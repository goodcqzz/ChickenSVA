"""
鸡基因组智能体框架 - 主应用入口

FastAPI应用主文件，包含：
- 应用配置和初始化
- CORS中间件
- 路由注册
- WebSocket端点（集成Agent引擎）
- 工具事件转发到前端
- 响应缓存
- 对话压缩
- 任务队列
- SV数据库
"""

import json
import logging
import asyncio
from contextlib import asynccontextmanager
import contextvars
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.api import chat, health, workspace, llm, mcp, rag
from app.middleware.auth import AuthMiddleware
from app.security import (
    install_rate_limiter,
    check_chat_allowance,
    extract_client_ip,
    init_quota_tracker,
    user_brought_own_key,
    redact_ws_payload_for_log,
)
from app.websocket.manager import WebSocketManager
from app.agent.core import AgentCore
from app.agent.tool_registry import create_default_registry, ToolRegistry
from app.agent.memory import ConversationMemory
from app.agent.pool import AgentPool, init_agent_pool, get_agent_pool
from app.agent.session_store import SessionStore
from app.agent.memory_compression import (
    MemoryCompressor, CompressionConfig,
    init_memory_compressor, get_memory_compressor
)
from app.llm.base import LLMConfig
from app.storage.database import init_db, close_db
from app.mcp.client import MCPClient
from app.mcp.bridge import MCPToolBridge

# 新增模块导入
from app.cache import ResponseCache, CacheConfig, init_response_cache, get_response_cache
from app.tasks import (
    TaskQueue, TaskWorker, WorkerPool,
    init_task_queue, get_task_queue,
    handle_imputation_task
)
from app.data import (
    SVDatabase, SVDatabaseConfig,
    init_sv_database, get_sv_database,
    DataAdapter, init_data_adapter
)

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format=settings.log_format,
)
logger = logging.getLogger(__name__)

ws_manager = WebSocketManager(
    max_connections=settings.ws_max_connections,
    broadcast_batch_size=settings.ws_broadcast_batch_size,
    cleanup_interval=settings.ws_cleanup_interval
)
tool_registry = create_default_registry()
mcp_client = MCPClient()
mcp_bridge = MCPToolBridge(mcp_client, tool_registry)

# 全局实例（将在 lifespan 中初始化）
agent_pool: AgentPool | None = None
response_cache: ResponseCache | None = None
memory_compressor: MemoryCompressor | None = None
task_queue: TaskQueue | None = None
worker_pool: WorkerPool | None = None
sv_database: SVDatabase | None = None
data_adapter: DataAdapter | None = None
session_store: SessionStore | None = None

# 存储当前正在处理消息的会话ID（使用 ContextVar 避免并发竞争）
_current_active_session: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("current_active_session", default=None)


async def _tool_event_handler(event_type: str, payload: Dict[str, Any], session_id: Optional[str] = None):
    target_session = session_id or _current_active_session.get()
    
    if event_type == "workspace_activate" and target_session:
        await ws_manager.send_to_session(target_session, {
            "type": "workspace_activate",
            "payload": payload,
        })


