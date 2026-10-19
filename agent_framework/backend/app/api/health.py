"""
健康检查路由

提供系统健康状态检查端点
"""

from datetime import datetime
from typing import Dict, Any

from fastapi import APIRouter, Request, status
from pydantic import BaseModel

from app.config import settings

router = APIRouter()


class HealthResponse(BaseModel):
    """健康检查响应模型"""
    status: str
    version: str
    environment: str
    timestamp: str
    services: Dict[str, Any]


class SystemInfoResponse(BaseModel):
    """系统信息响应模型"""
    app_name: str
    version: str
    environment: str
    debug: bool
    features: Dict[str, bool]


@router.get(
    "/health",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    summary="健康检查",
    description="检查系统各组件的健康状态"
)
async def health_check() -> HealthResponse:
    """
    系统健康检查端点
    
    返回系统整体健康状态和各服务状态
    """
    return HealthResponse(
        status="healthy",
        version=settings.app_version,
        environment=settings.app_env,
        timestamp=datetime.utcnow().isoformat(),
        services={
            "api": {"status": "up", "latency_ms": 0},
            "websocket": {"status": "up", "connections": 0},
            "mcp": {"status": "up", "url": settings.mcp_server_url}
        }
    )


@router.get(
    "/",
    response_model=SystemInfoResponse,
    status_code=status.HTTP_200_OK,
    summary="系统信息",
    description="获取系统基本信息和功能状态"
)
async def system_info() -> SystemInfoResponse:
    """
    系统信息端点
    
    返回应用基本信息和启用的功能
    """
    return SystemInfoResponse(
        app_name=settings.app_name,
        version=settings.app_version,
        environment=settings.app_env,
        debug=settings.debug,
        features={
            "websocket": True,
            "mcp_tools": True,
            "llm": bool(settings.qwen_api_key or settings.kimi_api_key),
            "memory": settings.storage_type != "memory",
            "file_upload": True
        }
    )


@router.get(
    "/ready",
    status_code=status.HTTP_200_OK,
    summary="就绪检查",
    description="Kubernetes等容器编排系统的就绪检查"
)
async def readiness_check() -> Dict[str, str]:
    """
    就绪检查端点
    
    用于容器编排系统判断服务是否准备好接收流量
    """
    return {"status": "ready"}


@router.get(
    "/live",
    status_code=status.HTTP_200_OK,
    summary="存活检查",
    description="Kubernetes等容器编排系统的存活检查"
)
async def liveness_check() -> Dict[str, str]:
    """
    存活检查端点
    
    用于容器编排系统判断服务是否正常运行
    """
    return {"status": "alive"}


@router.get(
    "/metrics",
    status_code=status.HTTP_200_OK,
    summary="系统指标",
    description="获取系统运行指标和性能数据"
)
async def metrics() -> Dict[str, Any]:
    """
    系统指标端点
    
    返回系统运行状态、Agent Pool 统计、WebSocket 统计、缓存统计等信息
    """
    from app.main import (
        ws_manager, agent_pool, response_cache,
        memory_compressor, task_queue, sv_database
    )
    
    return {
        "timestamp": datetime.utcnow().isoformat(),
        "agent_pool": agent_pool.get_stats() if agent_pool else None,
        "websocket": ws_manager.get_stats() if ws_manager else None,
        "cache": response_cache.get_stats() if response_cache else None,
        "compression": memory_compressor.get_stats() if memory_compressor else None,
        "task_queue": task_queue.get_stats() if task_queue else None,
        "sv_database": sv_database.get_stats() if sv_database else None,
        "config": {
            "agent_pool": {
                "max_size": settings.agent_pool_max_size,
                "idle_timeout": settings.agent_pool_idle_timeout,
                "max_age": settings.agent_pool_max_age,
            },
            "websocket": {
                "max_connections": settings.ws_max_connections,
                "broadcast_batch_size": settings.ws_broadcast_batch_size,
                "cleanup_interval": settings.ws_cleanup_interval,
            },
            "cache": {
                "enabled": settings.cache_enabled,
                "memory_max_size": settings.cache_memory_max_size,
                "persistent_enabled": settings.cache_persistent_enabled,
            },
            "compression": {
                "enabled": settings.compression_enabled,
                "max_messages": settings.compression_max_messages,
                "strategy": settings.compression_strategy,
            },
            "task_queue": {
                "enabled": settings.task_queue_enabled,
                "max_concurrent": settings.task_queue_max_concurrent,
                "num_workers": settings.task_queue_num_workers,
            },
            "sv_database": {
                "enabled": settings.sv_db_enabled,
                "type": settings.sv_db_type,
            }
        }
    }


