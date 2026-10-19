#!/usr/bin/env python3
"""
GFF3 注释文件解析模块
用于加载和查询基因组注释信息
"""

import re
from typing import Dict, List, Optional, Tuple
from collections import defaultdict
import bisect


class GFF3Annotation:
    """GFF3 注释文件解析和查询"""
    
    def __init__(self, gff3_file: str):
        """
        初始化并加载 GFF3 文件
        
        Args:
            gff3_file: GFF3 文件路径
        """
        self.gff3_file = gff3_file
        self.genes = {}           # gene_id -> gene_info
        self.gene_names = {}      # gene_name (大写) -> [gene_id, ...]
        self.gene_by_chr = {}     # chr -> [(start, end, gene_id), ...]
        self.gene_positions = {}  # chr -> sorted list of (start, gene_id)
        
        self.load_gff3(gff3_file)
    
    def _parse_attributes(self, attr_str: str) -> Dict[str, str]:
        """解析 GFF3 属性列"""
        attrs = {}
        for part in attr_str.split(';'):
            if '=' in part:
                key, value = part.split('=', 1)
                # URL 解码
                value = value.replace('%3B', ';').replace('%2C', ',').replace('%3D', '=').replace('%26', '&')
                attrs[key] = value
        return attrs
    
    def load_gff3(self, gff3_file: str):
        """加载 GFF3 文件"""
        print(f"正在加载 GFF3 注释文件: {gff3_file}")
        
        gene_count = 0
        
        with open(gff3_file, 'r', encoding='utf-8') as f:
            for line in f:
                if line.startswith('#'):
                    continue
                
                parts = line.strip().split('\t')
                if len(parts) < 9:
                    continue
                
                chrom, source, feature_type, start, end, score, strand, phase, attributes = parts
                
                # 只处理 gene 类型
                if feature_type != 'gene':
                    continue
                
                attrs = self._parse_attributes(attributes)
                
                # 提取基因信息
                gene_id_raw = attrs.get('ID', '')
                gene_id = gene_id_raw.replace('gene:', '')  # 移除前缀
                
                if not gene_id:
                    continue
                
                gene_info = {
                    'gene_id': gene_id,
                    'chromosome': chrom,
                    'start': int(start),
                    'end': int(end),
                    'strand': strand,
                    'source': source,
                    'name': attrs.get('Name', ''),
                    'biotype': attrs.get('biotype', ''),
                    'description': attrs.get('description', ''),
                    'logic_name': attrs.get('logic_name', ''),
                }
                
                # 存储基因信息
                self.genes[gene_id] = gene_info
                
                # 建立名称索引（大写用于不区分大小写搜索）
                gene_name = gene_info['name'].upper()
                if gene_name:
                    if gene_name not in self.gene_names:
                        self.gene_names[gene_name] = []
                    self.gene_names[gene_name].append(gene_id)
                
                # 建立染色体位置索引
                if chrom not in self.gene_by_chr:
                    self.gene_by_chr[chrom] = []
                self.gene_by_chr[chrom].append((int(start), int(end), gene_id))
                
                gene_count += 1
        
        # 对每个染色体的基因列表按起始位置排序
        for chrom in self.gene_by_chr:
            self.gene_by_chr[chrom].sort(key=lambda x: x[0])
            # 创建用于快速查找的位置列表
            self.gene_positions[chrom] = [(g[0], g[2]) for g in self.gene_by_chr[chrom]]
        
        print(f"✓ 加载完成: {gene_count} 个基因")
    
    def search_gene(self, query: str, exact_match: bool = False, limit: int = 50) -> List[Dict]:
        """
        按基因名或 ID 搜索
        
        Args:
            query: 搜索关键词（基因名或 Ensembl ID）
            exact_match: 是否精确匹配
            limit: 最大返回数量
        
        Returns:
            匹配的基因列表
        """
        results = []
        query_upper = query.upper()
        
        # 1. 先尝试精确匹配基因 ID
        if query in self.genes:
            results.append(self.genes[query])
        
        # 2. 尝试精确匹配基因名
        if query_upper in self.gene_names:
            for gene_id in self.gene_names[query_upper]:
                if gene_id not in [r['gene_id'] for r in results]:
                    results.append(self.genes[gene_id])
        
        # 3. 如果不是精确匹配模式，进行模糊搜索
        if not exact_match and len(results) < limit:
            # 搜索基因 ID 包含关键词
            for gene_id, info in self.genes.items():
                if len(results) >= limit:
                    break
                if gene_id in [r['gene_id'] for r in results]:
                    continue
                if query_upper in gene_id.upper():
                    results.append(info)
            
            # 搜索基因名包含关键词
            for name, gene_ids in self.gene_names.items():
                if len(results) >= limit:
                    break
                if query_upper in name:
                    for gene_id in gene_ids:
                        if gene_id not in [r['gene_id'] for r in results]:
                            results.append(self.genes[gene_id])
                            if len(results) >= limit:
                                break
            
            # 搜索描述包含关键词
            for gene_id, info in self.genes.items():
                if len(results) >= limit:
                    break
                if gene_id in [r['gene_id'] for r in results]:
                    continue
                if info['description'] and query_upper in info['description'].upper():
                    results.append(info)
        
        return results[:limit]
    
    def get_genes_in_region(
        self, 
        chromosome: str, 
        start: int, 
        end: int,
        limit: int = 100
    ) -> List[Dict]:
        """
        获取区域内的基因
        
        Args:
            chromosome: 染色体
            start: 起始位置
            end: 终止位置
            limit: 最大返回数量
        
        Returns:
            区域内的基因列表
        """
        # 标准化染色体名
        chrom = str(chromosome).replace('chr', '').replace('Chr', '')
        
        if chrom not in self.gene_by_chr:
            return []
        
        results = []
        for gene_start, gene_end, gene_id in self.gene_by_chr[chrom]:
            # 检查是否与查询区域重叠
            if gene_end >= start and gene_start <= end:
                gene_info = self.genes[gene_id].copy()
                
                # 计算相对位置关系
                if gene_start >= start and gene_end <= end:
                    gene_info['relation'] = 'within'  # 完全在区域内
                elif gene_start < start and gene_end > end:
                    gene_info['relation'] = 'contains'  # 基因包含整个区域
                elif gene_start < start:
                    gene_info['relation'] = 'overlap_left'  # 左侧重叠
                else:
                    gene_info['relation'] = 'overlap_right'  # 右侧重叠
                
                results.append(gene_info)
                
                if len(results) >= limit:
                    break
            
            # 如果已经过了查询区域，停止搜索
            if gene_start > end:
                break
        
        return results
    
    def get_nearby_genes(
        self, 
        chromosome: str, 
        position: int, 
        upstream: int = 10000, 
        downstream: int = 10000,
        limit: int = 50
    ) -> Dict:
        """
        获取某位置附近的基因
        
        Args:
            chromosome: 染色体
            position: 位置
            upstream: 上游距离（bp）
            downstream: 下游距离（bp）
            limit: 最大返回数量
        
        Returns:
            附近基因信息
        """
        start = max(1, position - upstream)
        end = position + downstream
        
        genes = self.get_genes_in_region(chromosome, start, end, limit)
        
        # 计算每个基因与查询位置的距离
        for gene in genes:
            gene_start = gene['start']
            gene_end = gene['end']
            
            if gene_start <= position <= gene_end:
                gene['distance'] = 0
                gene['position_relation'] = 'inside'
            elif position < gene_start:
                gene['distance'] = gene_start - position
                gene['position_relation'] = 'downstream'
            else:
                gene['distance'] = position - gene_end
                gene['position_relation'] = 'upstream'
        
        # 按距离排序
        genes.sort(key=lambda x: x['distance'])
        
        return {
            'query_position': position,
            'query_region': f"{chromosome}:{start}-{end}",
            'genes_found': len(genes),
            'genes': genes
        }
    
    def annotate_position(self, chromosome: str, position: int) -> Dict:
        """
        注释某个位置
        
        Args:
            chromosome: 染色体
            position: 位置
        
        Returns:
            位置注释信息
        """
        chrom = str(chromosome).replace('chr', '').replace('Chr', '')
        
        result = {
            'chromosome': chrom,
            'position': position,
            'in_gene': False,
            'genes_at_position': [],
            'nearest_gene': None,
            'nearest_distance': None
        }
        
        if chrom not in self.gene_by_chr:
            return result
        
        # 查找包含该位置的基因
        for gene_start, gene_end, gene_id in self.gene_by_chr[chrom]:
            if gene_start <= position <= gene_end:
                result['in_gene'] = True
                gene_info = self.genes[gene_id].copy()
                
                # 计算在基因中的相对位置
                gene_length = gene_end - gene_start + 1
                rel_pos = position - gene_start
                gene_info['relative_position'] = f"{rel_pos}/{gene_length}"
                gene_info['relative_percent'] = round(rel_pos / gene_length * 100, 1)
                
                result['genes_at_position'].append(gene_info)
        
        # 如果不在任何基因内，找最近的基因
        if not result['in_gene']:
            nearest = self.get_nearby_genes(chrom, position, upstream=50000, downstream=50000, limit=1)
            if nearest['genes']:
                result['nearest_gene'] = nearest['genes'][0]
                result['nearest_distance'] = nearest['genes'][0]['distance']
        
        return result
    
    def get_gene_annotation(self, gene_id: str) -> Optional[Dict]:
        """
        获取基因详细注释
        
        Args:
            gene_id: 基因 ID
        
        Returns:
            基因注释信息
        """
        # 尝试直接查找
        if gene_id in self.genes:
            return self.genes[gene_id].copy()
        
        # 尝试添加前缀查找
        if not gene_id.startswith('ENSGALG'):
            prefixed_id = f"ENSGALG{gene_id}"
            if prefixed_id in self.genes:
                return self.genes[prefixed_id].copy()
        
        # 尝试按名称查找
        gene_upper = gene_id.upper()
        if gene_upper in self.gene_names:
            first_id = self.gene_names[gene_upper][0]
            return self.genes[first_id].copy()
        
        return None
    
    def get_statistics(self) -> Dict:
        """获取注释统计信息"""
        biotypes = defaultdict(int)
        chromosomes = set()
        
        for gene in self.genes.values():
            biotypes[gene['biotype']] += 1
            chromosomes.add(gene['chromosome'])
        
        return {
            'total_genes': len(self.genes),
            'named_genes': len(self.gene_names),
            'chromosomes': sorted(list(chromosomes)),
            'num_chromosomes': len(chromosomes),
            'biotypes': dict(sorted(biotypes.items(), key=lambda x: -x[1]))
        }