tool_registry.set_event_callback(_tool_event_handler)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global agent_pool, response_cache, memory_compressor, task_queue, worker_pool, sv_database, data_adapter, session_store
    
    logger.info(f"启动 {settings.app_name} v{settings.app_version}")
    logger.info(f"环境: {settings.app_env}")

    await init_db()
    logger.info("数据库初始化完成")

    # 初始化会话历史持久化（SQLite），使重启/重连后可恢复上下文
    if settings.session_persistence_enabled:
        try:
            session_store = SessionStore(
                db_path=settings.session_db_path,
                ttl_days=settings.session_ttl_days,
            )
            pruned = await session_store.prune()
            logger.info("会话持久化初始化完成（清理过期 %s 条）", pruned)
        except Exception as e:
            session_store = None
            logger.warning("会话持久化初始化失败，将以无持久化模式运行：%s", e)

    # 初始化 Agent Pool
    agent_pool = init_agent_pool(
        tool_registry=tool_registry,
        max_size=settings.agent_pool_max_size,
        idle_timeout=settings.agent_pool_idle_timeout,
        max_age=settings.agent_pool_max_age,
    )
    await agent_pool.start()
    logger.info("Agent Pool 初始化完成")

    # 初始化响应缓存
    if settings.cache_enabled:
        cache_config = CacheConfig(
            memory_max_size=settings.cache_memory_max_size,
            memory_ttl=settings.cache_memory_ttl,
            persistent_enabled=settings.cache_persistent_enabled,
            persistent_path=settings.cache_persistent_path,
            persistent_max_size=settings.cache_persistent_max_size,
            persistent_ttl=settings.cache_persistent_ttl,
        )
        response_cache = init_response_cache(cache_config)
        await response_cache.start()
        logger.info("响应缓存初始化完成")

    # 初始化对话压缩
    if settings.compression_enabled:
        compression_config = CompressionConfig(
            max_messages=settings.compression_max_messages,
            max_tokens=settings.compression_max_tokens,
            strategy=settings.compression_strategy,
            preserve_recent=settings.compression_preserve_recent,
        )
        memory_compressor = init_memory_compressor(compression_config)
        logger.info("对话压缩初始化完成")

    # 初始化任务队列
    if settings.task_queue_enabled:
        task_queue = init_task_queue(
            db_path=settings.task_queue_db_path,
            max_concurrent=settings.task_queue_max_concurrent,
        )
        await task_queue.start()
        
        # 启动工作器池
        worker_pool = WorkerPool(task_queue, num_workers=settings.task_queue_num_workers)
        worker_pool.register_handler("imputation", handle_imputation_task)
        await worker_pool.start()
        logger.info(f"任务队列初始化完成: {settings.task_queue_num_workers} 个工作器")

    # 初始化 SV 数据库
    if settings.sv_db_enabled:
        sv_config = SVDatabaseConfig(
            db_type=settings.sv_db_type,
            host=settings.sv_db_host,
            port=settings.sv_db_port,
            database=settings.sv_db_name,
            username=settings.sv_db_user,
            password=settings.sv_db_password,
            sqlite_path=settings.sv_db_sqlite_path,
            csv_path=settings.sv_db_csv_path,
        )
        sv_database = init_sv_database(sv_config)
        await sv_database.connect()

        # 初始化数据适配器
        data_adapter = init_data_adapter(sv_database)
        logger.info("SV 数据库初始化完成")

    # 启动 WebSocket 管理器
    await ws_manager.start()
    logger.info("WebSocket 管理器已启动")

    mcp_ok = await mcp_client.initialize()
    if mcp_ok:
        bridged = await mcp_bridge.bridge_all_tools()
        logger.info(f"MCP工具桥接完成: {bridged}个工具")
    else:
        logger.warning("MCP服务器未连接，跳过工具桥接")

    yield

    logger.info("关闭应用...")
    await ws_manager.stop()
    
    if agent_pool:
        await agent_pool.stop()
    
    if response_cache:
        await response_cache.stop()
    
    if worker_pool:
        await worker_pool.stop()
    
    if task_queue:
        await task_queue.stop()
    
    if sv_database:
        await sv_database.disconnect()
    
    await close_db()
    await mcp_client.close()


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="鸡基因组智能体框架后端服务",
        docs_url="/docs" if settings.debug else None,
        redoc_url="/redoc" if settings.debug else None,
        lifespan=lifespan,
    )

    app.add_middleware(GZipMiddleware, minimum_size=1000)
    app.add_middleware(AuthMiddleware)

    # 限速器（按 IP，公网部署防滥用）
    install_rate_limiter(app)
    # 默认模型每日配额（SQLite 计数）
    init_quota_tracker()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_origin_regex=settings.cors_origin_regex,
        allow_credentials=settings.cors_allow_credentials,
        allow_methods=settings.cors_allow_methods,
        allow_headers=settings.cors_allow_headers,
    )

    if settings.is_production:
        @app.middleware("http")
        async def security_headers(request, call_next):
            response = await call_next(request)
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
            response.headers["X-Frame-Options"] = "DENY"
            return response

    app.include_router(health.router, prefix="/api/v1", tags=["健康检查"])
    app.include_router(chat.router, prefix="/api/v1", tags=["对话接口"])
    app.include_router(workspace.router, prefix="/api/v1", tags=["工作区接口"])
    app.include_router(rag.router, prefix="/api/v1", tags=["知识库检索"])
    app.include_router(llm.router, prefix="/api/v1/llm", tags=["LLM配置"])
    app.include_router(mcp.router, prefix="/api/v1/mcp", tags=["MCP管理"])

    @app.websocket("/ws/{session_id}")
    async def websocket_endpoint(websocket: WebSocket, session_id: str):
        logger.info(f"收到WebSocket连接请求 [{session_id}]")

        # 解析客户端真实 IP（可信代理感知，抵抗 X-Forwarded-For 伪造）
        client_ip = extract_client_ip(
            websocket.headers.get("x-forwarded-for"),
            websocket.headers.get("x-real-ip"),
            websocket.client.host if websocket.client else None,
        )
        _session_client_ip[session_id] = client_ip

        try:
            await websocket.accept()
            logger.info(f"WebSocket连接已接受 [{session_id}] ip={client_ip}")
        except Exception as e:
            logger.error(f"WebSocket accept失败 [{session_id}]: {e}")
            return

        ws_manager.register(session_id, websocket)

        try:
            await ws_manager.send_to_session(session_id, {
                "type": "connected",
                "payload": {"session_id": session_id, "message": "连接成功"},
            })
            logger.info(f"已发送连接成功消息 [{session_id}]")

            while True:
                try:
                    data = await websocket.receive_text()
                    logger.debug(f"收到消息 [{session_id}]: {redact_ws_payload_for_log(data)}")
                    await _handle_ws_message(session_id, data)
                except WebSocketDisconnect:
                    logger.info(f"客户端主动断开连接 [{session_id}]")
                    break
                except Exception as e:
                    logger.error(f"接收消息时出错 [{session_id}]: {type(e).__name__}: {e}")
                    break

        except Exception as e:
            logger.error(f"WebSocket处理异常 [{session_id}]: {type(e).__name__}: {e}")
        finally:
            ws_manager.unregister(session_id)
            _session_client_ip.pop(session_id, None)
            # 使用 Agent Pool 释放会话（标记为非活跃，允许复用）
            if agent_pool:
                await agent_pool.release(session_id)
            logger.info(f"连接清理完成 [{session_id}]")

    app.state.ws_manager = ws_manager
    app.state.tool_registry = tool_registry

    return app


