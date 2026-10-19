#!/usr/bin/env python3
"""
数据层模块 - 鸡基因组SV数据库数据处理组件
提供统一的数据访问接口和数据管理功能
"""

from .database_manager import DatabaseManager, DatabaseInfo, QueryResult
from .sv_data_loader import SVDataLoader, SVRecord
from .phenotype_manager import PhenotypeManager
from .data_validator import DataValidator, ValidationResult, ValidationSeverity

__version__ = "2.0.0"
__all__ = [
    "DatabaseManager",
    "DatabaseInfo",
    "QueryResult",
    "SVDataLoader",
    "SVRecord",
    "PhenotypeManager",
    "DataValidator",
    "ValidationResult",
    "ValidationSeverity",
]
