"""
真实数据层模块

提供与SV数据库的连接适配：
- 安全的数据访问接口
- 数据验证机制
- 异常处理策略
- 查询优化
"""

from app.data.sv_database import (
    SVDatabase,
    SVDatabaseConfig,
    SVRecord,
    SVQuery,
    SVQueryResult,
    init_sv_database,
    get_sv_database,
)
from app.data.data_adapter import DataAdapter, DataValidationError, init_data_adapter

__all__ = [
    "SVDatabase",
    "SVDatabaseConfig",
    "SVRecord",
    "SVQuery",
    "SVQueryResult",
    "DataAdapter",
    "DataValidationError",
    "init_sv_database",
    "get_sv_database",
    "init_data_adapter",
]
