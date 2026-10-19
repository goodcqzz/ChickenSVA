"""
按 IP 限速（基于 slowapi）。

仅在 settings.rate_limit_enabled=True 时实际生效；否则限速器返回的限制设为 "0/minute"
等价于「无限制装饰但永不命中」（slowapi 限速通过 default_limits=[] 实现关闭）。

WebSocket 入口（FastAPI 原生 WebSocket）无法直接被 slowapi 装饰，
我们在 main.py 的连接握手阶段手动调用 try_acquire_chat。
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from threading import Lock
from typing import Deque, Dict, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.config import settings

logger = logging.getLogger(__name__)


def extract_client_ip(
    xff: Optional[str],
    x_real_ip: Optional[str] = None,
    peer: Optional[str] = None,
) -> str:
    """从代理头中解析「真实客户端 IP」，抵抗 X-Forwarded-For 伪造。

    X-Forwarded-For 是「最早 → 最近」的链路：每经过一个代理，该代理会在右侧
    追加它看到的上游地址。本机直连的反代（Nginx / serve-proxy）一定会把它看到的
    地址追加到最右端，因此最右端永远是「可信的、本机反代写入的」。

    settings.trusted_proxy_hops 表示「本机反代之外、还需要再跳过几个可信反代」
    （例如高校外网反代 = 1）。我们从右往左跳过 hops 个可信代理后，剩下的最右元素
    即为真实客户端 IP；客户端自己伪造的 XFF 只会停留在更左侧，不会被取用。
    """
    hops = max(0, int(getattr(settings, "trusted_proxy_hops", 1)))
    if xff:
        parts = [p.strip() for p in xff.split(",") if p.strip()]
        if parts:
            idx = len(parts) - 1 - hops
            if idx < 0:
                idx = 0
            return parts[idx]
    if x_real_ip and x_real_ip.strip():
        return x_real_ip.strip()
    return (peer or "unknown").strip() or "unknown"


def client_ip_from_request(request: Request) -> str:
    """FastAPI Request → 客户端 IP（用于 HTTP 路由限速 / 配额）。"""
    peer = request.client.host if request.client else None
    return extract_client_ip(
        request.headers.get("x-forwarded-for"),
        request.headers.get("x-real-ip"),
        peer,
    )


def _get_client_ip(request: Request) -> str:
    """slowapi key_func：解析真实客户端 IP（可信代理感知）。"""
    ip = client_ip_from_request(request)
    if ip and ip != "unknown":
        return ip
    return get_remote_address(request)


# 全局 Limiter（HTTP 路由用）。若 rate_limit_enabled=False，default_limits 为空，
# 装饰器仍然存在但不会触发限制。
limiter = Limiter(
    key_func=_get_client_ip,
    default_limits=[],
    storage_uri=settings.rate_limit_storage_uri,
    headers_enabled=True,
)


def init_rate_limiter() -> Limiter:
    """根据当前 settings 重建 limiter（用于 reload 场景）。"""
    return limiter


async def _rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={
            "detail": "请求过于频繁，请稍后再试",
            "code": "RATE_LIMITED",
            "limit": str(exc.detail),
        },
    )


def install_rate_limiter(app: FastAPI) -> None:
    """把 limiter 挂到 FastAPI app 上。即便禁用也安全。"""
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)


# ---------------------------------------------------------------------------
# WebSocket 专用：滑动窗口限速器（不依赖 slowapi）
# 用于在 ws 握手 / chat 消息时手动检查
# ---------------------------------------------------------------------------

class _SlidingWindowLimiter:
    """每 IP 滑动窗口限速。线程安全。"""

    def __init__(self, max_count: int, window_seconds: float = 60.0) -> None:
        self.max = max_count
        self.window = window_seconds
        self._buckets: Dict[str, Deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def _prune(self, bucket: Deque[float], now: float) -> None:
        cutoff = now - self.window
        while bucket and bucket[0] < cutoff:
            bucket.popleft()

    def try_acquire(self, key: str) -> bool:
        if self.max <= 0:
            return True
        now = time.time()
        with self._lock:
            bucket = self._buckets[key]
            self._prune(bucket, now)
            if len(bucket) >= self.max:
                return False
            bucket.append(now)
            return True

    def get_used(self, key: str) -> int:
        if self.max <= 0 or not key:
            return 0
        now = time.time()
        with self._lock:
            bucket = self._buckets[key]
            self._prune(bucket, now)
            return len(bucket)

    def get_remaining(self, key: str) -> int:
        if self.max <= 0:
            return 10**9
        return max(0, self.max - self.get_used(key))


_chat_limiter: Optional[_SlidingWindowLimiter] = None
_default_model_burst_limiter: Optional[_SlidingWindowLimiter] = None


def get_chat_limiter() -> _SlidingWindowLimiter:
    global _chat_limiter
    if _chat_limiter is None:
        _chat_limiter = _SlidingWindowLimiter(settings.rate_limit_chat_per_minute, 60.0)
    return _chat_limiter


def get_default_model_burst_limiter() -> _SlidingWindowLimiter:
    """平台默认 Key 短时 burst 限速（默认 5 分钟 20 次）。"""
    global _default_model_burst_limiter
    if _default_model_burst_limiter is None:
        _default_model_burst_limiter = _SlidingWindowLimiter(
            settings.default_model_burst_limit,
            float(settings.default_model_burst_window_seconds),
        )
    return _default_model_burst_limiter


def try_acquire_chat(client_ip: str) -> bool:
    """通用 HTTP/聊天 IP 限速（RATE_LIMIT_ENABLED）。与平台配额独立。"""
    if not settings.rate_limit_enabled:
        return True
    return get_chat_limiter().try_acquire(client_ip)


def try_acquire_default_model_burst(client_ip: str) -> bool:
    """仅平台默认 Key 使用的 burst 限速；BYOK 不应调用此函数。"""
    if not settings.default_model_limits_enabled:
        return True
    if settings.default_model_burst_limit <= 0:
        return True
    return get_default_model_burst_limiter().try_acquire(client_ip)


def get_default_model_burst_remaining(client_ip: str) -> int:
    if not settings.default_model_limits_enabled or settings.default_model_burst_limit <= 0:
        return 10**9
    return get_default_model_burst_limiter().get_remaining(client_ip)


def check_chat_allowance(client_ip: str, using_own_key: bool) -> Optional[Dict[str, str]]:
    """统一的聊天防滥用检查（WebSocket 与 HTTP 共用）。

    返回 None 表示放行；否则返回 {"code", "message"} 错误信息。
    顺序：① 通用 IP 限速（RATE_LIMIT_ENABLED）；
         ② 仅平台默认 Key：burst 限速 + 每日配额（BYOK 不受限）。
    """
    if not try_acquire_chat(client_ip):
        return {
            "code": "RATE_LIMITED",
            "message": "请求过于频繁，请稍后再试（按 IP 限速）。",
        }

    if using_own_key:
        return None
    if not (settings.public_default_model_enabled and settings.default_model_limits_enabled):
        return None

    if settings.default_model_burst_limit > 0 and not try_acquire_default_model_burst(client_ip):
        window_min = max(1, settings.default_model_burst_window_seconds // 60)
        return {
            "code": "BURST_LIMITED",
            "message": (
                f"平台免费模型在 {window_min} 分钟内最多 {settings.default_model_burst_limit} 次提问，"
                "请稍后再试，或使用「我自己的 API Key (BYOK)」无限制使用。"
            ),
        }

    if settings.default_model_daily_quota > 0:
        from app.security import quota_tracker as _qt
        if _qt is not None and not _qt.try_consume(client_ip, 1):
            return {
                "code": "QUOTA_EXCEEDED",
                "message": (
                    f"今日平台免费模型已达上限（{settings.default_model_daily_quota} 次/天）。\n"
                    "可使用「我自己的 API Key (BYOK)」继续，或明日 UTC 0 点重置。"
                ),
            }

    return None