async def _handle_ws_message(session_id: str, data: str) -> None:
    try:
        message = json.loads(data)
    except json.JSONDecodeError:
        await ws_manager.send_to_session(session_id, {
            "type": "error",
            "payload": {"code": "INVALID_JSON", "message": "消息格式错误"},
        })
        return

    msg_type = message.get("type", "unknown")

    if msg_type == "ping":
        ws_manager.touch(session_id)
        await ws_manager.send_to_session(session_id, {
            "type": "pong",
            "payload": {"timestamp": datetime.utcnow().timestamp()},
        })
        return

    if msg_type == "cancel":
        await _cancel_active_chat(session_id)
        return

    if msg_type == "chat":
        payload = message.get("payload", {})
        content = payload.get("content", "")
        llm_config_dict = payload.get("llm_config", {})

        if not content:
            return

        client_ip = _session_client_ip.get(session_id, "unknown")
        using_own_key = user_brought_own_key(llm_config_dict)

        # 统一的防滥用检查：通用 IP 限速 + 平台默认 Key 的 burst/日配额（BYOK 不受限）
        denial = check_chat_allowance(client_ip, using_own_key)
        if denial is not None:
            await ws_manager.send_to_session(session_id, {
                "type": "message_end",
                "payload": {
                    "role": "assistant",
                    "content": denial["message"],
                    "state": "error",
                    "code": denial["code"],
                },
            })
            return

        if session_id in _processing_sessions:
            await _cancel_active_chat(session_id)

        asyncio.create_task(_process_chat(session_id, content, llm_config_dict))
        return

    if msg_type == "upload_complete":
        payload = message.get("payload", {})
        await ws_manager.send_to_session(session_id, {
            "type": "message",
            "payload": {
                "role": "assistant",
                "content": f"文件上传完成: {payload.get('files', [])}",
                "state": "idle",
            },
        })
        return

    logger.warning(f"未知消息类型 [{session_id}]: {msg_type}")


