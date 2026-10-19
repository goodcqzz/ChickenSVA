#!/usr/bin/env python3
"""
数据库管理器 - 统一管理SV数据库连接和查询
支持多种数据源：CSV、SQLite、PostgreSQL
"""

import os
import json
import sqlite3
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
from dataclasses import dataclass, asdict
from datetime import datetime

import pandas as pd
import numpy as np


def _project_root() -> Path:
    """推断仓库根目录（database_manager.py 位于 repo/data/）"""
    return Path(__file__).resolve().parent.parent


logger = logging.getLogger(__name__)


@dataclass
class DatabaseInfo:
    """数据库元信息"""
    name: str
    version: str
    total_samples: int
    total_variants: int
    sv_types: List[str]
    breeds: int
    chromosomes: List[str]
    last_updated: str
    data_sources: List[str]
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class QueryResult:
    """查询结果封装"""
    success: bool
    data: Optional[List[Dict]] = None
    total_count: int = 0
    query_time_ms: float = 0.0
    error_message: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "data": self.data,
            "total_count": self.total_count,
            "query_time_ms": self.query_time_ms,
            "error_message": self.error_message
        }


class DatabaseManager:
    """
    数据库管理器
    
    功能：
    1. 统一管理多个数据源
    2. 提供标准化的查询接口
    3. 支持数据缓存和连接池
    4. 自动数据验证和清理
    """
    
    CSV_ENCODINGS = ['utf-8', 'gbk', 'gb2312', 'gb18030', 'latin1']
    
    def __init__(
        self,
        data_path: str = "",
        cache_enabled: bool = True,
        cache_size: int = 1000
    ):
        if not data_path:
            data_path = str(_project_root() / "data")
        self.data_path = Path(data_path)
        self.cache_enabled = cache_enabled
        self.cache_size = cache_size
        
        # 数据源存储
        self._dataframes: Dict[str, pd.DataFrame] = {}
        self._database_info: Optional[DatabaseInfo] = None
        self._breed_columns: Dict[str, List[str]] = {}
        self._sv_metadata: Dict[str, Any] = {}
        
        # 缓存
        self._query_cache: Dict[str, Any] = {}
        
        # 初始化
        self._initialize()
    
    def _initialize(self):
        """初始化数据库管理器"""
        logger.info("初始化数据库管理器...")
        
        # 加载所有CSV文件
        self._load_csv_files()
        
        # 计算数据库统计信息
        self._calculate_statistics()
        
        logger.info(f"数据库管理器初始化完成，加载了 {len(self._dataframes)} 个数据文件")
    
    def _load_csv_files(self):
        """加载所有CSV数据文件"""
        if not self.data_path.exists():
            logger.warning(f"数据路径不存在: {self.data_path}")
            return
        
        csv_files = list(self.data_path.glob("*.csv"))
        
        for csv_file in csv_files:
            try:
                df = self._read_csv_with_encoding(csv_file)
                if df is not None and not df.empty:
                    key = csv_file.stem
                    self._dataframes[key] = df
                    self._breed_columns[key] = self._extract_breed_columns(df)
                    logger.info(f"✓ 加载数据文件: {csv_file.name} ({len(df)} 行)")
            except Exception as e:
                logger.error(f"✗ 加载失败 {csv_file.name}: {e}")
    
    def _read_csv_with_encoding(self, file_path: Path) -> Optional[pd.DataFrame]:
        """尝试多种编码读取CSV文件"""
        for encoding in self.CSV_ENCODINGS:
            try:
                df = pd.read_csv(file_path, encoding=encoding)
                # 清理列名
                df.columns = [str(col).strip() for col in df.columns]
                return df
            except UnicodeDecodeError:
                continue
            except Exception as e:
                logger.debug(f"编码 {encoding} 失败: {e}")
                continue
        
        logger.error(f"无法读取文件: {file_path}")
        return None
    
    def _extract_breed_columns(self, df: pd.DataFrame) -> List[str]:
        """提取品种列（SV频率数据列）"""
        # 标准SV数据格式：前10列为元数据，之后为品种频率
        if 'Mean_fre' in df.columns:
            idx = df.columns.get_loc('Mean_fre')
            return list(df.columns[idx + 1:])
        
        # 表型数据格式：第一列为性状，之后为品种
        if len(df.columns) > 1:
            return list(df.columns[1:])
        
        return []
    
    def _calculate_statistics(self):
        """计算数据库统计信息"""
        total_variants = 0
        all_sv_types = set()
        all_breeds = set()
        
        for name, df in self._dataframes.items():
            if 'SV_Type' in df.columns:
                total_variants += len(df)
                all_sv_types.update(df['SV_Type'].dropna().unique())
            
            breeds = self._breed_columns.get(name, [])
            all_breeds.update(breeds)
        
        self._database_info = DatabaseInfo(
            name="鸡基因组SV数据库",
            version="3.2.1",
            total_samples=len(all_breeds),
            total_variants=total_variants,
            sv_types=sorted(list(all_sv_types)),
            breeds=len(all_breeds),
            chromosomes=[f"chr{i}" for i in range(1, 29)] + ["chrZ", "chrW", "chrM"],
            last_updated=datetime.now().strftime("%Y-%m-%d"),
            data_sources=list(self._dataframes.keys())
        )
    
    def get_database_info(self) -> Dict[str, Any]:
        """获取数据库元信息"""
        if self._database_info:
            return self._database_info.to_dict()
        return {}
    
    def query_by_gene(
        self,
        gene_name: str,
        database: Optional[str] = None,
        limit: int = 100
    ) -> QueryResult:
        """
        按基因名查询SV
        
        Args:
            gene_name: 基因名称（如 IGF2BP1）
            database: 指定数据库，None则搜索所有
            limit: 返回结果数量限制
        """
        start_time = datetime.now()
        
        try:
            results = []
            
            sources = [database] if database else list(self._dataframes.keys())
            
            for source in sources:
                if source not in self._dataframes:
                    continue
                
                df = self._dataframes[source]
                
                # 检查是否有Gene列
                if 'Gene' not in df.columns:
                    continue
                
                # 模糊匹配基因名
                mask = df['Gene'].str.contains(gene_name, case=False, na=False)
                matched = df[mask].head(limit)
                
                for _, row in matched.iterrows():
                    result = self._row_to_dict(row, source)
                    results.append(result)
            
            query_time = (datetime.now() - start_time).total_seconds() * 1000
            
            return QueryResult(
                success=True,
                data=results,
                total_count=len(results),
                query_time_ms=query_time
            )
            
        except Exception as e:
            logger.error(f"基因查询失败: {e}")
            return QueryResult(
                success=False,
                error_message=str(e),
                query_time_ms=(datetime.now() - start_time).total_seconds() * 1000
            )
    
    def query_by_region(
        self,
        chromosome: str,
        start: int,
        end: int,
        database: Optional[str] = None,
        limit: int = 100
    ) -> QueryResult:
        """
        按基因组区域查询SV
        
        Args:
            chromosome: 染色体（如 chr1）
            start: 起始位置
            end: 结束位置
            database: 指定数据库
            limit: 返回结果数量限制
        """
        start_time = datetime.now()
        
        try:
            results = []
            sources = [database] if database else list(self._dataframes.keys())
            
            for source in sources:
                if source not in self._dataframes:
                    continue
                
                df = self._dataframes[source]
                
                # 检查必要的列
                if 'Chr' not in df.columns or 'POS' not in df.columns:
                    continue
                
                # 标准化染色体名称
                chr_num = chromosome.replace('chr', '')
                
                # 区域查询
                mask = (
                    (df['Chr'].astype(str) == chr_num) &
                    (df['POS'].astype(int) >= start) &
                    (df['POS'].astype(int) <= end)
                )
                
                matched = df[mask].head(limit)
                
                for _, row in matched.iterrows():
                    result = self._row_to_dict(row, source)
                    results.append(result)
            
            query_time = (datetime.now() - start_time).total_seconds() * 1000
            
            return QueryResult(
                success=True,
                data=results,
                total_count=len(results),
                query_time_ms=query_time
            )
            
        except Exception as e:
            logger.error(f"区域查询失败: {e}")
            return QueryResult(
                success=False,
                error_message=str(e),
                query_time_ms=(datetime.now() - start_time).total_seconds() * 1000
            )
    
    def query_by_sv_id(
        self,
        sv_id: str,
        database: Optional[str] = None
    ) -> QueryResult:
        """按SV ID查询"""
        start_time = datetime.now()
        
        try:
            sources = [database] if database else list(self._dataframes.keys())
            
            for source in sources:
                if source not in self._dataframes:
                    continue
                
                df = self._dataframes[source]
                
                # 检查ID列
                id_col = 'ID' if 'ID' in df.columns else df.columns[0]
                
                mask = df[id_col].astype(str) == sv_id
                matched = df[mask]
                
                if not matched.empty:
                    query_time = (datetime.now() - start_time).total_seconds() * 1000
                    return QueryResult(
                        success=True,
                        data=[self._row_to_dict(matched.iloc[0], source)],
                        total_count=1,
                        query_time_ms=query_time
                    )
            
            return QueryResult(
                success=True,
                data=[],
                total_count=0,
                query_time_ms=(datetime.now() - start_time).total_seconds() * 1000
            )
            
        except Exception as e:
            return QueryResult(
                success=False,
                error_message=str(e),
                query_time_ms=(datetime.now() - start_time).total_seconds() * 1000
            )
    
    def _row_to_dict(self, row: pd.Series, source: str) -> Dict[str, Any]:
        """将DataFrame行转换为字典"""
        result = {
            "source": source,
            "data": row.to_dict()
        }
        
        # 添加品种频率统计
        breed_cols = self._breed_columns.get(source, [])
        if breed_cols:
            frequencies = []
            for col in breed_cols:
                if col in row and pd.notna(row[col]):
                    try:
                        frequencies.append({
                            "breed": col,
                            "frequency": float(row[col])
                        })
                    except (ValueError, TypeError):
                        pass
            
            if frequencies:
                result["breed_frequencies"] = frequencies
                result["mean_frequency"] = np.mean([f["frequency"] for f in frequencies])
        
        return result
    
    def get_available_databases(self) -> List[str]:
        """获取可用的数据库列表"""
        return list(self._dataframes.keys())
    
    def get_breed_list(self) -> List[str]:
        """获取所有品种列表"""
        all_breeds = set()
        for breeds in self._breed_columns.values():
            all_breeds.update(breeds)
        return sorted(list(all_breeds))
    
    def get_sv_types(self) -> List[str]:
        """获取SV类型列表"""
        if self._database_info:
            return self._database_info.sv_types
        return []
    
    def reload_data(self):
        """重新加载数据"""
        self._dataframes.clear()
        self._breed_columns.clear()
        self._initialize()
