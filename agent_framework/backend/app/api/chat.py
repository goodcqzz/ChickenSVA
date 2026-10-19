"""
对话路由

提供对话相关的RESTful API
"""

import asyncio
import json
from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException, status, Request
from fastapi.responses import StreamingResponse

from app.security import check_chat_allowance, client_ip_from_request
from app.config import settings

router = APIRouter()

_ALLOWED_PROVIDERS = frozenset({"qwen", "deepseek", "openrouter"})


def _enforce_chat_quota(http_request: Request) -> None:
    """HTTP 聊天接口防滥用：与 WebSocket 路径共用同一套 IP 限速 + 平台 Key 配额。

    HTTP 接口不接收按请求携带的 BYOK Key（始终走平台默认 Key），因此一律按
    平台用量计入限速/配额，防止有人绕过 WS 直接刷 HTTP 端点消耗平台 Key。
    """
    client_ip = client_ip_from_request(http_request)
    denial = check_chat_allowance(client_ip, using_own_key=False)
    if denial is not None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"code": denial["code"], "message": denial["message"]},
        )


def _coerce_provider(provider: Optional[str]) -> str:
    p = (provider or "qwen").strip()
    return p if p in _ALLOWED_PROVIDERS else "deepseek"


def _fallback_llm_config_from_settings() -> "LLMConfig":
    from app.llm.base import LLMConfig
    from app.config import settings

    prov = _coerce_provider(getattr(settings, "llm_provider", None))
    if prov == "deepseek":
        model = getattr(settings, "deepseek_model", "deepseek-v4-flash")
        key = getattr(settings, "deepseek_api_key", None) or ""
    elif prov == "qwen":
        model = getattr(settings, "qwen_model", "qwen-max")
        key = getattr(settings, "qwen_api_key", None) or ""
    else:
        model = "openai/gpt-4o"
        key = getattr(settings, "openrouter_api_key", None) or ""
    return LLMConfig(
        provider=prov,
        model=model,
        api_key=key,
        temperature=0.7,
        max_tokens=getattr(settings, "platform_default_max_tokens", 8192),
    )


class ChatMessage(BaseModel):
    """聊天消息模型"""
    role: str = Field(..., description="消息角色: user/assistant/system")
    content: str = Field(..., description="消息内容")
    timestamp: Optional[str] = Field(None, description="时间戳")


class ChatRequest(BaseModel):
    """对话请求模型"""
    session_id: str = Field(..., description="会话ID")
    message: str = Field(..., description="用户消息")
    context: Optional[List[ChatMessage]] = Field(None, description="上下文消息")
    stream: Optional[bool] = Field(False, description="是否流式响应")


class ChatResponse(BaseModel):
    """对话响应模型"""
    success: bool = Field(True, description="是否成功")
    message_id: str = Field(..., description="消息ID")
    content: str = Field(..., description="助手回复")
    state: str = Field("idle", description="当前状态")
    timestamp: str = Field(..., description="时间戳")
    tool_calls: Optional[List[dict]] = Field(None, description="工具调用记录")


class SessionHistoryResponse(BaseModel):
    """会话历史响应模型"""
    session_id: str = Field(..., description="会话ID")
    messages: List[ChatMessage] = Field(default_factory=list, description="消息列表")
    created_at: str = Field(..., description="创建时间")
    updated_at: str = Field(..., description="更新时间")


@router.post(
    "/chat",
    response_model=ChatResponse,
    status_code=status.HTTP_200_OK,
    summary="发送消息",
    description="发送消息到智能体并获取回复"
)
async def send_message(request: ChatRequest, http_request: Request) -> ChatResponse:
    """
    发送聊天消息
    
    通过HTTP接口发送消息，适合不需要实时响应的场景
    WebSocket连接优先使用WebSocket接口
    """
    _enforce_chat_quota(http_request)
    try:
        from app.agent.pool import get_agent_pool
        from app.llm.base import LLMConfig
        from app.llm_config_store import llm_config_store
        
        pool = get_agent_pool()
        if pool is None:
            raise HTTPException(status_code=503, detail="Agent服务未就绪")
        
        user_config = llm_config_store.get_config("default")
        
        if user_config and user_config.get("api_key"):
            prov = _coerce_provider(user_config.get("provider"))
            llm_config = LLMConfig(
                provider=prov,
                model=user_config.get("model") or "deepseek-v4-flash",
                api_key=user_config.get("api_key") or "",
                temperature=float(user_config.get("temperature", 0.7)),
                max_tokens=int(user_config.get("max_tokens", getattr(settings, "platform_default_max_tokens", 8192))),
                system_prompt=user_config.get("system_prompt") or "",
            )
        else:
            llm_config = _fallback_llm_config_from_settings()
        
        agent = await pool.get_or_create(request.session_id, llm_config)
        
        # 执行对话
        result = await agent.run(request.message, session_id=request.session_id, stream=False)
        
        return ChatResponse(
            success=True,
            message_id=f"msg_{datetime.utcnow().timestamp()}",
            content=result.answer,
            state="completed",
            timestamp=datetime.utcnow().isoformat(),
            tool_calls=result.tool_calls if hasattr(result, 'tool_calls') else None
        )
    except Exception as e:
        import logging
        logging.error(f"处理消息时出错: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="处理消息时出现内部错误，请稍后重试。",
        )