_processing_sessions: Set[str] = set()
_processing_lock = asyncio.Lock()
_active_chat_tasks: Dict[str, asyncio.Task] = {}
# session_id -> 客户端真实 IP（用于限速 / 配额）
_session_client_ip: Dict[str, str] = {}


async def _cancel_active_chat(session_id: str) -> None:
    task = _active_chat_tasks.get(session_id)
    if task and not task.done():
        logger.info(f"取消旧的聊天任务 [{session_id}]")
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.debug(f"取消旧任务时出现异常 [{session_id}]: {exc}")
    _active_chat_tasks.pop(session_id, None)
    async with _processing_lock:
        _processing_sessions.discard(session_id)


async def _chat_keepalive_loop(session_id: str, interval: int = 10) -> None:
    try:
        while True:
            await asyncio.sleep(interval)
            await ws_manager.send_to_session(session_id, {
                "type": "pong",
                "payload": {"timestamp": datetime.utcnow().timestamp(), "source": "keepalive"},
            })
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.debug(f"keepalive循环退出 [{session_id}]: {exc}")


async def _process_chat(
    session_id: str,
    content: str,
    llm_config_dict: Dict[str, Any],
) -> None:
    global _current_active_session

    if session_id in _processing_sessions:
        await ws_manager.send_to_session(session_id, {
            "type": "message_end",
            "payload": {
                "role": "assistant",
                "content": "上一条消息仍在处理中，请稍后再试。",
                "state": "error",
            },
        })
        return

    async with _processing_lock:
        if session_id in _processing_sessions:
            await ws_manager.send_to_session(session_id, {
                "type": "message_end",
                "payload": {
                    "role": "assistant",
                    "content": "上一条消息仍在处理中，请稍后再试。",
                    "state": "error",
                },
            })
            return
        _processing_sessions.add(session_id)

    current_task = asyncio.current_task()
    if current_task is not None:
        _active_chat_tasks[session_id] = current_task

    await ws_manager.send_to_session(session_id, {
        "type": "message_start",
        "payload": {"role": "assistant", "state": "thinking"},
    })

    keepalive_task = asyncio.create_task(_chat_keepalive_loop(session_id))

    try:
        session_token = _current_active_session.set(session_id)
        
        if not agent_pool:
            raise RuntimeError("Agent Pool 未初始化")
        
        llm_config = _build_llm_config(llm_config_dict)
        logger.info(f"LLM配置 [{session_id}]: provider={llm_config.provider}, model={llm_config.model}, api_key={'***' + llm_config.api_key[-4:] if llm_config.api_key and len(llm_config.api_key) > 4 else '未配置'}")
        agent = await agent_pool.get_or_create(session_id, llm_config)

        # 进程内无历史时（重启/新连接命中持久化会话），尝试从磁盘恢复上下文
        if session_store is not None and agent.memory.get_message_count() == 0:
            try:
                saved_messages = await session_store.load(session_id)
                if saved_messages:
                    agent.memory.from_dict(saved_messages)
                    logger.info("已从持久化恢复会话历史 [%s]: %s 条", session_id, len(saved_messages))
            except Exception as e:
                logger.warning("恢复会话历史失败 [%s]：%s", session_id, e)

        async def on_token(sid: str, token_data: Dict[str, Any]) -> None:
            await ws_manager.send_to_session(sid, token_data)

        agent.on_token = on_token

        result = await agent.run(
            user_message=content,
            session_id=session_id,
            stream=True,
        )

        agent.on_token = None

        # 本轮完成后持久化最新历史（best-effort，失败不影响对话）
        if session_store is not None:
            try:
                await session_store.save(session_id, agent.memory.to_dict())
            except Exception as e:
                logger.warning("持久化会话历史失败 [%s]：%s", session_id, e)
        
        _current_active_session.set(None)

        await ws_manager.send_to_session(session_id, {
            "type": "message_end",
            "payload": {
                "role": "assistant",
                "content": result.answer,
                "state": "idle",
                "tool_calls": result.tool_calls,
                "steps": len(result.steps),
            },
        })

    except asyncio.CancelledError:
        logger.info(f"Agent处理已取消 [{session_id}]")
        _current_active_session.set(None)
        raise
    except Exception as e:
        logger.error(f"Agent处理失败 [{session_id}]: {e}", exc_info=True)
        _current_active_session.set(None)
        try:
            safe_msg = "处理消息时出现内部错误，请稍后重试。"
            error_str = str(e).lower()
            if "api_key" in error_str or "apikey" in error_str or "unauthorized" in error_str or "401" in error_str:
                safe_msg = "API Key 无效或未配置，请检查大模型配置。"
            elif "rate_limit" in error_str or "429" in error_str:
                safe_msg = "API 调用频率超限，请稍后重试。"
            elif "timeout" in error_str:
                safe_msg = "请求超时，请稍后重试。"
            await ws_manager.send_to_session(session_id, {
                "type": "message_end",
                "payload": {
                    "role": "assistant",
                    "content": safe_msg,
                    "state": "error",
                },
            })
        except Exception:
            pass
    finally:
        keepalive_task.cancel()
        try:
            await keepalive_task
        except asyncio.CancelledError:
            pass
        async with _processing_lock:
            _processing_sessions.discard(session_id)
        if _active_chat_tasks.get(session_id) is current_task:
            _active_chat_tasks.pop(session_id, None)


