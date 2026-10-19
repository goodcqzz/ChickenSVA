"""
Agent 实例池管理器

提供 AgentCore 实例的生命周期管理：
- LRU 缓存策略
- 自动清理空闲实例
- 内存使用限制
- 并发安全
"""

import asyncio
import logging
from collections import OrderedDict
from datetime import datetime, timedelta
from typing import Dict, Optional
from contextlib import asynccontextmanager

from app.agent.core import AgentCore
from app.agent.tool_registry import ToolRegistry
from app.agent.memory import ConversationMemory
from app.llm.base import LLMConfig
from app.llm.factory import LLMFactory
from app.config import settings

logger = logging.getLogger(__name__)


class PooledAgent:
    """包装器：为 AgentCore 添加元数据"""
    
    def __init__(self, agent: AgentCore, session_id: str):
        self.agent = agent
        self.session_id = session_id
        self.created_at = datetime.utcnow()
        self.last_activity = datetime.utcnow()
        self.request_count = 0
        self.is_active = True
    
    def touch(self):
        """更新最后活动时间"""
        self.last_activity = datetime.utcnow()
        self.request_count += 1
    
    @property
    def idle_seconds(self) -> float:
        """空闲时间（秒）"""
        return (datetime.utcnow() - self.last_activity).total_seconds()
    
    @property
    def age_seconds(self) -> float:
        """存活时间（秒）"""
        return (datetime.utcnow() - self.created_at).total_seconds()