@router.get(
    "/chat/history/{session_id}",
    response_model=SessionHistoryResponse,
    status_code=status.HTTP_200_OK,
    summary="获取会话历史",
    description="获取指定会话的消息历史"
)
async def get_chat_history(session_id: str) -> SessionHistoryResponse:
    """
    获取会话历史记录
    
    返回指定会话的所有消息记录
    """
    try:
        from app.agent.pool import get_agent_pool
        
        pool = get_agent_pool()
        if pool is None:
            return SessionHistoryResponse(
                session_id=session_id,
                messages=[],
                created_at=datetime.utcnow().isoformat(),
                updated_at=datetime.utcnow().isoformat()
            )
        if session_id not in pool._pool:
            return SessionHistoryResponse(
                session_id=session_id,
                messages=[],
                created_at=datetime.utcnow().isoformat(),
                updated_at=datetime.utcnow().isoformat()
            )
        pooled = pool._pool[session_id]
        agent = pooled.agent
        
        # 从agent的memory中获取消息
        messages = []
        for msg in agent.memory.get_messages():
            messages.append(ChatMessage(
                role=msg.role.value,
                content=msg.content,
                timestamp=datetime.utcnow().isoformat()
            ))
        
        return SessionHistoryResponse(
            session_id=session_id,
            messages=messages,
            created_at=datetime.utcnow().isoformat(),
            updated_at=datetime.utcnow().isoformat()
        )
    except Exception as e:
        return SessionHistoryResponse(
            session_id=session_id,
            messages=[],
            created_at=datetime.utcnow().isoformat(),
            updated_at=datetime.utcnow().isoformat()
        )


@router.delete(
    "/chat/session/{session_id}",
    status_code=status.HTTP_200_OK,
    summary="删除会话",
    description="删除指定会话及其历史记录"
)
async def delete_session(session_id: str):
    """
    删除会话
    
    删除指定会话的所有数据
    """
    try:
        from app.agent.pool import get_agent_pool
        pool = get_agent_pool()
        if pool is None:
            raise HTTPException(status_code=503, detail="Agent服务未就绪")
        await pool.remove(session_id)
        return {"success": True, "message": "会话已删除"}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="删除会话时出现内部错误。",
        )


@router.post(
    "/chat/stream",
    status_code=status.HTTP_200_OK,
    summary="流式对话",
    description="发送消息并获取流式响应"
)
async def stream_chat(request: ChatRequest, http_request: Request):
    """
    流式对话接口
    
    返回SSE格式的流式响应
    """
    _enforce_chat_quota(http_request)
    from app.agent.pool import get_agent_pool
    from app.llm.base import LLMConfig

    pool = get_agent_pool()
    if pool is None:
        return StreamingResponse(
            _error_stream("Agent服务未就绪"),
            media_type="text/event-stream",
            status_code=503,
        )
    
    llm_config = _fallback_llm_config_from_settings()
    agent = await pool.get_or_create(request.session_id, llm_config)
    
    token_queue: asyncio.Queue[dict] = asyncio.Queue()
    done_event = asyncio.Event()
    
    async def on_token(session_id: str, token_data: dict) -> None:
        await token_queue.put(token_data)
    
    async def run_agent() -> None:
        try:
            agent.on_token = on_token
            await agent.run(request.message, session_id=request.session_id, stream=True)
        except Exception as e:
            await token_queue.put({"type": "error", "payload": {"message": str(e)}})
        finally:
            agent.on_token = None
            done_event.set()
    
    async def generate_stream():
        agent_task = asyncio.create_task(run_agent())
        try:
            while not done_event.is_set() or not token_queue.empty():
                try:
                    token_data = await asyncio.wait_for(token_queue.get(), timeout=0.5)
                    yield f"data: {json.dumps(token_data)}\n\n"
                except asyncio.TimeoutError:
                    continue
            yield f"data: {json.dumps({'type': 'complete'})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"
        finally:
            if not agent_task.done():
                agent_task.cancel()
                try:
                    await agent_task
                except asyncio.CancelledError:
                    pass
    
    return StreamingResponse(
        generate_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


async def _error_stream(message: str):
    yield f"data: {json.dumps({'type': 'error', 'error': message})}\n\n"