# 测试代码
if __name__ == "__main__":
    import sys
    
    gff3_file = sys.argv[1] if len(sys.argv) > 1 else '../annotation/Gallus_gallus.bGalGal1.mat.broiler.GRCg7b.115.gff3'
    
    print("=" * 60)
    print("GFF3 注释模块测试")
    print("=" * 60)
    
    anno = GFF3Annotation(gff3_file)
    
    # 统计信息
    stats = anno.get_statistics()
    print(f"\n统计信息:")
    print(f"  总基因数: {stats['total_genes']}")
    print(f"  有名称的基因: {stats['named_genes']}")
    print(f"  染色体数: {stats['num_chromosomes']}")
    print(f"  基因类型: {list(stats['biotypes'].items())[:5]}")
    
    # 搜索基因
    print(f"\n搜索 BMP2:")
    results = anno.search_gene("BMP2")
    for g in results[:3]:
        print(f"  {g['gene_id']}: {g['name']} @ {g['chromosome']}:{g['start']}-{g['end']}")
    
    # 区域查询
    print(f"\n查询 1:50000-150000 区域的基因:")
    genes = anno.get_genes_in_region("1", 50000, 150000)
    for g in genes[:5]:
        print(f"  {g['gene_id']}: {g.get('name', '-')} @ {g['start']}-{g['end']}")
    
    # 位置注释
    print(f"\n注释位置 1:100000:")
    pos_anno = anno.annotate_position("1", 100000)
    print(f"  在基因内: {pos_anno['in_gene']}")
    if pos_anno['nearest_gene']:
        print(f"  最近基因: {pos_anno['nearest_gene']['gene_id']} (距离 {pos_anno['nearest_distance']} bp)")