# 注意：Agent 管理已迁移到 AgentPool，保留此函数用于兼容性
# 新代码应直接使用 agent_pool.get_or_create()
def _get_or_create_agent(
    session_id: str,
    llm_config_dict: Dict[str, Any],
) -> AgentCore:
    """已弃用：请使用 agent_pool.get_or_create()"""
    if agent_pool:
        llm_config = _build_llm_config(llm_config_dict) if llm_config_dict else None
        # 使用 asyncio.run_coroutine_threadsafe 或确保在异步上下文中调用
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # 如果在运行的事件循环中，创建任务
                future = asyncio.ensure_future(agent_pool.get_or_create(session_id, llm_config))
                # 这里不能直接等待，需要调用者处理
                raise RuntimeError("请在异步上下文中使用 agent_pool.get_or_create() 直接获取 Agent")
            else:
                return loop.run_until_complete(agent_pool.get_or_create(session_id, llm_config))
        except RuntimeError:
            raise RuntimeError("请在异步上下文中使用 agent_pool.get_or_create() 直接获取 Agent")
    raise RuntimeError("Agent Pool 未初始化")


def _read_system_prompt_fallback() -> str:
    """与 /api/v1/llm/config/default 一致：仓库内 Agent 系统提示词。"""
    prompt_path = (
        Path(__file__).resolve().parents[2]
        / "frontend"
        / "src"
        / "prompts"
        / "Agent_prompt.md"
    )
    try:
        return prompt_path.read_text(encoding="utf-8")
    except Exception:
        return (
            "你是鸡基因组结构变异分析助手，优先使用 query_sv、query_annotation 和填充工作流。"
        )


def _default_model_for_provider(provider: str) -> str:
    """按 provider 返回平台默认模型 ID（与 settings 字段保持一致）。"""
    mapping = {
        "deepseek": settings.deepseek_model or "deepseek-v4-flash",
        "qwen": settings.qwen_model or "qwen-max",
        "openrouter": "openai/gpt-4o",
    }
    return mapping.get(provider, "deepseek-v4-flash")


def _pick_top_k(config_dict: Dict[str, Any], saved: Dict[str, Any]) -> Optional[int]:
    raw = config_dict.get("top_k")
    if raw is None:
        raw = config_dict.get("topK")
    if raw is None:
        raw = saved.get("top_k")
    if raw is None or raw == "":
        return None
    try:
        v = int(float(raw))
        return v if v >= 1 else None
    except (TypeError, ValueError):
        return None


