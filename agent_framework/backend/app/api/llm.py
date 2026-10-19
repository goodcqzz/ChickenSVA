"""
大语言模型API

提供模型列表获取、模型配置管理、能力表查询和连接测试。
"""

from typing import Dict, List, Optional, Any
from pathlib import Path
from fastapi import APIRouter, HTTPException, status, Query, Body, Header

import httpx
import logging

from app.llm_config import (
    ProviderRegistry,
    get_provider_config,
    fetch_models_for_provider,
    get_model_capabilities,
    capabilities_to_dict,
    generate_param_controls,
    get_param_panel_metadata,
    build_request_payload,
    get_safe_params_for_probe,
    ModelCatalog,
)
from app.llm_config.model_catalog import ModelEntry
from app.llm_config_store import llm_config_store, DEFAULT_LLM_CONFIG
from app.schemas.llm import (
    LLMSettings,
    LLMActiveConfigPublic,
    ModelInfoSchema,
    ProviderModelsSchema,
    CapabilitiesLookupRequest,
    CapabilitiesResponseSchema,
    TestConnectionRequest,
    TestConnectionResponse,
    ProviderMetaSchema,
    LLMConfigResponseSchema,
)

router = APIRouter()
logger = logging.getLogger(__name__)


def _agent_system_prompt_path() -> Path:
    return (
        Path(__file__).resolve().parents[3]
        / "frontend"
        / "src"
        / "prompts"
        / "Agent_prompt.md"
    )


def _read_agent_system_prompt_text() -> str:
    """与仓库 frontend 内 Agent_prompt.md 一致。"""
    prompt_path = _agent_system_prompt_path()
    try:
        return prompt_path.read_text(encoding="utf-8")
    except Exception:
        return (
            "你是鸡基因组结构变异分析助手，优先使用 query_sv、query_annotation 和填充工作流。"
        )


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _entry_raw_meta(e: ModelEntry) -> Optional[Dict[str, Any]]:
    m = e.raw_meta
    if isinstance(m, dict) and m:
        return m
    return None


def _model_entry_to_schema(e: ModelEntry) -> ModelInfoSchema:
    return ModelInfoSchema(
        id=e.id,
        name=e.name,
        provider=e.provider,
        description=e.description,
        max_tokens=e.max_tokens,
        context_window=e.context_window,
        raw_meta=_entry_raw_meta(e),
    )


def _build_model_info_list(provider_id: str) -> List[ModelInfoSchema]:
    """从内置模型目录构建模型信息列表"""
    entries = ModelCatalog.get_cached_models(provider_id)
    return [_model_entry_to_schema(e) for e in entries]


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------

@router.get(
    "/providers",
    response_model=List[ProviderMetaSchema],
    summary="获取供应商列表",
    description="获取所有支持的LLM供应商元数据"
)
async def get_providers() -> List[ProviderMetaSchema]:
    """获取供应商元数据列表"""
    builtins = ModelCatalog.get_cached_models
    return [
        ProviderMetaSchema(
            id=p.id,
            name=p.name,
            name_zh=p.name_zh,
            base_url=p.base_url,
            supports_models_endpoint=p.supports_models_endpoint,
            default_model=builtins(p.id)[0].id if builtins(p.id) else "",
        )
        for p in ProviderRegistry.list_providers()
    ]


@router.get(
    "/models",
    response_model=List[ProviderModelsSchema],
    summary="获取可用模型列表",
    description="获取所有支持的LLM提供商及其模型列表（内置兜底）"
)
async def get_models() -> List[ProviderModelsSchema]:
    return [
        ProviderModelsSchema(
            provider=pid,
            models=_build_model_info_list(pid)
        )
        for pid in ProviderRegistry.list_ids()
    ]