class AgentPool:
    """
    Agent 实例池
    
    特性：
    1. LRU 淘汰策略
    2. 最大实例数限制
    3. 空闲超时清理
    4. 最大存活时间
    5. 并发安全
    """
    
    def __init__(
        self,
        tool_registry: ToolRegistry,
        max_size: int = 100,
        idle_timeout: int = 1800,  # 30分钟
        max_age: int = 7200,       # 2小时
        cleanup_interval: int = 300  # 5分钟
    ):
        self._tool_registry = tool_registry
        self._max_size = max_size
        self._idle_timeout = idle_timeout
        self._max_age = max_age
        self._cleanup_interval = cleanup_interval
        
        # 实例存储: OrderedDict 保持 LRU 顺序
        self._pool: OrderedDict[str, PooledAgent] = OrderedDict()
        self._lock = asyncio.Lock()
        self._cleanup_task: Optional[asyncio.Task] = None
        self._shutdown = False
        
        # 统计信息
        self._stats = {
            "created": 0,
            "reused": 0,
            "evicted": 0,
            "expired": 0,
            "errors": 0
        }
        
        logger.info(
            f"AgentPool 初始化完成: max_size={max_size}, "
            f"idle_timeout={idle_timeout}s, max_age={max_age}s"
        )
    
    async def start(self):
        """启动后台清理任务"""
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())
            logger.info("AgentPool 后台清理任务已启动")
    
    async def stop(self):
        """停止池并清理所有实例"""
        self._shutdown = True
        
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        
        async with self._lock:
            for pooled in self._pool.values():
                try:
                    await pooled.agent.close()
                except Exception as e:
                    logger.error(f"关闭 Agent 失败 [{pooled.session_id}]: {e}")
            
            self._pool.clear()
        
        logger.info("AgentPool 已停止，所有实例已清理")
    
    async def get_or_create(
        self,
        session_id: str,
        llm_config: Optional[LLMConfig] = None
    ) -> AgentCore:
        """
        获取或创建 Agent 实例
        
        Args:
            session_id: 会话ID
            llm_config: LLM 配置（创建新实例时使用）
        
        Returns:
            AgentCore 实例
        """
        async with self._lock:
            # 检查现有实例
            if session_id in self._pool:
                pooled = self._pool.pop(session_id)  # 移动到末尾（最近使用）
                
                # 检查是否过期
                if pooled.idle_seconds > self._idle_timeout:
                    logger.info(f"Agent 空闲超时 [{session_id}]: {pooled.idle_seconds:.0f}s")
                    await self._close_agent(pooled)
                    self._stats["expired"] += 1
                elif pooled.age_seconds > self._max_age:
                    logger.info(f"Agent 存活超时 [{session_id}]: {pooled.age_seconds:.0f}s")
                    await self._close_agent(pooled)
                    self._stats["expired"] += 1
                else:
                    if llm_config is not None:
                        try:
                            if hasattr(pooled.agent.llm, "close"):
                                await pooled.agent.llm.close()
                            pooled.agent.llm_config = llm_config
                            pooled.agent.llm = LLMFactory.create(llm_config)
                            logger.info(f"Agent LLM配置已更新 [{session_id}]")
                        except Exception as e:
                            logger.error(f"更新Agent LLM配置失败 [{session_id}]: {e}")
                    pooled.touch()
                    self._pool[session_id] = pooled
                    self._stats["reused"] += 1
                    logger.debug(f"Agent 复用 [{session_id}]: 已处理 {pooled.request_count} 请求")
                    return pooled.agent
            
            # LRU 淘汰
            while len(self._pool) >= self._max_size:
                oldest_id, oldest = self._pool.popitem(last=False)
                logger.info(f"LRU 淘汰 Agent [{oldest_id}]")
                await self._close_agent(oldest)
                self._stats["evicted"] += 1
            
            # 创建新实例
            try:
                agent = AgentCore(
                    tool_registry=self._tool_registry,
                    llm_config=llm_config,
                    max_execution_time=settings.agent_max_execution_time,
                )
                pooled = PooledAgent(agent, session_id)
                self._pool[session_id] = pooled
                self._stats["created"] += 1
                logger.info(f"创建新 Agent [{session_id}]: 当前池大小 {len(self._pool)}/{self._max_size}")
                return agent
            except Exception as e:
                self._stats["errors"] += 1
                logger.error(f"创建 Agent 失败 [{session_id}]: {e}")
                raise
    
    async def release(self, session_id: str):
        """
        释放 Agent 实例（标记为非活跃，但不立即关闭）
        
        Args:
            session_id: 会话ID
        """
        async with self._lock:
            if session_id in self._pool:
                self._pool[session_id].is_active = False
                logger.debug(f"Agent 标记为非活跃 [{session_id}]")
    
    async def remove(self, session_id: str):
        """
        立即移除 Agent 实例
        
        Args:
            session_id: 会话ID
        """
        async with self._lock:
            if session_id in self._pool:
                pooled = self._pool.pop(session_id)
                await self._close_agent(pooled)
                logger.info(f"Agent 已移除 [{session_id}]")
    
    @asynccontextmanager
    async def acquire(self, session_id: str, llm_config: Optional[LLMConfig] = None):
        """
        上下文管理器：自动获取和释放
        
        用法:
            async with pool.acquire(session_id) as agent:
                await agent.execute(...)
        """
        agent = await self.get_or_create(session_id, llm_config)
        try:
            yield agent
        finally:
            # 可选：立即释放或保持缓存
            pass
    
    def get_stats(self) -> Dict:
        """获取池统计信息"""
        return {
            **self._stats,
            "current_size": len(self._pool),
            "max_size": self._max_size,
            "active_sessions": [
                {
                    "session_id": sid,
                    "idle_seconds": p.idle_seconds,
                    "request_count": p.request_count,
                    "is_active": p.is_active
                }
                for sid, p in self._pool.items()
            ]
        }
    
    async def _close_agent(self, pooled: PooledAgent):
        """安全关闭 Agent"""
        try:
            await pooled.agent.close()
        except Exception as e:
            logger.error(f"关闭 Agent 异常 [{pooled.session_id}]: {e}")
    
    async def _cleanup_loop(self):
        """后台清理循环"""
        while not self._shutdown:
            try:
                await asyncio.sleep(self._cleanup_interval)
                await self._cleanup_idle()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"清理循环异常: {e}")
    
    async def _cleanup_idle(self):
        """清理空闲和过期实例"""
        to_remove = []
        
        async with self._lock:
            for session_id, pooled in self._pool.items():
                if not pooled.is_active:
                    to_remove.append(session_id)
                elif pooled.idle_seconds > self._idle_timeout:
                    to_remove.append(session_id)
                elif pooled.age_seconds > self._max_age:
                    to_remove.append(session_id)
        
        for session_id in to_remove:
            await self.remove(session_id)
            self._stats["expired"] += 1
        
        if to_remove:
            logger.info(f"后台清理完成: 移除 {len(to_remove)} 个实例，当前池大小 {len(self._pool)}")


# 全局实例池（将在 main.py 中初始化）
_agent_pool: Optional[AgentPool] = None


def init_agent_pool(tool_registry: ToolRegistry, **kwargs) -> AgentPool:
    """初始化全局 Agent Pool"""
    global _agent_pool
    _agent_pool = AgentPool(tool_registry, **kwargs)
    return _agent_pool


def get_agent_pool() -> Optional[AgentPool]:
    """获取全局 Agent Pool"""
    return _agent_pool
