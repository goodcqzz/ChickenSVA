"""
数据适配器

提供统一的数据访问接口：
- 数据验证
- 异常处理
- 查询优化
- 结果格式化
"""

import logging
from typing import Dict, Any, Optional, List, Union
from dataclasses import dataclass
from datetime import datetime

from app.data.sv_database import (
    SVDatabase, SVQuery, SVRecord, SVQueryResult,
    get_sv_database
)

logger = logging.getLogger(__name__)


class DataValidationError(Exception):
    """数据验证错误"""
    pass


class DataNotFoundError(Exception):
    """数据未找到错误"""
    pass


@dataclass
class QueryParams:
    """标准化查询参数"""
    query_type: str  # gene, region, sv_id
    query_value: str
    sample_filter: Optional[str] = None
    sv_type: Optional[str] = None
    limit: int = 100


class DataAdapter:
    """
    数据适配器
    
    统一封装 SV 数据库访问，提供：
    - 参数验证
    - 查询转换
    - 结果格式化
    - 错误处理
    """
    
    def __init__(self, database: Optional[SVDatabase] = None):
        self.db = database or get_sv_database()
        
        if not self.db:
            raise RuntimeError("SV 数据库未初始化")
    
    async def query_sv(self, params: QueryParams) -> Dict[str, Any]:
        """
        查询 SV 数据
        
        Args:
            params: 查询参数
            
        Returns:
            格式化的查询结果
        """
        try:
            # 验证参数
            self._validate_params(params)
            
            # 转换查询
            sv_query = self._convert_query(params)
            
            # 执行查询
            result = await self.db.query(sv_query)
            
            # 格式化结果
            return self._format_result(result, params)
            
        except DataValidationError as e:
            logger.warning(f"查询参数验证失败: {e}")
            return {
                "success": False,
                "error": str(e),
                "data": []
            }
        except Exception as e:
            logger.error(f"查询 SV 数据失败: {e}")
            return {
                "success": False,
                "error": f"查询失败: {str(e)}",
                "data": []
            }
    
    async def query_gene_sv(self, gene_name: str, breed: Optional[str] = None) -> Dict[str, Any]:
        """
        查询基因的 SV
        
        Args:
            gene_name: 基因名
            breed: 品种筛选
            
        Returns:
            查询结果
        """
        try:
            records = await self.db.get_by_gene(gene_name)
            
            if not records:
                return {
                    "success": True,
                    "gene": gene_name,
                    "sv_count": 0,
                    "data": [],
                    "message": f"未找到基因 {gene_name} 的 SV 记录"
                }
            
            # 格式化记录
            data = []
            for record in records:
                item = self._format_record(record)
                
                # 添加品种频率
                if breed:
                    item["breed_frequency"] = self._get_breed_frequency(record, breed)
                
                data.append(item)
            
            return {
                "success": True,
                "gene": gene_name,
                "sv_count": len(data),
                "data": data
            }
            
        except Exception as e:
            logger.error(f"查询基因 SV 失败: {e}")
            return {
                "success": False,
                "error": str(e),
                "gene": gene_name
            }
    
    async def query_region_sv(
        self,
        chrom: str,
        start: int,
        end: int,
        breed: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        查询区域的 SV
        
        Args:
            chrom: 染色体
            start: 起始位置
            end: 结束位置
            breed: 品种筛选
            
        Returns:
            查询结果
        """
        try:
            records = await self.db.get_by_region(chrom, start, end)
            
            # 格式化记录
            data = [self._format_record(r) for r in records]
            
            return {
                "success": True,
                "region": f"{chrom}:{start}-{end}",
                "sv_count": len(data),
                "data": data
            }
            
        except Exception as e:
            logger.error(f"查询区域 SV 失败: {e}")
            return {
                "success": False,
                "error": str(e),
                "region": f"{chrom}:{start}-{end}"
            }
    
    async def get_sv_frequency(self, sv_id: str, breed: Optional[str] = None) -> Dict[str, Any]:
        """
        获取 SV 频率
        
        Args:
            sv_id: SV ID
            breed: 品种
            
        Returns:
            频率信息
        """
        try:
            freq_info = await self.db.get_frequency(sv_id, breed)
            
            if "error" in freq_info:
                return {
                    "success": False,
                    "error": freq_info["error"],
                    "sv_id": sv_id
                }
            
            return {
                "success": True,
                **freq_info
            }
            
        except Exception as e:
            logger.error(f"获取 SV 频率失败: {e}")
            return {
                "success": False,
                "error": str(e),
                "sv_id": sv_id
            }
    
    def _validate_params(self, params: QueryParams):
        """验证查询参数"""
        valid_types = ["gene", "region", "sv_id", "chrom"]
        
        if params.query_type not in valid_types:
            raise DataValidationError(f"不支持的查询类型: {params.query_type}")
        
        if not params.query_value:
            raise DataValidationError("查询值不能为空")
        
        if params.query_type == "region":
            # 验证区域格式
            if ":" not in params.query_value:
                raise DataValidationError("区域格式错误，应为: chr:start-end")
        
        if params.limit < 1 or params.limit > 1000:
            raise DataValidationError("limit 必须在 1-1000 之间")
    
    def _convert_query(self, params: QueryParams) -> SVQuery:
        """转换查询参数"""
        if params.query_type == "gene":
            return SVQuery(
                gene_name=params.query_value,
                sv_type=params.sv_type,
                limit=params.limit
            )
        
        elif params.query_type == "region":
            # 解析区域
            chrom, pos = params.query_value.split(":")
            start, end = map(int, pos.split("-"))
            
            return SVQuery(
                chrom=chrom,
                start=start,
                end=end,
                sv_type=params.sv_type,
                limit=params.limit
            )
        
        elif params.query_type == "sv_id":
            # SV ID 查询在格式化结果时处理
            return SVQuery(limit=1)
        
        elif params.query_type == "chrom":
            return SVQuery(
                chrom=params.query_value,
                sv_type=params.sv_type,
                limit=params.limit
            )
        
        return SVQuery(limit=params.limit)
    
    def _format_result(
        self,
        result: SVQueryResult,
        params: QueryParams
    ) -> Dict[str, Any]:
        """格式化查询结果"""
        data = []
        
        for record in result.records:
            item = self._format_record(record)
            
            # 添加品种频率信息
            if params.sample_filter:
                item["breed_frequency"] = self._get_breed_frequency(
                    record, params.sample_filter
                )
            
            data.append(item)
        
        return {
            "success": True,
            "query_type": params.query_type,
            "query_value": params.query_value,
            "total": result.total,
            "returned": len(data),
            "has_more": result.has_more,
            "data": data
        }
    
    def _format_record(self, record: SVRecord) -> Dict[str, Any]:
        """格式化单条记录"""
        return {
            "sv_id": record.id,
            "chrom": record.chrom,
            "start": record.start,
            "end": record.end,
            "sv_type": record.sv_type,
            "length": record.length,
            "gene": {
                "name": record.gene_name,
                "id": record.gene_id
            } if record.gene_name else None,
            "frequency": {
                "gushi": record.freq_gushi,
                **record.freq_other_breeds
            },
            "annotation": record.annotation,
            "impact": record.impact,
            "quality": record.quality,
        }
    
    def _get_breed_frequency(self, record: SVRecord, breed: str) -> Dict[str, Any]:
        """获取特定品种频率"""
        if breed == "固始":
            return {
                "breed": breed,
                "frequency": record.freq_gushi,
                "has_data": record.freq_gushi > 0
            }
        else:
            freq = record.freq_other_breeds.get(breed, 0.0)
            return {
                "breed": breed,
                "frequency": freq,
                "has_data": freq > 0
            }


# 适配器实例
_data_adapter: Optional[DataAdapter] = None


def init_data_adapter(database: Optional[SVDatabase] = None) -> DataAdapter:
    """初始化数据适配器"""
    global _data_adapter
    _data_adapter = DataAdapter(database)
    return _data_adapter


def get_data_adapter() -> Optional[DataAdapter]:
    """获取数据适配器"""
    return _data_adapter
