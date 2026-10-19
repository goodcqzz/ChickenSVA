#!/usr/bin/env python3
"""
GFF3解析器 - 高效解析GFF3格式的基因组注释文件
支持大文件分块读取、索引构建和快速查询
"""

import gzip
import logging
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple, Set
from dataclasses import dataclass, field
from collections import defaultdict

logger = logging.getLogger(__name__)


@dataclass
class GFF3Record:
    """GFF3记录"""
    seqid: str  # 染色体
    source: str  # 来源
    type: str  # 特征类型
    start: int  # 起始位置
    end: int  # 结束位置
    score: Optional[float]  # 得分
    strand: str  # 链
    phase: Optional[str]  # 相位
    attributes: Dict[str, str]  # 属性
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "seqid": self.seqid,
            "source": self.source,
            "type": self.type,
            "start": self.start,
            "end": self.end,
            "score": self.score,
            "strand": self.strand,
            "phase": self.phase,
            "attributes": self.attributes
        }
    
    @property
    def gene_id(self) -> Optional[str]:
        """获取基因ID"""
        return self.attributes.get('ID') or self.attributes.get('gene_id')
    
    @property
    def gene_name(self) -> Optional[str]:
        """获取基因名称"""
        return self.attributes.get('Name') or self.attributes.get('gene_name')
    
    @property
    def length(self) -> int:
        """获取特征长度"""
        return self.end - self.start + 1


@dataclass
class GeneModel:
    """基因模型"""
    gene_id: str
    gene_name: Optional[str]
    chromosome: str
    start: int
    end: int
    strand: str
    transcripts: List[Dict[str, Any]] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "gene_id": self.gene_id,
            "gene_name": self.gene_name,
            "chromosome": self.chromosome,
            "start": self.start,
            "end": self.end,
            "strand": self.strand,
            "length": self.end - self.start + 1,
            "transcript_count": len(self.transcripts)
        }


