"""
数据库连接管理

提供异步数据库连接和初始化，支持连接池优化
"""

import logging
import os
from typing import AsyncGenerator, Optional
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool

from app.config import settings
from app.storage.models import Base

logger = logging.getLogger(__name__)

# 数据库配置
DATABASE_URL = settings.database_url or f"sqlite+aiosqlite:///./data/agent.db"

# 引擎实例（延迟初始化）
_engine = None
_async_session = None


def get_engine():
    """获取或创建数据库引擎（单例模式）"""
    global _engine
    if _engine is None:
        engine_kwargs = {
            "echo": settings.debug,
            "pool_pre_ping": True,  # 连接前检测，避免使用失效连接
        }
        
        # SQLite 特殊配置
        if "sqlite" in DATABASE_URL:
            # SQLite 异步模式优化
            engine_kwargs.update({
                "connect_args": {
                    "check_same_thread": False,
                }
            })
            # 生产环境使用连接池，开发环境使用 NullPool 避免并发问题
            if not settings.is_production:
                engine_kwargs["poolclass"] = NullPool
        else:
            # PostgreSQL/MySQL 连接池配置
            engine_kwargs.update({
                "pool_size": settings.db_pool_size,
                "max_overflow": settings.db_max_overflow,
                "pool_timeout": settings.db_pool_timeout,
                "pool_recycle": settings.db_pool_recycle,
            })
        
        _engine = create_async_engine(DATABASE_URL, **engine_kwargs)
        logger.info(f"数据库引擎已创建: {DATABASE_URL}")
    
    return _engine


def get_session_maker():
    """获取或创建会话工厂"""
    global _async_session
    if _async_session is None:
        _async_session = async_sessionmaker(
            get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
            autocommit=False,
            autoflush=False,
        )
    return _async_session


async def init_db() -> None:
    """初始化数据库，创建所有表"""
    # 确保数据目录存在
    if "sqlite" in DATABASE_URL:
        db_path = DATABASE_URL.replace("sqlite+aiosqlite:///", "")
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    logger.info("数据库初始化完成")


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    获取数据库会话
    
    用于 FastAPI 依赖注入
    """
    session_maker = get_session_maker()
    async with session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


@asynccontextmanager
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    上下文管理器方式获取数据库会话
    
    用法:
        async with get_db_session() as session:
            result = await session.execute(...)
    """
    session_maker = get_session_maker()
    async with session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def close_db() -> None:
    """关闭数据库连接"""
    global _engine
    if _engine:
        await _engine.dispose()
        _engine = None
        logger.info("数据库连接已关闭")


async def check_db_health() -> dict:
    """
    检查数据库健康状态
    
    Returns:
        健康状态信息
    """
    try:
        engine = get_engine()
        async with engine.connect() as conn:
            # 执行简单查询测试连接
            result = await conn.execute("SELECT 1")
            await result.fetchone()
        
        return {
            "status": "healthy",
            "url": DATABASE_URL.split("@")[-1] if "@" in DATABASE_URL else DATABASE_URL,
        }
    except Exception as e:
        logger.error(f"数据库健康检查失败: {e}")
        return {
            "status": "unhealthy",
            "error": str(e),
        }


async def get_db_stats() -> dict:
    """
    获取数据库连接统计
    
    Returns:
        连接池统计信息
    """
    engine = get_engine()
    
    # SQLAlchemy 连接池统计
    pool = engine.pool
    return {
        "size": pool.size() if hasattr(pool, 'size') else 0,
        "checked_in": pool.checkedin() if hasattr(pool, 'checkedin') else 0,
        "checked_out": pool.checkedout() if hasattr(pool, 'checkedout') else 0,
        "overflow": pool.overflow() if hasattr(pool, 'overflow') else 0,
    }