@router.get(
    "/models/live",
    response_model=List[ProviderModelsSchema],
    summary="实时拉取模型列表",
    description="从供应商 API 实时拉取模型列表，需要 api_key"
)
async def get_live_models(
    provider: str = Query(..., description="供应商ID"),
    api_key: str = Query(..., description="API密钥"),
    base_url: Optional[str] = Query(None, description="自定义base_url"),
) -> List[ProviderModelsSchema]:
    if provider not in ProviderRegistry.list_ids():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"不支持的提供商: {provider}"
        )

    models = await fetch_models_for_provider(provider, api_key, base_url, force_refresh=True)
    return [
        ProviderModelsSchema(
            provider=provider,
            models=[_model_entry_to_schema(m) for m in models],
        )
    ]


@router.get(
    "/models/{provider}",
    response_model=List[ModelInfoSchema],
    summary="获取指定提供商的模型",
    description="获取特定提供商支持的所有模型（内置兜底）"
)
async def get_provider_models(provider: str) -> List[ModelInfoSchema]:
    if provider not in ProviderRegistry.list_ids():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"不支持的提供商: {provider}"
        )
    return _build_model_info_list(provider)


@router.get(
    "/capabilities/{provider}/{model}",
    response_model=CapabilitiesResponseSchema,
    summary="获取模型能力表",
    description="获取指定模型支持哪些参数及限制"
)
async def get_capabilities(provider: str, model: str) -> CapabilitiesResponseSchema:
    if provider not in ProviderRegistry.list_ids():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"不支持的提供商: {provider}"
        )

    meta = get_param_panel_metadata(provider, model)
    return CapabilitiesResponseSchema(
        provider=meta["provider"],
        model=meta["model"],
        capabilities=meta["capabilities"],
        controls=meta["controls"],
        used_raw_meta=False,
    )


@router.post(
    "/capabilities/lookup",
    response_model=CapabilitiesResponseSchema,
    summary="获取模型能力表（含接口元数据）",
    description="与 GET 能力接口相同，但可在 body 中传入 /models 返回的 raw_meta，以合并 supported_parameters 等",
)
async def post_capabilities_lookup(
    body: CapabilitiesLookupRequest = Body(...),
) -> CapabilitiesResponseSchema:
    if body.provider not in ProviderRegistry.list_ids():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"不支持的提供商: {body.provider}",
        )
    api_meta = body.raw_meta if body.raw_meta else None
    meta = get_param_panel_metadata(body.provider, body.model, api_meta=api_meta)
    return CapabilitiesResponseSchema(
        provider=meta["provider"],
        model=meta["model"],
        capabilities=meta["capabilities"],
        controls=meta["controls"],
        used_raw_meta=bool(api_meta),
    )


@router.post(
    "/test-connection",
    response_model=TestConnectionResponse,
    summary="测试连接",
    description="用极短 prompt、max_tokens=1 测试模型连通性"
)
async def test_connection(request: TestConnectionRequest) -> TestConnectionResponse:
    provider_cfg = get_provider_config(request.provider)
    if not provider_cfg:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"不支持的提供商: {request.provider}"
        )

    import time
    base_url = ProviderRegistry.get_base_url(request.provider, request.base_url)
    headers = provider_cfg.build_auth_header(request.api_key)
    headers["Content-Type"] = "application/json"
    headers.update(provider_cfg.default_headers)

    safe_params = get_safe_params_for_probe(request.provider, request.model)
    tested: Dict[str, Any] = {}
    actual_error: Optional[str] = None
    latency_ms: Optional[int] = None

    t0 = time.time()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0)) as client:
            response = await client.post(
                f"{base_url}{provider_cfg.chat_endpoint}",
                headers=headers,
                json=safe_params,
            )
            response.raise_for_status()
        latency_ms = int((time.time() - t0) * 1000)
        tested = {k: v for k, v in safe_params.items() if k not in ("messages",)}
    except httpx.HTTPStatusError as e:
        latency_ms = int((time.time() - t0) * 1000)
        actual_error = f"HTTP {e.response.status_code}: {e.response.text[:200]}"
        # 尝试从错误响应推断哪些参数不被支持
        error_text = e.response.text.lower()
        if "temperature" in error_text:
            actual_error += " [推断: temperature 参数可能不被支持或受限]"
        if "top_p" in error_text:
            actual_error += " [推断: top_p 参数可能不被支持]"
        if "max_tokens" in error_text:
            actual_error += " [推断: max_tokens 参数可能不被支持或名称不同]"
    except httpx.ConnectTimeout:
        latency_ms = int((time.time() - t0) * 1000)
        actual_error = "连接超时：无法访问供应商服务器，请检查网络或 base_url 配置"
    except httpx.ReadTimeout:
        latency_ms = int((time.time() - t0) * 1000)
        actual_error = "读取超时：服务器响应过慢"
    except httpx.NetworkError as e:
        latency_ms = int((time.time() - t0) * 1000)
        actual_error = f"网络错误 ({type(e).__name__})：无法建立连接"
    except Exception as e:
        latency_ms = int((time.time() - t0) * 1000)
        actual_error = f"请求异常 ({type(e).__name__}): {e}"

    suggested_caps = capabilities_to_dict(
        get_model_capabilities(request.provider, request.model)
    )
    if actual_error:
        error_lower = actual_error.lower()
        if "temperature" in error_lower:
            suggested_caps["temperature"]["supported"] = False
        if "top_p" in error_lower:
            suggested_caps["top_p"]["supported"] = False
        if "max_tokens" in error_lower:
            suggested_caps["max_tokens"]["supported"] = False

    return TestConnectionResponse(
        success=actual_error is None,
        message="连接成功" if actual_error is None else f"连接失败: {actual_error}",
        provider=request.provider,
        model=request.model,
        latency_ms=latency_ms,
        tested_params=tested,
        actual_error=actual_error,
        capabilities=suggested_caps,
    )


