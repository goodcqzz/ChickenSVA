"""
LLM 响应缓存系统

提供高效的 LLM 响应缓存机制：
- 基于请求内容的智能哈希键生成
- 多级缓存架构（内存 + 持久化）
- 自动过期清理
- 缓存命中率统计
- 支持语义相似度匹配（可选）

使用示例:
    cache = ResponseCache()
    
    # 检查缓存
    cached_response = await cache.get(messages, model)
    if cached_response:
        return cached_response
    
    # 调用 LLM 并缓存结果
    response = await llm.chat(messages)
    await cache.set(messages, model, response)
"""

import json
import hashlib
import logging
import asyncio
from typing import Dict, Any, Optional, List, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import OrderedDict
import pickle
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class CacheConfig:
    """缓存配置"""
    # 内存缓存配置
    memory_max_size: int = 1000              # 内存缓存最大条目数
    memory_ttl: int = 300                    # 内存缓存TTL（秒）
    
    # 持久化缓存配置
    persistent_enabled: bool = True          # 是否启用持久化缓存
    persistent_path: str = "./data/cache.db" # 持久化缓存路径
    persistent_max_size: int = 10000         # 持久化缓存最大条目数
    persistent_ttl: int = 3600               # 持久化缓存TTL（秒）
    
    # 缓存键配置
    include_temperature: bool = False        # 是否将 temperature 纳入缓存键
    include_system_prompt: bool = True       # 是否将 system_prompt 纳入缓存键
    
    # 清理配置
    cleanup_interval: int = 600              # 清理间隔（秒）
    
    # 统计配置
    enable_stats: bool = True                # 是否启用统计


@dataclass
class CacheEntry:
    """缓存条目"""
    key: str
    response: str
    model: str
    created_at: datetime
    expires_at: datetime
    access_count: int = 0
    last_accessed: Optional[datetime] = None
    
    def is_expired(self) -> bool:
        """检查是否过期"""
        return datetime.utcnow() > self.expires_at
    
    def touch(self):
        """更新访问信息"""
        self.access_count += 1
        self.last_accessed = datetime.utcnow()


@dataclass
class CacheStats:
    """缓存统计信息"""
    hits: int = 0
    misses: int = 0
    sets: int = 0
    evictions: int = 0
    expirations: int = 0
    errors: int = 0
    
    # 内存缓存统计
    memory_size: int = 0
    memory_hits: int = 0
    memory_misses: int = 0
    
    # 持久化缓存统计
    persistent_size: int = 0
    persistent_hits: int = 0
    persistent_misses: int = 0
    
    @property
    def total_requests(self) -> int:
        """总请求数"""
        return self.hits + self.misses
    
    @property
    def hit_rate(self) -> float:
        """缓存命中率"""
        total = self.total_requests
        return self.hits / total if total > 0 else 0.0
    
    @property
    def memory_hit_rate(self) -> float:
        """内存缓存命中率"""
        total = self.memory_hits + self.memory_misses
        return self.memory_hits / total if total > 0 else 0.0
    
    @property
    def persistent_hit_rate(self) -> float:
        """持久化缓存命中率"""
        total = self.persistent_hits + self.persistent_misses
        return self.persistent_hits / total if total > 0 else 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": f"{self.hit_rate:.2%}",
            "sets": self.sets,
            "evictions": self.evictions,
            "expirations": self.expirations,
            "errors": self.errors,
            "memory": {
                "size": self.memory_size,
                "hits": self.memory_hits,
                "misses": self.memory_misses,
                "hit_rate": f"{self.memory_hit_rate:.2%}",
            },
            "persistent": {
                "size": self.persistent_size,
                "hits": self.persistent_hits,
                "misses": self.persistent_misses,
                "hit_rate": f"{self.persistent_hit_rate:.2%}",
            },
        }