def _build_llm_config(config_dict: Dict[str, Any]) -> LLMConfig:
    """
    从 WebSocket 消息 + 后端存储合并出最终的 LLMConfig。
    优先顺序：实时消息 > 后端存储 > 环境变量 > 硬编码默认值
    """
    from app.llm_config_store import llm_config_store

    saved = llm_config_store.get_config("default") or {}

    def _pick(key: str, *candidates, default=None):
        """从多个候选值中挑选第一个有效的"""
        for c in candidates:
            if c is not None and c != "":
                return c
        return default

    provider = _pick(
        "provider",
        config_dict.get("provider"),
        saved.get("provider"),
        settings.llm_provider or "deepseek",
    )
    allowed = frozenset({"qwen", "deepseek", "openrouter"})
    if provider not in allowed:
        provider = "qwen"
    # 公网/多用户安全策略：
    # 当 persist_user_api_keys=False 时，磁盘 llm_config.json 中的 api_keys / api_key
    # 一律视为不可信（避免任何残留）。仅信任：① 本次 WS 携带的 Key；② 服务端环境变量。
    key_for_provider = ""
    if settings.persist_user_api_keys:
        api_keys_saved = saved.get("api_keys") or {}
        if isinstance(api_keys_saved, dict):
            key_for_provider = api_keys_saved.get(provider) or ""
        if not key_for_provider:
            key_for_provider = saved.get("api_key") or ""

    using_own_key = user_brought_own_key(config_dict)

    api_key = _pick(
        None,
        config_dict.get("api_key"),
        config_dict.get("apiKey"),
        key_for_provider,
        "",
    )
    if not api_key:
        # 服务端环境变量提供的默认 Key（平台默认模型）
        if settings.public_default_model_enabled:
            env_key_map = {
                "deepseek": settings.deepseek_api_key,
                "qwen": settings.qwen_api_key,
                "openrouter": settings.openrouter_api_key,
            }
            api_key = env_key_map.get(provider) or ""

    # 安全：仅当用户自带 Key（BYOK）时才允许覆盖 base_url。
    # 否则（使用平台默认 Key）强制忽略客户端传入的 base_url，由 provider 写死官方
    # endpoint，避免「空 Key → 填入平台 Key → 发往攻击者 base_url」导致平台 Key 外泄/SSRF。
    if using_own_key:
        base_url = _pick(
            "base_url",
            config_dict.get("base_url"),
            config_dict.get("baseUrl"),
            saved.get("base_url"),
            None,
        )
    else:
        base_url = None

    # 系统提示词始终以仓库 Agent_prompt.md 为准，避免依赖全局槽中的陈旧快照
    system_prompt = _read_system_prompt_fallback()

    # 低温度默认，降低事实型问答的杜撰风险
    temperature = _pick("temperature", config_dict.get("temperature"), saved.get("temperature"), 0.2)
    top_p = _pick("top_p", config_dict.get("topP"), saved.get("top_p"), 0.9)
    # 平台默认 Key：服务端钳制为低温度上限（防杜撰、防滥用）；BYOK 用户保留自定义自由度
    if not using_own_key:
        try:
            temperature = min(float(temperature), 0.3)
        except (TypeError, ValueError):
            temperature = 0.2
        try:
            top_p = min(float(top_p), 0.9)
        except (TypeError, ValueError):
            top_p = 0.9

    return LLMConfig(
        provider=provider,
        model=_pick(
            "model",
            config_dict.get("model"),
            saved.get("model"),
            _default_model_for_provider(provider),
        ),
        api_key=api_key,
        temperature=temperature,
        max_tokens=_pick("max_tokens", config_dict.get("maxTokens"), saved.get("max_tokens"), settings.platform_default_max_tokens),
        top_p=top_p,
        frequency_penalty=_pick("frequency_penalty", config_dict.get("frequencyPenalty"), saved.get("frequency_penalty"), 0.0),
        presence_penalty=_pick("presence_penalty", config_dict.get("presencePenalty"), saved.get("presence_penalty"), 0.0),
        enable_online_search=bool(_pick("enable_online_search", config_dict.get("enableOnlineSearch"), saved.get("enable_online_search"), False)),
        enable_reasoning=bool(_pick("enable_reasoning", config_dict.get("enableReasoning"), saved.get("enable_reasoning"), False)),
        top_k=_pick_top_k(config_dict, saved),
        reasoning_effort=_pick(
            None,
            config_dict.get("reasoning_effort"),
            config_dict.get("reasoningEffort"),
            saved.get("reasoning_effort"),
            None,
        ),
        system_prompt=system_prompt,
        base_url=base_url,
    )


app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.reload,
        log_level=settings.log_level.lower(),
    )