@router.post(
    "/config",
    response_model=LLMConfigResponseSchema,
    summary="保存LLM配置",
    description="保存用户的LLM配置偏好"
)
async def save_llm_config(
    config: LLMSettings,
    x_admin_token: Optional[str] = Header(default=None, alias="X-Admin-Token"),
) -> LLMConfigResponseSchema:
    # 基础校验
    if config.provider not in ProviderRegistry.list_ids():
        return LLMConfigResponseSchema(
            success=False,
            message=f"不支持的提供商: {config.provider}"
        )

    # 用能力表校验参数合法性
    caps = get_model_capabilities(config.provider, config.model)

    temp_cap = caps.get("temperature")
    if temp_cap and temp_cap.fixed is not None and config.temperature != temp_cap.fixed:
        return LLMConfigResponseSchema(
            success=False,
            message=f"模型 {config.model} 的 temperature 必须固定为 {temp_cap.fixed}"
        )

    if config.enable_online_search:
        ws_cap = caps.get("web_search")
        if not ws_cap or not ws_cap.supported:
            return LLMConfigResponseSchema(
                success=False,
                message=f"模型 {config.model} 不支持联网搜索"
            )

    if config.enable_reasoning:
        re_cap = caps.get("reasoning_effort")
        if not re_cap or not re_cap.supported:
            return LLMConfigResponseSchema(
                success=False,
                message=f"模型 {config.model} 不支持深度思考模式"
            )

    from app.config import settings as _app_settings

    # 公网多用户安全策略：全局 "default" 槽是所有用户共享的平台配置，
    # 未持管理员令牌的请求（含旧版前端设置面板的下拉框即时保存）一律不写入。
    # 返回 success=True 以兼容旧前端 UI（其仅在失败时弹错）；个人偏好仍保留在浏览器本地。
    admin_token = (getattr(_app_settings, "llm_config_admin_token", "") or "").strip()
    provided_token = (x_admin_token or "").strip()
    if not admin_token or provided_token != admin_token:
        logger.info(
            "LLM 全局配置写入被忽略（已配置管理员令牌=%s，请求携带令牌=%s，model=%s）",
            bool(admin_token),
            bool(provided_token),
            config.model,
        )
        return LLMConfigResponseSchema(
            success=True,
            message="配置已保留在浏览器本地（服务端全局配置已锁定，平台默认模型不随网页设置变更）",
            config=config,
        )

    # 保存配置：系统提示词始终以仓库 Agent_prompt.md 为准
    # 安全策略：当 settings.persist_user_api_keys=False（公网/多用户模式），
    # 后端拒绝持久化任何用户提交的 API Key，仅保留服务端环境变量提供的默认 Key（如有）。
    prev = llm_config_store.get_config("default") or {}
    api_keys = dict(prev.get("api_keys") or {})
    if _app_settings.persist_user_api_keys and config.api_key:
        api_keys[config.provider] = config.api_key

    dump = config.model_dump(exclude_none=False)
    dump["system_prompt"] = _read_agent_system_prompt_text()
    dump["api_keys"] = api_keys
    dump["api_key"] = api_keys.get(config.provider) or prev.get("api_key")
    if not _app_settings.persist_user_api_keys:
        # 显式抹掉本次请求中的 api_key，确保不被任何后续路径写盘
        dump["api_key"] = api_keys.get(config.provider) or ""

    llm_config_store.save_config("default", dump)

    return LLMConfigResponseSchema(
        success=True,
        message="配置保存成功",
        config=config,
    )


