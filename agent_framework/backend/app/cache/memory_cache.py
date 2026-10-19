"""
内存缓存实现

提供基于 OrderedDict 的 LRU 内存缓存
"""

import asyncio
import logging
from typing import Dict, Any, Optional, OrderedDict
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


@dataclass
class MemoryCacheEntry:
    """内存缓存条目"""
    key: str
    value: Any
    expires_at: datetime
    created_at: datetime
    access_count: int = 0
    
    def is_expired(self) -> bool:
        """检查是否过期"""
        return datetime.utcnow() > self.expires_at


class MemoryCache:
    """
    内存 LRU 缓存
    
    特性：
    - 固定容量，LRU 淘汰
    - TTL 支持
    - 线程安全
    - 统计信息
    """
    
    def __init__(self, max_size: int = 1000, default_ttl: int = 300):
        self.max_size = max_size
        self.default_ttl = default_ttl
        self._cache: OrderedDict[str, MemoryCacheEntry] = OrderedDict()
        self._lock = asyncio.Lock()
        
        # 统计
        self._hits = 0
        self._misses = 0
        self._sets = 0
        self._evictions = 0
    
    async def get(self, key: str) -> Optional[Any]:
        """获取缓存值"""
        async with self._lock:
            if key not in self._cache:
                self._misses += 1
                return None
            
            entry = self._cache[key]
            
            if entry.is_expired():
                del self._cache[key]
                self._misses += 1
                return None
            
            # LRU: 移动到末尾
            self._cache.move_to_end(key)
            entry.access_count += 1
            
            self._hits += 1
            return entry.value
    
    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """设置缓存值"""
        async with self._lock:
            # LRU 淘汰
            while len(self._cache) >= self.max_size:
                oldest_key, _ = self._cache.popitem(last=False)
                self._evictions += 1
                logger.debug(f"LRU淘汰: {oldest_key}")
            
            expires_at = datetime.utcnow() + timedelta(seconds=ttl or self.default_ttl)
            
            entry = MemoryCacheEntry(
                key=key,
                value=value,
                expires_at=expires_at,
                created_at=datetime.utcnow()
            )
            
            self._cache[key] = entry
            self._sets += 1
            return True
    
    async def delete(self, key: str) -> bool:
        """删除缓存值"""
        async with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False
    
    async def clear(self):
        """清空缓存"""
        async with self._lock:
            self._cache.clear()
    
    async def cleanup_expired(self) -> int:
        """清理过期条目，返回清理数量"""
        expired_keys = []
        
        async with self._lock:
            for key, entry in self._cache.items():
                if entry.is_expired():
                    expired_keys.append(key)
            
            for key in expired_keys:
                del self._cache[key]
        
        return len(expired_keys)
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        total = self._hits + self._misses
        hit_rate = self._hits / total if total > 0 else 0.0
        
        return {
            "size": len(self._cache),
            "max_size": self.max_size,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": f"{hit_rate:.2%}",
            "sets": self._sets,
            "evictions": self._evictions,
        }
