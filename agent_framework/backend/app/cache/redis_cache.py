"""
Redis 缓存实现

提供基于 Redis 的分布式缓存支持
"""

import json
import logging
import pickle
from typing import Any, Optional, Dict
from datetime import datetime

try:
    import redis.asyncio as redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    redis = None

logger = logging.getLogger(__name__)


class RedisCache:
    """
    Redis 分布式缓存
    
    特性：
    - 分布式缓存支持
    - 自动序列化/反序列化
    - TTL 支持
    - 连接池管理
    """
    
    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        default_ttl: int = 3600,
        key_prefix: str = "agent:cache:"
    ):
        if not REDIS_AVAILABLE:
            raise ImportError("Redis 支持需要安装 redis 包: pip install redis")
        
        self.redis_url = redis_url
        self.default_ttl = default_ttl
        self.key_prefix = key_prefix
        self._client: Optional[redis.Redis] = None
        
        # 统计
        self._hits = 0
        self._misses = 0
        self._sets = 0
    
    async def connect(self):
        """连接 Redis"""
        try:
            self._client = redis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=False  # 我们需要二进制数据
            )
            # 测试连接
            await self._client.ping()
            logger.info(f"Redis 连接成功: {self.redis_url}")
        except Exception as e:
            logger.error(f"Redis 连接失败: {e}")
            raise
    
    async def disconnect(self):
        """断开 Redis 连接"""
        if self._client:
            await self._client.close()
            self._client = None
            logger.info("Redis 连接已关闭")
    
    def _make_key(self, key: str) -> str:
        """生成带前缀的键"""
        return f"{self.key_prefix}{key}"
    
    async def get(self, key: str) -> Optional[Any]:
        """获取缓存值"""
        if not self._client:
            return None
        
        try:
            full_key = self._make_key(key)
            data = await self._client.get(full_key)
            
            if data is None:
                self._misses += 1
                return None
            
            value = pickle.loads(data)
            self._hits += 1
            return value
            
        except Exception as e:
            logger.error(f"Redis get 失败: {e}")
            self._misses += 1
            return None
    
    async def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[int] = None
    ) -> bool:
        """设置缓存值"""
        if not self._client:
            return False
        
        try:
            full_key = self._make_key(key)
            data = pickle.dumps(value)
            
            await self._client.setex(
                full_key,
                ttl or self.default_ttl,
                data
            )
            
            self._sets += 1
            return True
            
        except Exception as e:
            logger.error(f"Redis set 失败: {e}")
            return False
    
    async def delete(self, key: str) -> bool:
        """删除缓存值"""
        if not self._client:
            return False
        
        try:
            full_key = self._make_key(key)
            result = await self._client.delete(full_key)
            return result > 0
        except Exception as e:
            logger.error(f"Redis delete 失败: {e}")
            return False
    
    async def clear(self) -> bool:
        """清空缓存（仅清除带前缀的键）"""
        if not self._client:
            return False
        
        try:
            pattern = f"{self.key_prefix}*"
            cursor = 0
            
            while True:
                cursor, keys = await self._client.scan(
                    cursor,
                    match=pattern,
                    count=100
                )
                
                if keys:
                    await self._client.delete(*keys)
                
                if cursor == 0:
                    break
            
            logger.info("Redis 缓存已清空")
            return True
            
        except Exception as e:
            logger.error(f"Redis clear 失败: {e}")
            return False
    
    async def exists(self, key: str) -> bool:
        """检查键是否存在"""
        if not self._client:
            return False
        
        try:
            full_key = self._make_key(key)
            return await self._client.exists(full_key) > 0
        except Exception as e:
            logger.error(f"Redis exists 失败: {e}")
            return False
    
    async def ttl(self, key: str) -> int:
        """获取键的剩余TTL"""
        if not self._client:
            return -2
        
        try:
            full_key = self._make_key(key)
            return await self._client.ttl(full_key)
        except Exception as e:
            logger.error(f"Redis ttl 失败: {e}")
            return -2
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        total = self._hits + self._misses
        hit_rate = self._hits / total if total > 0 else 0.0
        
        return {
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": f"{hit_rate:.2%}",
            "sets": self._sets,
        }
