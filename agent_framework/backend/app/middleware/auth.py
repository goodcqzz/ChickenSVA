import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from app.config import settings

logger = logging.getLogger(__name__)


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not settings.auth_enabled:
            return await call_next(request)

        path = request.url.path

        if path in settings.auth_exempt_paths:
            return await call_next(request)

        if path.startswith("/ws/"):
            return await call_next(request)

        if not settings.auth_api_key:
            return await call_next(request)

        api_key = request.headers.get("X-API-Key") or request.query_params.get("api_key")

        if api_key != settings.auth_api_key:
            logger.warning(f"认证失败: {request.method} {path}")
            return JSONResponse(
                status_code=401,
                content={"detail": "无效或缺失的API Key"},
            )

        return await call_next(request)
