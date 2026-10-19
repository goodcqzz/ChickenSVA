#!/usr/bin/env python3
"""
注释索引管理器 - 管理基因组注释数据的索引
支持快速基因查询、区域检索和特征定位
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, asdict
from collections import defaultdict

from .gff3_parser import GFF3Parser, GeneModel

logger = logging.getLogger(__name__)


@dataclass
class IndexEntry:
    """索引条目"""
    gene_id: str
    chromosome: str
    start: int
    end: int
    file_offset: Optional[int] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class AnnotationIndex:
    """
    注释索引管理器
    
    功能：
    1. 构建基因位置索引
    2. 支持染色体快速查询
    3. 区间树索引加速区域查询
    4. 索引持久化
    """
    
    def __init__(
        self,
        gff3_parser: Optional[GFF3Parser] = None,
        index_path: Optional[str] = None
    ):
        self.gff3 = gff3_parser
        self.index_path = Path(index_path) if index_path else None
        
        # 索引数据结构
        self._gene_by_chromosome: Dict[str, List[str]] = defaultdict(list)
        self._gene_positions: Dict[str, Tuple[str, int, int]] = {}  # gene_id -> (chr, start, end)
        self._interval_tree: Optional[Dict] = None
        
        # 加载或构建索引
        if self.index_path and self.index_path.exists():
            self._load_index()
        elif gff3_parser:
            self._build_index_from_gff3()
    
    def _build_index_from_gff3(self):
        """从GFF3构建索引"""
        if not self.gff3:
            return
        
        logger.info("从GFF3构建注释索引...")
        
        for gene in self.gff3.iter_genes():
            # 染色体索引
            self._gene_by_chromosome[gene.chromosome].append(gene.gene_id)
            
            # 位置索引
            self._gene_positions[gene.gene_id] = (
                gene.chromosome,
                gene.start,
                gene.end
            )
        
        logger.info(f"✓ 索引构建完成: {len(self._gene_positions)} 个基因")
    
    def _load_index(self):
        """从文件加载索引"""
        try:
            with open(self.index_path, 'r') as f:
                data = json.load(f)
            
            self._gene_by_chromosome = defaultdict(list, data.get('by_chromosome', {}))
            self._gene_positions = data.get('positions', {})
            
            logger.info(f"✓ 索引加载完成: {len(self._gene_positions)} 个基因")
            
        except Exception as e:
            logger.error(f"索引加载失败: {e}")
            # 如果加载失败，尝试重新构建
            if self.gff3:
                self._build_index_from_gff3()
    
    def save_index(self, index_path: Optional[str] = None):
        """
        保存索引到文件
        
        Args:
            index_path: 索引文件路径
        """
        path = Path(index_path) if index_path else self.index_path
        
        if not path:
            raise ValueError("未指定索引路径")
        
        data = {
            'by_chromosome': dict(self._gene_by_chromosome),
            'positions': self._gene_positions,
            'version': '1.0'
        }
        
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)
        
        logger.info(f"✓ 索引已保存: {path}")
    
    def get_genes_by_chromosome(self, chromosome: str) -> List[str]:
        """获取染色体上的所有基因"""
        return self._gene_by_chromosome.get(chromosome, [])
    
    def get_gene_position(self, gene_id: str) -> Optional[Tuple[str, int, int]]:
        """获取基因位置"""
        return self._gene_positions.get(gene_id)
    
    def find_genes_in_region(
        self,
        chromosome: str,
        start: int,
        end: int
    ) -> List[str]:
        """
        查找区域内的基因
        
        Args:
            chromosome: 染色体
            start: 起始位置
            end: 结束位置
            
        Returns:
            基因ID列表
        """
        matching_genes = []
        
        for gene_id in self._gene_by_chromosome.get(chromosome, []):
            pos = self._gene_positions.get(gene_id)
            if pos:
                _, gene_start, gene_end = pos
                # 检查重叠
                if gene_start <= end and gene_end >= start:
                    matching_genes.append(gene_id)
        
        return matching_genes
    
    def find_nearest_genes(
        self,
        chromosome: str,
        position: int,
        n: int = 5
    ) -> List[Tuple[str, int]]:
        """
        查找最近的基因
        
        Args:
            chromosome: 染色体
            position: 位置
            n: 返回基因数量
            
        Returns:
            (基因ID, 距离) 列表
        """
        distances = []
        
        for gene_id in self._gene_by_chromosome.get(chromosome, []):
            pos = self._gene_positions.get(gene_id)
            if pos:
                _, gene_start, gene_end = pos
                # 计算到基因的距离
                if gene_start <= position <= gene_end:
                    distance = 0
                elif position < gene_start:
                    distance = gene_start - position
                else:
                    distance = position - gene_end
                
                distances.append((gene_id, distance))
        
        # 排序并返回最近的n个
        distances.sort(key=lambda x: x[1])
        return distances[:n]
    
    def get_chromosome_stats(self, chromosome: str) -> Dict[str, Any]:
        """获取染色体统计信息"""
        genes = self._gene_by_chromosome.get(chromosome, [])
        
        if not genes:
            return {"gene_count": 0}
        
        # 计算长度统计
        lengths = []
        for gene_id in genes:
            pos = self._gene_positions.get(gene_id)
            if pos:
                _, start, end = pos
                lengths.append(end - start + 1)
        
        return {
            "gene_count": len(genes),
            "total_length": sum(lengths) if lengths else 0,
            "avg_gene_length": sum(lengths) / len(lengths) if lengths else 0,
            "min_position": min(pos[1] for pos in [self._gene_positions.get(g) for g in genes] if pos) if genes else None,
            "max_position": max(pos[2] for pos in [self._gene_positions.get(g) for g in genes] if pos) if genes else None
        }
    
    def get_index_stats(self) -> Dict[str, Any]:
        """获取索引统计信息"""
        total_genes = len(self._gene_positions)
        chromosomes = list(self._gene_by_chromosome.keys())
        
        return {
            "total_genes": total_genes,
            "chromosomes": chromosomes,
            "chromosome_count": len(chromosomes),
            "genes_per_chromosome": {
                chr: len(genes)
                for chr, genes in self._gene_by_chromosome.items()
            }
        }


# Interval Tree implementation for efficient range queries
class IntervalTree:
    """
    区间树 - 用于高效区间查询
    """
    
    def __init__(self):
        self.intervals: List[Tuple[int, int, str]] = []  # (start, end, data)
    
    def add(self, start: int, end: int, data: str):
        """添加区间"""
        self.intervals.append((start, end, data))
    
    def query(self, start: int, end: int) -> List[str]:
        """查询与给定区间重叠的所有区间"""
        results = []
        for s, e, data in self.intervals:
            if s <= end and e >= start:
                results.append(data)
        return results
    
    def build(self):
        """构建索引（简化版，实际可实现更复杂的平衡树）"""
        # 按起始位置排序
        self.intervals.sort(key=lambda x: x[0])