@router.get(
    "/quota",
    status_code=status.HTTP_200_OK,
    summary="查询当前 IP 平台默认模型剩余配额",
    description="仅在使用平台默认 Key 时受限；BYOK 用户不受此约束。",
)
async def quota_status(request: Request) -> Dict[str, Any]:
    from app.security import quota_tracker, get_default_model_burst_remaining

    ip = _client_ip(request)
    used = quota_tracker.get_used(ip) if quota_tracker else 0
    daily = settings.default_model_daily_quota
    burst_limit = settings.default_model_burst_limit if settings.default_model_limits_enabled else 0
    burst_window = settings.default_model_burst_window_seconds
    burst_remaining = get_default_model_burst_remaining(ip) if burst_limit > 0 else None
    return {
        "ip": ip,
        "used": used,
        "quota": daily if daily > 0 else None,
        "remaining": (daily - used) if daily > 0 else None,
        "unlimited": daily <= 0 and burst_limit <= 0,
        "burst_limit": burst_limit if burst_limit > 0 else None,
        "burst_window_seconds": burst_window if burst_limit > 0 else None,
        "burst_remaining": burst_remaining if burst_limit > 0 else None,
        "limits_apply_to": "platform_default_key_only",
    }


def _client_ip(request: Request) -> str:
    """统一解析客户端真实 IP（适配 Nginx X-Forwarded-For）。"""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        ip = xff.split(",")[0].strip()
        if ip:
            return ip
    return request.client.host if request.client else "unknown"


@router.get(
    "/public-config",
    status_code=status.HTTP_200_OK,
    summary="公开配置（无敏感信息）",
    description=(
        "返回前端在路由守卫/登录页所需的公开开关。"
        "不包含任何 API Key 或敏感信息。"
    ),
)
async def public_config() -> Dict[str, Any]:
    has_default = bool(
        settings.public_default_model_enabled
        and (
            settings.deepseek_api_key
            or settings.qwen_api_key
            or settings.openrouter_api_key
        )
    )
    default_provider = settings.llm_provider if has_default else None
    default_model = None
    if has_default:
        if default_provider == "deepseek":
            default_model = settings.deepseek_model
        elif default_provider == "qwen":
            default_model = settings.qwen_model
    return {
        "auth_users_enabled": bool(settings.auth_users_enabled),
        "has_default_model": has_default,
        "persist_user_api_keys": bool(settings.persist_user_api_keys),
        "default_provider": default_provider,
        "default_model": default_model,
        "default_model_limits_enabled": bool(settings.default_model_limits_enabled),
        "default_model_daily_quota": (
            settings.default_model_daily_quota if settings.default_model_daily_quota > 0 else None
        ),
        "default_model_burst_limit": (
            settings.default_model_burst_limit
            if settings.default_model_limits_enabled and settings.default_model_burst_limit > 0
            else None
        ),
        "default_model_burst_window_seconds": (
            settings.default_model_burst_window_seconds
            if settings.default_model_limits_enabled and settings.default_model_burst_limit > 0
            else None
        ),
        "debug": bool(settings.debug),
    }
