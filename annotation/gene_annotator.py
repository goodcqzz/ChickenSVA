#!/usr/bin/env python3
"""
基因注释器 - 提供基因功能注释和富集分析
支持GO、KEGG等功能注释
"""

import re
import logging
from typing import Any, Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, field
from collections import defaultdict

from .gff3_parser import GFF3Parser, GeneModel

logger = logging.getLogger(__name__)


@dataclass
class FunctionalAnnotation:
    """功能注释"""
    gene_id: str
    gene_name: Optional[str]
    go_terms: List[Dict[str, str]] = field(default_factory=list)
    kegg_pathways: List[Dict[str, str]] = field(default_factory=list)
    pfam_domains: List[Dict[str, str]] = field(default_factory=list)
    description: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "gene_id": self.gene_id,
            "gene_name": self.gene_name,
            "go_terms": self.go_terms,
            "kegg_pathways": self.kegg_pathways,
            "pfam_domains": self.pfam_domains,
            "description": self.description
        }


@dataclass
class EnrichmentResult:
    """富集分析结果"""
    term_id: str
    term_name: str
    category: str
    gene_count: int
    total_genes: int
    p_value: float
    adjusted_p_value: Optional[float] = None
    gene_ids: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "term_id": self.term_id,
            "term_name": self.term_name,
            "category": self.category,
            "gene_count": self.gene_count,
            "total_genes": self.total_genes,
            "p_value": self.p_value,
            "adjusted_p_value": self.adjusted_p_value,
            "gene_ids": self.gene_ids
        }


