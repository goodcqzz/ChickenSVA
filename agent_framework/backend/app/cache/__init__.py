"""
缓存模块

提供多级缓存支持：
- L1: 内存缓存 (LRU)
- L2: 本地缓存 (SQLite/Redis)
- L3: 分布式缓存 (Redis Cluster)
"""

from app.cache.response_cache import (
    ResponseCache, CacheConfig, CacheEntry, CacheStats,
    init_response_cache, get_response_cache
)
from app.cache.memory_cache import MemoryCache
from app.cache.redis_cache import RedisCache

__all__ = [
    "ResponseCache",
    "CacheConfig",
    "CacheEntry",
    "CacheStats",
    "MemoryCache",
    "RedisCache",
    "init_response_cache",
    "get_response_cache",
]
