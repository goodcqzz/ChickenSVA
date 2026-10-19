#!/usr/bin/env python3
"""
注释文件库模块 - 基因组注释数据管理
提供GFF3解析、基因查询和注释数据管理功能
"""

from .gff3_parser import GFF3Parser
from .gene_annotator import GeneAnnotator
from .annotation_index import AnnotationIndex
from .annotation_query import AnnotationQuery

__version__ = "2.0.0"
__all__ = [
    "GFF3Parser",
    "GeneAnnotator",
    "AnnotationIndex",
    "AnnotationQuery"
]