class GeneAnnotator:
    """
    基因注释器
    
    功能：
    1. 基因功能注释查询
    2. GO/KEGG富集分析
    3. 基因集功能分析
    4. 注释数据管理
    """
    
    # GO分类
    GO_CATEGORIES = {
        'BP': 'Biological Process',
        'CC': 'Cellular Component',
        'MF': 'Molecular Function'
    }
    
    def __init__(
        self,
        gff3_parser: Optional[GFF3Parser] = None,
        annotation_db: Optional[str] = None
    ):
        self.gff3 = gff3_parser
        self.annotation_db = annotation_db
        
        # 注释数据缓存
        self._go_annotations: Dict[str, List[Dict]] = {}
        self._kegg_annotations: Dict[str, List[Dict]] = {}
        self._gene_descriptions: Dict[str, str] = {}
        
        # 富集分析背景集
        self._background_genes: Set[str] = set()
        
        if annotation_db:
            self._load_annotation_db()
    
    def _load_annotation_db(self):
        """加载注释数据库"""
        # 这里可以加载外部的GO/KEGG注释文件
        # 格式可以是CSV、TSV或自定义格式
        logger.info(f"加载注释数据库: {self.annotation_db}")
    
    def annotate_gene(self, gene_id: str) -> Optional[FunctionalAnnotation]:
        """
        获取基因功能注释
        
        Args:
            gene_id: 基因ID
            
        Returns:
            功能注释信息
        """
        # 从GFF3获取基本信息
        gene_name = None
        if self.gff3:
            gene = self.gff3.get_gene(gene_id)
            if gene:
                gene_name = gene.gene_name
        
        # 构建注释
        annotation = FunctionalAnnotation(
            gene_id=gene_id,
            gene_name=gene_name
        )
        
        # 添加GO注释
        if gene_id in self._go_annotations:
            annotation.go_terms = self._go_annotations[gene_id]
        
        # 添加KEGG注释
        if gene_id in self._kegg_annotations:
            annotation.kegg_pathways = self._kegg_annotations[gene_id]
        
        # 添加描述
        if gene_id in self._gene_descriptions:
            annotation.description = self._gene_descriptions[gene_id]
        
        return annotation
    
    def annotate_gene_list(self, gene_ids: List[str]) -> List[FunctionalAnnotation]:
        """批量注释基因列表"""
        return [
            self.annotate_gene(gid)
            for gid in gene_ids
            if self.annotate_gene(gid)
        ]
    
    def search_genes_by_function(
        self,
        keyword: str,
        annotation_type: str = "all"
    ) -> List[str]:
        """
        按功能关键词搜索基因
        
        Args:
            keyword: 搜索关键词
            annotation_type: 注释类型 (go, kegg, description, all)
            
        Returns:
            基因ID列表
        """
        matching_genes = []
        keyword_lower = keyword.lower()
        
        # 搜索GO注释
        if annotation_type in ('go', 'all'):
            for gene_id, go_terms in self._go_annotations.items():
                for term in go_terms:
                    if keyword_lower in term.get('name', '').lower():
                        matching_genes.append(gene_id)
                        break
        
        # 搜索KEGG注释
        if annotation_type in ('kegg', 'all'):
            for gene_id, pathways in self._kegg_annotations.items():
                for pathway in pathways:
                    if keyword_lower in pathway.get('name', '').lower():
                        if gene_id not in matching_genes:
                            matching_genes.append(gene_id)
                        break
        
        # 搜索描述
        if annotation_type in ('description', 'all'):
            for gene_id, desc in self._gene_descriptions.items():
                if keyword_lower in desc.lower():
                    if gene_id not in matching_genes:
                        matching_genes.append(gene_id)
        
        return matching_genes
    
    def enrichment_analysis(
        self,
        gene_list: List[str],
        background: Optional[List[str]] = None,
        annotation_type: str = "go",
        pvalue_threshold: float = 0.05
    ) -> List[EnrichmentResult]:
        """
        富集分析
        
        Args:
            gene_list: 感兴趣的基因列表
            background: 背景基因集（可选）
            annotation_type: 注释类型 (go, kegg)
            pvalue_threshold: p值阈值
            
        Returns:
            富集结果列表
        """
        gene_set = set(gene_list)
        bg_set = set(background) if background else self._background_genes
        
        if not bg_set:
            bg_set = gene_set
        
        results = []
        
        if annotation_type == "go":
            results = self._go_enrichment(gene_set, bg_set)
        elif annotation_type == "kegg":
            results = self._kegg_enrichment(gene_set, bg_set)
        
        # 过滤和排序
        results = [
            r for r in results
            if r.p_value < pvalue_threshold
        ]
        results.sort(key=lambda x: x.p_value)
        
        return results
    
    def _go_enrichment(
        self,
        gene_set: Set[str],
        bg_set: Set[str]
    ) -> List[EnrichmentResult]:
        """GO富集分析"""
        # 统计每个GO term的基因数
        term_counts = defaultdict(lambda: {'study': 0, 'population': 0, 'genes': []})
        
        for gene_id in gene_set:
            if gene_id in self._go_annotations:
                for term in self._go_annotations[gene_id]:
                    term_id = term.get('id')
                    if term_id:
                        term_counts[term_id]['study'] += 1
                        term_counts[term_id]['genes'].append(gene_id)
        
        for gene_id in bg_set:
            if gene_id in self._go_annotations:
                for term in self._go_annotations[gene_id]:
                    term_id = term.get('id')
                    if term_id:
                        term_counts[term_id]['population'] += 1
        
        # 计算富集显著性
        results = []
        study_total = len(gene_set)
        pop_total = len(bg_set)
        
        for term_id, counts in term_counts.items():
            if counts['study'] < 2:  # 至少2个基因
                continue
            
            # 超几何检验（简化版）
            from scipy.stats import hypergeom
            
            k = counts['study']  # 研究集中属于该term的基因数
            M = pop_total  # 背景集总数
            n = counts['population']  # 背景集中属于该term的基因数
            N = study_total  # 研究集总数
            
            try:
                p_value = hypergeom.sf(k-1, M, n, N)
            except:
                p_value = 1.0
            
            # 获取term信息
            term_info = self._get_go_term_info(term_id)
            
            results.append(EnrichmentResult(
                term_id=term_id,
                term_name=term_info.get('name', term_id),
                category=term_info.get('category', 'Unknown'),
                gene_count=k,
                total_genes=N,
                p_value=p_value,
                gene_ids=counts['genes']
            ))
        
        return results
    
    def _kegg_enrichment(
        self,
        gene_set: Set[str],
        bg_set: Set[str]
    ) -> List[EnrichmentResult]:
        """KEGG富集分析"""
        # 类似GO富集分析
        pathway_counts = defaultdict(lambda: {'study': 0, 'population': 0, 'genes': []})
        
        for gene_id in gene_set:
            if gene_id in self._kegg_annotations:
                for pathway in self._kegg_annotations[gene_id]:
                    pathway_id = pathway.get('id')
                    if pathway_id:
                        pathway_counts[pathway_id]['study'] += 1
                        pathway_counts[pathway_id]['genes'].append(gene_id)
        
        for gene_id in bg_set:
            if gene_id in self._kegg_annotations:
                for pathway in self._kegg_annotations[gene_id]:
                    pathway_id = pathway.get('id')
                    if pathway_id:
                        pathway_counts[pathway_id]['population'] += 1
        
        results = []
        study_total = len(gene_set)
        pop_total = len(bg_set)
        
        from scipy.stats import hypergeom
        
        for pathway_id, counts in pathway_counts.items():
            if counts['study'] < 2:
                continue
            
            k = counts['study']
            M = pop_total
            n = counts['population']
            N = study_total
            
            try:
                p_value = hypergeom.sf(k-1, M, n, N)
            except:
                p_value = 1.0
            
            pathway_info = self._get_kegg_pathway_info(pathway_id)
            
            results.append(EnrichmentResult(
                term_id=pathway_id,
                term_name=pathway_info.get('name', pathway_id),
                category='KEGG',
                gene_count=k,
                total_genes=N,
                p_value=p_value,
                gene_ids=counts['genes']
            ))
        
        return results
    
    def _get_go_term_info(self, term_id: str) -> Dict[str, str]:
        """获取GO term信息"""
        # 简化的GO term信息
        # 实际应用中应该从OBO文件或数据库加载
        return {
            'name': term_id,
            'category': 'Unknown'
        }
    
    def _get_kegg_pathway_info(self, pathway_id: str) -> Dict[str, str]:
        """获取KEGG通路信息"""
        return {
            'name': pathway_id,
            'category': 'KEGG'
        }
    
    def get_go_summary(self, gene_list: List[str]) -> Dict[str, Any]:
        """获取基因列表的GO摘要"""
        category_counts = defaultdict(int)
        term_counts = defaultdict(int)
        
        for gene_id in gene_list:
            if gene_id in self._go_annotations:
                for term in self._go_annotations[gene_id]:
                    category = term.get('category', 'Unknown')
                    term_id = term.get('id', 'Unknown')
                    category_counts[category] += 1
                    term_counts[term_id] += 1
        
        return {
            'total_go_terms': sum(category_counts.values()),
            'category_distribution': dict(category_counts),
            'top_terms': sorted(
                term_counts.items(),
                key=lambda x: x[1],
                reverse=True
            )[:10]
        }
    
    def add_annotation(
        self,
        gene_id: str,
        annotation_type: str,
        annotation_data: Dict[str, Any]
    ):
        """添加注释数据"""
        if annotation_type == "go":
            if gene_id not in self._go_annotations:
                self._go_annotations[gene_id] = []
            self._go_annotations[gene_id].append(annotation_data)
        
        elif annotation_type == "kegg":
            if gene_id not in self._kegg_annotations:
                self._kegg_annotations[gene_id] = []
            self._kegg_annotations[gene_id].append(annotation_data)
        
        elif annotation_type == "description":
            self._gene_descriptions[gene_id] = annotation_data.get('description', '')
    
    def set_background_genes(self, gene_list: List[str]):
        """设置背景基因集"""
        self._background_genes = set(gene_list)