class ResponseCache:
    """
    LLM 响应缓存管理器
    
    实现多级缓存架构：
    L1: 内存 LRU 缓存（最快）
    L2: SQLite 持久化缓存（中等）
    """
    
    def __init__(self, config: Optional[CacheConfig] = None):
        self.config = config or CacheConfig()
        self.stats = CacheStats()
        
        # L1: 内存缓存
        self._memory_cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._memory_lock = asyncio.Lock()
        
        # L2: 持久化缓存
        self._persistent_cache: Optional[sqlite3.Connection] = None
        self._persistent_lock = asyncio.Lock()
        
        # 后台清理任务
        self._cleanup_task: Optional[asyncio.Task] = None
        self._shutdown = False
        
        logger.info("ResponseCache 初始化完成")
    
    async def start(self):
        """启动缓存管理器"""
        # 初始化持久化缓存
        if self.config.persistent_enabled:
            await self._init_persistent_cache()
        
        # 启动后台清理任务
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info("ResponseCache 已启动")
    
    async def stop(self):
        """停止缓存管理器"""
        self._shutdown = True
        
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        
        # 关闭持久化缓存
        if self._persistent_cache:
            self._persistent_cache.close()
        
        logger.info("ResponseCache 已停止")
    
    async def get(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: Optional[float] = None,
        **kwargs
    ) -> Optional[str]:
        """
        获取缓存的响应
        
        Args:
            messages: 对话消息列表
            model: 模型名称
            temperature: 温度参数（可选）
            **kwargs: 其他参数
            
        Returns:
            缓存的响应内容，未命中返回 None
        """
        try:
            cache_key = self._generate_key(messages, model, temperature, **kwargs)
            
            # L1: 检查内存缓存
            async with self._memory_lock:
                if cache_key in self._memory_cache:
                    entry = self._memory_cache[cache_key]
                    if not entry.is_expired():
                        entry.touch()
                        # 移动到末尾（LRU）
                        self._memory_cache.move_to_end(cache_key)
                        
                        self.stats.hits += 1
                        self.stats.memory_hits += 1
                        logger.debug(f"内存缓存命中: {cache_key[:16]}...")
                        return entry.response
                    else:
                        # 过期，删除
                        del self._memory_cache[cache_key]
                        self.stats.expirations += 1
            
            # L2: 检查持久化缓存
            if self.config.persistent_enabled and self._persistent_cache:
                entry = await self._get_from_persistent(cache_key)
                if entry and not entry.is_expired():
                    # 提升到内存缓存
                    await self._set_to_memory(cache_key, entry)
                    
                    self.stats.hits += 1
                    self.stats.persistent_hits += 1
                    logger.debug(f"持久化缓存命中: {cache_key[:16]}...")
                    return entry.response
                elif entry:
                    # 过期，删除
                    await self._delete_from_persistent(cache_key)
                    self.stats.expirations += 1
            
            # 缓存未命中
            self.stats.misses += 1
            self.stats.memory_misses += 1
            if self.config.persistent_enabled:
                self.stats.persistent_misses += 1
            
            return None
            
        except Exception as e:
            logger.error(f"缓存获取失败: {e}")
            self.stats.errors += 1
            return None
    
    async def set(
        self,
        messages: List[Dict[str, str]],
        model: str,
        response: str,
        temperature: Optional[float] = None,
        ttl: Optional[int] = None,
        **kwargs
    ) -> bool:
        """
        设置缓存
        
        Args:
            messages: 对话消息列表
            model: 模型名称
            response: 响应内容
            temperature: 温度参数（可选）
            ttl: 自定义TTL（秒，可选）
            **kwargs: 其他参数
            
        Returns:
            是否设置成功
        """
        try:
            cache_key = self._generate_key(messages, model, temperature, **kwargs)
            
            now = datetime.utcnow()
            entry = CacheEntry(
                key=cache_key,
                response=response,
                model=model,
                created_at=now,
                expires_at=now + timedelta(seconds=ttl or self.config.memory_ttl),
                last_accessed=now
            )
            
            # L1: 写入内存缓存
            await self._set_to_memory(cache_key, entry)
            
            # L2: 写入持久化缓存
            if self.config.persistent_enabled:
                await self._set_to_persistent(entry)
            
            self.stats.sets += 1
            logger.debug(f"缓存已设置: {cache_key[:16]}...")
            return True
            
        except Exception as e:
            logger.error(f"缓存设置失败: {e}")
            self.stats.errors += 1
            return False
    
    async def delete(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: Optional[float] = None,
        **kwargs
    ) -> bool:
        """删除缓存条目"""
        try:
            cache_key = self._generate_key(messages, model, temperature, **kwargs)
            
            # 从内存缓存删除
            async with self._memory_lock:
                if cache_key in self._memory_cache:
                    del self._memory_cache[cache_key]
            
            # 从持久化缓存删除
            if self.config.persistent_enabled:
                await self._delete_from_persistent(cache_key)
            
            return True
        except Exception as e:
            logger.error(f"缓存删除失败: {e}")
            return False
    
    async def clear(self) -> bool:
        """清空所有缓存"""
        try:
            # 清空内存缓存
            async with self._memory_lock:
                self._memory_cache.clear()
            
            # 清空持久化缓存
            if self._persistent_cache:
                self._persistent_cache.execute("DELETE FROM cache_entries")
                self._persistent_cache.commit()
            
            logger.info("缓存已清空")
            return True
        except Exception as e:
            logger.error(f"缓存清空失败: {e}")
            return False
    
    def get_stats(self) -> Dict[str, Any]:
        """获取缓存统计信息"""
        # 更新当前大小
        self.stats.memory_size = len(self._memory_cache)
        if self.config.persistent_enabled and self._persistent_cache:
            cursor = self._persistent_cache.execute("SELECT COUNT(*) FROM cache_entries")
            self.stats.persistent_size = cursor.fetchone()[0]
        
        return self.stats.to_dict()
    
    def _generate_key(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: Optional[float] = None,
        **kwargs
    ) -> str:
        """
        生成缓存键
        
        基于消息内容、模型和关键参数生成唯一哈希
        """
        # 构建缓存键内容
        key_parts = {
            "model": model,
            "messages": messages,
        }
        
        if self.config.include_temperature and temperature is not None:
            key_parts["temperature"] = temperature
        
        if self.config.include_system_prompt:
            # 提取 system prompt
            for msg in messages:
                if msg.get("role") == "system":
                    key_parts["system"] = msg.get("content", "")
                    break
        
        # 序列化并哈希
        key_json = json.dumps(key_parts, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(key_json.encode()).hexdigest()
    
    async def _set_to_memory(self, key: str, entry: CacheEntry):
        """写入内存缓存（带LRU淘汰）"""
        async with self._memory_lock:
            # LRU 淘汰
            while len(self._memory_cache) >= self.config.memory_max_size:
                oldest_key, _ = self._memory_cache.popitem(last=False)
                self.stats.evictions += 1
                logger.debug(f"内存缓存LRU淘汰: {oldest_key[:16]}...")
            
            self._memory_cache[key] = entry
    
    async def _init_persistent_cache(self):
        """初始化持久化缓存（SQLite）"""
        try:
            # 确保目录存在
            Path(self.config.persistent_path).parent.mkdir(parents=True, exist_ok=True)
            
            # 连接数据库
            self._persistent_cache = sqlite3.connect(
                self.config.persistent_path,
                check_same_thread=False
            )
            
            # 创建表
            self._persistent_cache.execute("""
                CREATE TABLE IF NOT EXISTS cache_entries (
                    key TEXT PRIMARY KEY,
                    response TEXT NOT NULL,
                    model TEXT NOT NULL,
                    created_at TIMESTAMP NOT NULL,
                    expires_at TIMESTAMP NOT NULL,
                    access_count INTEGER DEFAULT 0,
                    last_accessed TIMESTAMP
                )
            """)
            
            # 创建索引
            self._persistent_cache.execute("""
                CREATE INDEX IF NOT EXISTS idx_expires ON cache_entries(expires_at)
            """)
            
            self._persistent_cache.commit()
            logger.info(f"持久化缓存已初始化: {self.config.persistent_path}")
            
        except Exception as e:
            logger.error(f"持久化缓存初始化失败: {e}")
            self._persistent_cache = None
    
    async def _get_from_persistent(self, key: str) -> Optional[CacheEntry]:
        """从持久化缓存获取"""
        if not self._persistent_cache:
            return None
        
        try:
            cursor = self._persistent_cache.execute(
                "SELECT * FROM cache_entries WHERE key = ?",
                (key,)
            )
            row = cursor.fetchone()
            
            if row:
                # 更新访问计数
                self._persistent_cache.execute(
                    """UPDATE cache_entries 
                       SET access_count = access_count + 1, 
                           last_accessed = ? 
                       WHERE key = ?""",
                    (datetime.utcnow(), key)
                )
                self._persistent_cache.commit()
                
                return CacheEntry(
                    key=row[0],
                    response=row[1],
                    model=row[2],
                    created_at=datetime.fromisoformat(row[3]),
                    expires_at=datetime.fromisoformat(row[4]),
                    access_count=row[5],
                    last_accessed=datetime.fromisoformat(row[6]) if row[6] else None
                )
            
            return None
            
        except Exception as e:
            logger.error(f"持久化缓存读取失败: {e}")
            return None
    
    async def _set_to_persistent(self, entry: CacheEntry):
        """写入持久化缓存"""
        if not self._persistent_cache:
            return
        
        try:
            # 检查并淘汰旧条目
            cursor = self._persistent_cache.execute(
                "SELECT COUNT(*) FROM cache_entries"
            )
            count = cursor.fetchone()[0]
            
            if count >= self.config.persistent_max_size:
                # 删除最旧的条目
                self._persistent_cache.execute("""
                    DELETE FROM cache_entries 
                    WHERE key IN (
                        SELECT key FROM cache_entries 
                        ORDER BY last_accessed ASC NULLS FIRST, created_at ASC 
                        LIMIT ?
                    )
                """, (count - self.config.persistent_max_size + 1,))
                self.stats.evictions += 1
            
            # 插入或更新
            self._persistent_cache.execute("""
                INSERT OR REPLACE INTO cache_entries 
                (key, response, model, created_at, expires_at, access_count, last_accessed)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                entry.key,
                entry.response,
                entry.model,
                entry.created_at.isoformat(),
                entry.expires_at.isoformat(),
                entry.access_count,
                entry.last_accessed.isoformat() if entry.last_accessed else None
            ))
            
            self._persistent_cache.commit()
            
        except Exception as e:
            logger.error(f"持久化缓存写入失败: {e}")
    
    async def _delete_from_persistent(self, key: str):
        """从持久化缓存删除"""
        if not self._persistent_cache:
            return
        
        try:
            self._persistent_cache.execute(
                "DELETE FROM cache_entries WHERE key = ?",
                (key,)
            )
            self._persistent_cache.commit()
        except Exception as e:
            logger.error(f"持久化缓存删除失败: {e}")
    
    async def _cleanup_loop(self):
        """后台清理循环"""
        while not self._shutdown:
            try:
                await asyncio.sleep(self.config.cleanup_interval)
                await self._cleanup_expired()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"缓存清理异常: {e}")
    
    async def _cleanup_expired(self):
        """清理过期条目"""
        now = datetime.utcnow()
        
        # 清理内存缓存
        expired_memory = []
        async with self._memory_lock:
            for key, entry in self._memory_cache.items():
                if entry.is_expired():
                    expired_memory.append(key)
            
            for key in expired_memory:
                del self._memory_cache[key]
        
        if expired_memory:
            self.stats.expirations += len(expired_memory)
            logger.debug(f"内存缓存清理: {len(expired_memory)} 个过期条目")
        
        # 清理持久化缓存
        if self._persistent_cache:
            try:
                cursor = self._persistent_cache.execute(
                    "DELETE FROM cache_entries WHERE expires_at < ?",
                    (now.isoformat(),)
                )
                self._persistent_cache.commit()
                
                if cursor.rowcount > 0:
                    self.stats.expirations += cursor.rowcount
                    logger.debug(f"持久化缓存清理: {cursor.rowcount} 个过期条目")
                    
            except Exception as e:
                logger.error(f"持久化缓存清理失败: {e}")


# 全局缓存实例
_response_cache: Optional[ResponseCache] = None


def init_response_cache(config: Optional[CacheConfig] = None) -> ResponseCache:
    """初始化全局响应缓存"""
    global _response_cache
    _response_cache = ResponseCache(config)
    return _response_cache


def get_response_cache() -> Optional[ResponseCache]:
    """获取全局响应缓存"""
    return _response_cache
