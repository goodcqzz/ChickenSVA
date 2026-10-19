#!/usr/bin/env python3
"""
注释查询接口 - 提供统一的注释数据查询API
整合GFF3解析、基因注释和索引功能
"""

import logging
from typing import Any, Dict, List, Optional, Union
from dataclasses import dataclass

from .gff3_parser import GFF3Parser
from .gene_annotator import GeneAnnotator
from .annotation_index import AnnotationIndex

logger = logging.getLogger(__name__)


@dataclass
class QueryResult:
    """查询结果"""
    success: bool
    data: Optional[Any] = None
    count: int = 0
    message: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "data": self.data,
            "count": self.count,
            "message": self.message
        }


class AnnotationQuery:
    """
    注释查询接口
    
    功能：
    1. 统一查询基因注释信息
    2. 支持多种查询方式（ID、位置、功能）
    3. 整合多个数据源
    4. 结果格式化和过滤
    """
    
    def __init__(
        self,
        gff3_path: Optional[str] = None,
        annotation_db: Optional[str] = None,
        index_path: Optional[str] = None
    ):
        # 初始化组件
        self.gff3: Optional[GFF3Parser] = None
        self.annotator: Optional[GeneAnnotator] = None
        self.index: Optional[AnnotationIndex] = None
        
        if gff3_path:
            self.gff3 = GFF3Parser(gff3_path)
            self.annotator = GeneAnnotator(self.gff3, annotation_db)
            self.index = AnnotationIndex(self.gff3, index_path)
    
    def query_by_gene_id(self, gene_id: str) -> QueryResult:
        """
        按基因ID查询
        
        Args:
            gene_id: 基因ID
            
        Returns:
            查询结果
        """
        if not self.gff3:
            return QueryResult(
                success=False,
                message="GFF3解析器未初始化"
            )
        
        try:
            gene = self.gff3.get_gene(gene_id)
            
            if not gene:
                return QueryResult(
                    success=True,
                    data=None,
                    count=0,
                    message=f"未找到基因: {gene_id}"
                )
            
            # 获取完整信息
            result = {
                "gene": gene.to_dict(),
                "structure": self.gff3.get_gene_structure(gene_id),
                "annotation": None
            }
            
            # 添加功能注释
            if self.annotator:
                annotation = self.annotator.annotate_gene(gene_id)
                if annotation:
                    result["annotation"] = annotation.to_dict()
            
            return QueryResult(
                success=True,
                data=result,
                count=1,
                message="查询成功"
            )
            
        except Exception as e:
            logger.error(f"查询失败: {e}")
            return QueryResult(
                success=False,
                message=f"查询出错: {str(e)}"
            )
    
    def query_by_gene_name(self, gene_name: str) -> QueryResult:
        """按基因名称查询"""
        if not self.gff3:
            return QueryResult(
                success=False,
                message="GFF3解析器未初始化"
            )
        
        try:
            gene = self.gff3.find_gene_by_name(gene_name)
            
            if not gene:
                return QueryResult(
                    success=True,
                    data=None,
                    count=0,
                    message=f"未找到基因: {gene_name}"
                )
            
            return self.query_by_gene_id(gene.gene_id)
            
        except Exception as e:
            return QueryResult(
                success=False,
                message=f"查询出错: {str(e)}"
            )
    
    def query_by_region(
        self,
        chromosome: str,
        start: int,
        end: int,
        include_features: bool = False
    ) -> QueryResult:
        """
        按基因组区域查询
        
        Args:
            chromosome: 染色体
            start: 起始位置
            end: 结束位置
            include_features: 是否包含所有特征
            
        Returns:
            查询结果
        """
        if not self.gff3:
            return QueryResult(
                success=False,
                message="GFF3解析器未初始化"
            )
        
        try:
            # 获取区域内的基因
            genes = self.gff3.get_genes_in_region(chromosome, start, end)
            
            results = []
            for gene in genes:
                gene_data = {
                    "gene": gene.to_dict()
                }
                
                if include_features:
                    gene_data["structure"] = self.gff3.get_gene_structure(gene.gene_id)
                
                results.append(gene_data)
            
            return QueryResult(
                success=True,
                data=results,
                count=len(results),
                message=f"找到 {len(results)} 个基因"
            )
            
        except Exception as e:
            return QueryResult(
                success=False,
                message=f"查询出错: {str(e)}"
            )
    
    def query_by_function(
        self,
        keyword: str,
        annotation_type: str = "all"
    ) -> QueryResult:
        """
        按功能关键词查询
        
        Args:
            keyword: 搜索关键词
            annotation_type: 注释类型
            
        Returns:
            查询结果
        """
        if not self.annotator:
            return QueryResult(
                success=False,
                message="注释器未初始化"
            )
        
        try:
            gene_ids = self.annotator.search_genes_by_function(keyword, annotation_type)
            
            results = []
            for gene_id in gene_ids:
                annotation = self.annotator.annotate_gene(gene_id)
                if annotation:
                    results.append(annotation.to_dict())
            
            return QueryResult(
                success=True,
                data=results,
                count=len(results),
                message=f"找到 {len(results)} 个相关基因"
            )
            
        except Exception as e:
            return QueryResult(
                success=False,
                message=f"查询出错: {str(e)}"
            )
    
    def batch_query(self, gene_ids: List[str]) -> QueryResult:
        """批量查询基因"""
        if not self.gff3:
            return QueryResult(
                success=False,
                message="GFF3解析器未初始化"
            )
        
        results = []
        not_found = []
        
        for gene_id in gene_ids:
            gene = self.gff3.get_gene(gene_id)
            if gene:
                result = {"gene": gene.to_dict()}
                
                if self.annotator:
                    annotation = self.annotator.annotate_gene(gene_id)
                    if annotation:
                        result["annotation"] = annotation.to_dict()
                
                results.append(result)
            else:
                not_found.append(gene_id)
        
        message = f"找到 {len(results)}/{len(gene_ids)} 个基因"
        if not_found:
            message += f"，未找到: {', '.join(not_found[:5])}"
            if len(not_found) > 5:
                message += f" 等 {len(not_found)} 个"
        
        return QueryResult(
            success=True,
            data=results,
            count=len(results),
            message=message
        )
    
    def get_statistics(self) -> QueryResult:
        """获取注释数据统计"""
        if not self.gff3:
            return QueryResult(
                success=False,
                message="GFF3解析器未初始化"
            )
        
        try:
            stats = self.gff3.get_statistics()
            
            if self.index:
                index_stats = self.index.get_index_stats()
                stats.update(index_stats)
            
            return QueryResult(
                success=True,
                data=stats,
                message="统计信息"
            )
            
        except Exception as e:
            return QueryResult(
                success=False,
                message=f"获取统计失败: {str(e)}"
            )
    
    def get_chromosomes(self) -> QueryResult:
        """获取染色体列表"""
        if not self.gff3:
            return QueryResult(
                success=False,
                message="GFF3解析器未初始化"
            )
        
        chromosomes = self.gff3.get_chromosomes()
        
        return QueryResult(
            success=True,
            data=chromosomes,
            count=len(chromosomes),
            message=f"共 {len(chromosomes)} 条染色体"
        )
    
    def get_feature_types(self) -> QueryResult:
        """获取特征类型列表"""
        if not self.gff3:
            return QueryResult(
                success=False,
                message="GFF3解析器未初始化"
            )
        
        feature_types = self.gff3.get_feature_types()
        
        return QueryResult(
            success=True,
            data=feature_types,
            count=len(feature_types),
            message=f"共 {len(feature_types)} 种特征类型"
        )
    
    def find_nearest_genes(
        self,
        chromosome: str,
        position: int,
        n: int = 5
    ) -> QueryResult:
        """查找最近的基因"""
        if not self.index:
            return QueryResult(
                success=False,
                message="索引未初始化"
            )
        
        try:
            nearest = self.index.find_nearest_genes(chromosome, position, n)
            
            results = []
            for gene_id, distance in nearest:
                gene = self.gff3.get_gene(gene_id) if self.gff3 else None
                if gene:
                    results.append({
                        "gene": gene.to_dict(),
                        "distance": distance
                    })
            
            return QueryResult(
                success=True,
                data=results,
                count=len(results),
                message=f"找到 {len(results)} 个最近基因"
            )
            
        except Exception as e:
            return QueryResult(
                success=False,
                message=f"查询出错: {str(e)}"
            )
    
    def export_gene_list(
        self,
        gene_ids: List[str],
        format: str = "json"
    ) -> QueryResult:
        """
        导出基因列表
        
        Args:
            gene_ids: 基因ID列表
            format: 导出格式 (json, csv, tsv)
            
        Returns:
            导出结果
        """
        result = self.batch_query(gene_ids)
        
        if not result.success:
            return result
        
        if format == "json":
            return result
        
        elif format in ("csv", "tsv"):
            # 转换为表格格式
            delimiter = "," if format == "csv" else "\t"
            
            rows = []
            for item in result.data or []:
                gene = item.get("gene", {})
                row = {
                    "gene_id": gene.get("gene_id"),
                    "gene_name": gene.get("gene_name"),
                    "chromosome": gene.get("chromosome"),
                    "start": gene.get("start"),
                    "end": gene.get("end"),
                    "strand": gene.get("strand"),
                    "length": gene.get("length")
                }
                rows.append(row)
            
            return QueryResult(
                success=True,
                data=rows,
                count=len(rows),
                message=f"导出为 {format.upper()} 格式"
            )
        
        else:
            return QueryResult(
                success=False,
                message=f"不支持的格式: {format}"
            )