class GFF3Parser:
    """
    GFF3解析器
    
    功能：
    1. 高效解析大型GFF3文件
    2. 支持gzip压缩文件
    3. 构建索引加速查询
    4. 提取基因模型信息
    """
    
    # 常用特征类型
    FEATURE_TYPES = {
        'gene', 'transcript', 'mRNA', 'exon', 'CDS', 'UTR', 'five_prime_UTR',
        'three_prime_UTR', 'intron', 'pseudogene', 'ncRNA', 'tRNA', 'rRNA'
    }
    
    def __init__(
        self,
        gff3_path: str,
        build_index: bool = True,
        cache_records: bool = False
    ):
        self.gff3_path = Path(gff3_path)
        self.cache_records = cache_records
        
        # 数据存储
        self._records: List[GFF3Record] = [] if cache_records else None
        self._gene_index: Dict[str, GeneModel] = {}
        self._chromosome_index: Dict[str, List[GFF3Record]] = defaultdict(list)
        self._type_index: Dict[str, List[GFF3Record]] = defaultdict(list)
        
        # 统计信息
        self._stats: Dict[str, Any] = {}
        
        # 验证文件
        if not self.gff3_path.exists():
            raise FileNotFoundError(f"GFF3文件不存在: {gff3_path}")
        
        # 构建索引
        if build_index:
            self._build_index()
    
    def _open_file(self):
        """打开文件（支持gzip）"""
        if str(self.gff3_path).endswith('.gz'):
            return gzip.open(self.gff3_path, 'rt', encoding='utf-8')
        else:
            return open(self.gff3_path, 'r', encoding='utf-8')
    
    def _parse_line(self, line: str) -> Optional[GFF3Record]:
        """解析单行GFF3记录"""
        line = line.strip()
        
        # 跳过注释和空行
        if not line or line.startswith('#'):
            return None
        
        parts = line.split('\t')
        if len(parts) != 9:
            return None
        
        try:
            # 解析位置
            start = int(parts[3])
            end = int(parts[4])
            
            # 解析得分
            score = None
            if parts[5] != '.':
                score = float(parts[5])
            
            # 解析相位
            phase = None
            if parts[7] != '.':
                phase = parts[7]
            
            # 解析属性
            attributes = self._parse_attributes(parts[8])
            
            return GFF3Record(
                seqid=parts[0],
                source=parts[1],
                type=parts[2],
                start=start,
                end=end,
                score=score,
                strand=parts[6],
                phase=phase,
                attributes=attributes
            )
            
        except Exception as e:
            logger.debug(f"解析行失败: {line[:50]}... - {e}")
            return None
    
    def _parse_attributes(self, attr_string: str) -> Dict[str, str]:
        """解析属性字段"""
        attributes = {}
        
        for attr in attr_string.split(';'):
            attr = attr.strip()
            if not attr:
                continue
            
            if '=' in attr:
                key, value = attr.split('=', 1)
                attributes[key.strip()] = value.strip()
            elif ' ' in attr:
                # 旧格式：key value
                parts = attr.split(None, 1)
                if len(parts) == 2:
                    attributes[parts[0]] = parts[1].strip('"')
        
        return attributes
    
    def _build_index(self):
        """构建索引"""
        logger.info(f"开始构建GFF3索引: {self.gff3_path}")
        
        record_count = 0
        gene_count = 0
        type_counts = defaultdict(int)
        
        with self._open_file() as f:
            for line in f:
                record = self._parse_line(line)
                if not record:
                    continue
                
                record_count += 1
                type_counts[record.type] += 1
                
                # 缓存记录
                if self.cache_records:
                    self._records.append(record)
                
                # 染色体索引
                self._chromosome_index[record.seqid].append(record)
                
                # 类型索引
                self._type_index[record.type].append(record)
                
                # 基因索引
                if record.type == 'gene':
                    gene_id = record.gene_id
                    if gene_id:
                        self._gene_index[gene_id] = GeneModel(
                            gene_id=gene_id,
                            gene_name=record.gene_name,
                            chromosome=record.seqid,
                            start=record.start,
                            end=record.end,
                            strand=record.strand
                        )
                        gene_count += 1
        
        # 构建基因-转录本关系
        self._build_gene_transcript_relationships()
        
        self._stats = {
            'total_records': record_count,
            'gene_count': gene_count,
            'type_counts': dict(type_counts),
            'chromosomes': list(self._chromosome_index.keys()),
            'indexed': True
        }
        
        logger.info(f"✓ GFF3索引构建完成: {record_count} 条记录, {gene_count} 个基因")
    
    def _build_gene_transcript_relationships(self):
        """构建基因和转录本的关系"""
        # 查找转录本记录
        transcript_types = {'mRNA', 'transcript', 'ncRNA', 'tRNA', 'rRNA'}
        
        for record_type in transcript_types:
            for record in self._type_index.get(record_type, []):
                # 查找Parent属性
                parent_id = record.attributes.get('Parent')
                if parent_id and parent_id in self._gene_index:
                    gene = self._gene_index[parent_id]
                    gene.transcripts.append({
                        'id': record.gene_id,
                        'type': record.type,
                        'start': record.start,
                        'end': record.end
                    })
    
    def get_gene(self, gene_id: str) -> Optional[GeneModel]:
        """获取基因信息"""
        return self._gene_index.get(gene_id)
    
    def find_gene_by_name(self, gene_name: str) -> Optional[GeneModel]:
        """按基因名称查找"""
        for gene in self._gene_index.values():
            if gene.gene_name and gene.gene_name.lower() == gene_name.lower():
                return gene
        return None
    
    def query_region(
        self,
        chromosome: str,
        start: int,
        end: int,
        feature_types: Optional[List[str]] = None
    ) -> List[GFF3Record]:
        """
        按区域查询特征
        
        Args:
            chromosome: 染色体
            start: 起始位置
            end: 结束位置
            feature_types: 特征类型过滤
            
        Returns:
            匹配的记录列表
        """
        results = []
        
        # 标准化染色体名称
        chr_key = chromosome.replace('chr', '')
        if chr_key not in self._chromosome_index:
            chr_key = chromosome
        
        records = self._chromosome_index.get(chr_key, [])
        
        for record in records:
            # 检查重叠
            if record.end < start or record.start > end:
                continue
            
            # 类型过滤
            if feature_types and record.type not in feature_types:
                continue
            
            results.append(record)
        
        return results
    
    def get_genes_in_region(
        self,
        chromosome: str,
        start: int,
        end: int
    ) -> List[GeneModel]:
        """获取区域内的所有基因"""
        records = self.query_region(chromosome, start, end, ['gene'])
        
        genes = []
        for record in records:
            gene_id = record.gene_id
            if gene_id and gene_id in self._gene_index:
                genes.append(self._gene_index[gene_id])
        
        return genes
    
    def get_gene_structure(self, gene_id: str) -> Optional[Dict[str, Any]]:
        """获取基因完整结构"""
        gene = self._gene_index.get(gene_id)
        if not gene:
            return None
        
        # 获取所有相关特征
        records = self.query_region(
            gene.chromosome,
            gene.start,
            gene.end
        )
        
        # 组织特征
        structure = {
            'gene': gene.to_dict(),
            'transcripts': [],
            'exons': [],
            'cds': [],
            'other_features': []
        }
        
        for record in records:
            if record.type == 'gene':
                continue
            
            record_dict = record.to_dict()
            
            if record.type in ('mRNA', 'transcript'):
                structure['transcripts'].append(record_dict)
            elif record.type == 'exon':
                structure['exons'].append(record_dict)
            elif record.type == 'CDS':
                structure['cds'].append(record_dict)
            else:
                structure['other_features'].append(record_dict)
        
        return structure
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        return self._stats.copy()
    
    def get_feature_types(self) -> List[str]:
        """获取所有特征类型"""
        return list(self._type_index.keys())
    
    def get_chromosomes(self) -> List[str]:
        """获取所有染色体"""
        return list(self._chromosome_index.keys())
    
    def iter_genes(self) -> Iterator[GeneModel]:
        """迭代所有基因"""
        yield from self._gene_index.values()
    
    def search_by_attribute(
        self,
        key: str,
        value: str,
        exact: bool = True
    ) -> List[GFF3Record]:
        """
        按属性搜索
        
        Args:
            key: 属性名
            value: 属性值
            exact: 是否精确匹配
            
        Returns:
            匹配的记录
        """
        results = []
        
        search_records = self._records if self.cache_records else self._iter_records()
        
        for record in search_records:
            attr_value = record.attributes.get(key)
            if attr_value:
                if exact and attr_value == value:
                    results.append(record)
                elif not exact and value.lower() in attr_value.lower():
                    results.append(record)
        
        return results
    
    def _iter_records(self) -> Iterator[GFF3Record]:
        """迭代所有记录（不缓存时使用）"""
        with self._open_file() as f:
            for line in f:
                record = self._parse_line(line)
                if record:
                    yield record


# 向后兼容
GFF3Annotation = GFF3Parser