@router.get(
    "/config/active",
    response_model=LLMActiveConfigPublic,
    summary="获取当前已保存的 LLM 配置（无密钥）",
    description="从服务端 llm_config.json 读取已持久化的供应商/模型/采样参数，用于前端与对话全局对齐；不包含明文 API Key",
)
async def get_active_llm_config() -> LLMActiveConfigPublic:
    cfg = llm_config_store.get_config("default")
    if not cfg:
        return LLMActiveConfigPublic()

    api_keys = cfg.get("api_keys") or {}
    present: Dict[str, bool] = {}
    if isinstance(api_keys, dict):
        for k, v in api_keys.items():
            present[str(k)] = bool(v)

    key_ok = bool(cfg.get("api_key")) or (
        isinstance(api_keys, dict) and any(bool(v) for v in api_keys.values())
    )

    def _f(name: str, default: float) -> float:
        try:
            return float(cfg.get(name, default))
        except (TypeError, ValueError):
            return default

    def _i(name: str, default: int) -> int:
        try:
            return int(cfg.get(name, default))
        except (TypeError, ValueError):
            return default

    tk = cfg.get("top_k")
    top_k: Optional[int] = None
    if tk is not None and tk != "":
        try:
            top_k = int(float(tk))
        except (TypeError, ValueError):
            top_k = None

    prov = str(cfg.get("provider") or "deepseek")
    if prov not in ProviderRegistry.list_ids():
        prov = "deepseek"

    return LLMActiveConfigPublic(
        provider=prov,
        model=str(cfg.get("model") or "deepseek-v4-flash"),
        temperature=_f("temperature", 0.7),
        max_tokens=_i("max_tokens", 8192),
        top_p=_f("top_p", 0.95),
        top_k=top_k,
        frequency_penalty=_f("frequency_penalty", 0.0),
        presence_penalty=_f("presence_penalty", 0.0),
        enable_online_search=bool(cfg.get("enable_online_search", False)),
        enable_reasoning=bool(cfg.get("enable_reasoning", False)),
        reasoning_effort=cfg.get("reasoning_effort"),
        base_url=cfg.get("base_url"),
        api_key_configured=key_ok,
        api_keys_present=present,
    )


@router.get(
    "/system-prompt",
    summary="获取 Agent 系统提示词（后端管理，不暴露给前端 UI）",
    description="供运维/调试使用；对话时由 Agent 自动加载，用户无需配置。",
)
async def get_system_prompt() -> Dict[str, Any]:
    text = _read_agent_system_prompt_text()
    path = _agent_system_prompt_path()
    return {
        "path": str(path),
        "length": len(text),
        "content": text,
    }


@router.get(
    "/config/default",
    response_model=Dict[str, Any],
    summary="获取默认配置",
    description="获取推荐的默认LLM配置"
)
async def get_default_config() -> Dict[str, Any]:
    cfg = dict(DEFAULT_LLM_CONFIG)
    cfg["system_prompt"] = _read_agent_system_prompt_text()
    return cfg
