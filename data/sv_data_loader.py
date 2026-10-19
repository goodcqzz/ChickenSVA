#!/usr/bin/env python3
"""
SV数据加载器 - 专门处理SV频率数据的加载和预处理
支持大文件分块加载、数据验证和格式转换
"""

import os
import gzip
import logging
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple, Union
from dataclasses import dataclass

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class SVRecord:
    """SV记录数据结构"""
    sv_id: str
    chromosome: str
    position: int
    end: int
    ref: str
    alt: str
    sv_type: str
    region: str
    gene: str
    mean_frequency: float
    breed_frequencies: Dict[str, float]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.sv_id,
            "chromosome": self.chromosome,
            "position": self.position,
            "end": self.end,
            "ref": self.ref,
            "alt": self.alt,
            "sv_type": self.sv_type,
            "region": self.region,
            "gene": self.gene,
            "mean_frequency": self.mean_frequency,
            "breed_frequencies": self.breed_frequencies
        }


class SVDataLoader:
    """
    SV数据加载器
    
    功能：
    1. 高效加载大型SV频率CSV文件
    2. 数据验证和质量控制
    3. 支持分块处理大文件
    4. 数据格式转换和标准化
    """
    
    CSV_ENCODINGS = ['utf-8', 'gbk', 'gb2312', 'gb18030', 'latin1']
    CHUNK_SIZE = 10000  # 分块读取大小
    
    # SV类型映射
    SV_TYPE_MAPPING = {
        'DEL': 'Deletion',
        'DUP': 'Duplication', 
        'INV': 'Inversion',
        'INS': 'Insertion',
        'BND': 'Translocation/Breakend',
        'CNV': 'Copy Number Variation'
    }
    
    def __init__(
        self,
        data_path: str,
        chunk_size: int = 10000,
        validate_data: bool = True
    ):
        self.data_path = Path(data_path)
        self.chunk_size = chunk_size
        self.validate_data = validate_data
        
        # 数据缓存
        self._dataframe: Optional[pd.DataFrame] = None
        self._breed_columns: List[str] = []
        self._metadata: Dict[str, Any] = {}
        
        logger.info(f"SV数据加载器初始化: {data_path}")
    
    def load(self, force_reload: bool = False) -> pd.DataFrame:
        """
        加载SV数据
        
        Args:
            force_reload: 强制重新加载
            
        Returns:
            加载的DataFrame
        """
        if self._dataframe is not None and not force_reload:
            return self._dataframe
        
        if not self.data_path.exists():
            raise FileNotFoundError(f"数据文件不存在: {self.data_path}")
        
        logger.info(f"开始加载SV数据: {self.data_path}")
        
        # 读取CSV
        df = self._read_csv_file()
        
        if df is None or df.empty:
            raise ValueError(f"无法加载数据文件或文件为空: {self.data_path}")
        
        # 数据预处理
        df = self._preprocess_data(df)
        
        # 数据验证
        if self.validate_data:
            validation_result = self._validate_data(df)
            if not validation_result['valid']:
                logger.warning(f"数据验证警告: {validation_result['warnings']}")
        
        # 提取品种列
        self._breed_columns = self._extract_breed_columns(df)
        
        # 计算元数据
        self._calculate_metadata(df)
        
        self._dataframe = df
        
        logger.info(f"✓ SV数据加载完成: {len(df)} 条记录, {len(self._breed_columns)} 个品种")
        
        return df
    
    def _read_csv_file(self) -> Optional[pd.DataFrame]:
        """读取CSV文件（支持多种编码）"""
        for encoding in self.CSV_ENCODINGS:
            try:
                df = pd.read_csv(self.data_path, encoding=encoding)
                # 清理列名
                df.columns = [str(col).strip() for col in df.columns]
                logger.debug(f"使用编码 {encoding} 成功读取文件")
                return df
            except UnicodeDecodeError:
                continue
            except Exception as e:
                logger.debug(f"编码 {encoding} 读取失败: {e}")
                continue
        
        logger.error(f"无法使用任何编码读取文件: {self.data_path}")
        return None
    
    def _preprocess_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """数据预处理"""
        # 标准化列名
        column_mapping = {
            'ID': 'ID',
            'Chr': 'Chr',
            'POS': 'POS',
            'End': 'End',
            'REF': 'REF',
            'ALT': 'ALT',
            'SV_Type': 'SV_Type',
            'Region': 'Region',
            'Gene': 'Gene',
            'Mean_fre': 'Mean_fre'
        }
        
        # 重命名列（如果存在）
        for old_name, new_name in column_mapping.items():
            if old_name in df.columns:
                df = df.rename(columns={old_name: new_name})
        
        # 数据类型转换
        if 'POS' in df.columns:
            df['POS'] = pd.to_numeric(df['POS'], errors='coerce')
        if 'End' in df.columns:
            df['End'] = pd.to_numeric(df['End'], errors='coerce')
        if 'Mean_fre' in df.columns:
            df['Mean_fre'] = pd.to_numeric(df['Mean_fre'], errors='coerce')
        
        # 标准化SV类型
        if 'SV_Type' in df.columns:
            df['SV_Type'] = df['SV_Type'].str.upper().str.strip()
        
        # 标准化染色体名称
        if 'Chr' in df.columns:
            df['Chr'] = df['Chr'].astype(str).str.replace('chr', '', case=False)
        
        return df
    
    def _validate_data(self, df: pd.DataFrame) -> Dict[str, Any]:
        """数据验证"""
        warnings = []
        
        # 检查必需列
        required_cols = ['ID', 'Chr', 'POS']
        for col in required_cols:
            if col not in df.columns:
                warnings.append(f"缺少必需列: {col}")
        
        # 检查空值
        if 'POS' in df.columns:
            null_count = df['POS'].isna().sum()
            if null_count > 0:
                warnings.append(f"位置列包含 {null_count} 个空值")
        
        # 检查SV类型
        if 'SV_Type' in df.columns:
            valid_types = set(self.SV_TYPE_MAPPING.keys())
            invalid_types = set(df['SV_Type'].dropna().unique()) - valid_types
            if invalid_types:
                warnings.append(f"发现未知SV类型: {invalid_types}")
        
        # 检查频率范围
        breed_cols = self._extract_breed_columns(df)
        for col in breed_cols[:5]:  # 只检查前5个品种列
            if col in df.columns:
                invalid_freq = ((df[col] < 0) | (df[col] > 1)).sum()
                if invalid_freq > 0:
                    warnings.append(f"品种 {col} 包含 {invalid_freq} 个无效频率值")
        
        return {
            'valid': len(warnings) == 0,
            'warnings': warnings
        }
    
    def _extract_breed_columns(self, df: pd.DataFrame) -> List[str]:
        """提取品种列"""
        # 标准格式：Mean_fre 之后的列为品种频率
        if 'Mean_fre' in df.columns:
            idx = df.columns.get_loc('Mean_fre')
            return list(df.columns[idx + 1:])
        
        # 备选：尝试识别频率列（数值在0-1之间）
        breed_cols = []
        for col in df.columns:
            if col in ['ID', 'Chr', 'POS', 'End', 'REF', 'ALT', 'SV_Type', 'Region', 'Gene']:
                continue
            
            try:
                numeric_col = pd.to_numeric(df[col], errors='coerce')
                if numeric_col.dropna().between(0, 1).all():
                    breed_cols.append(col)
            except:
                pass
        
        return breed_cols
    
    def _calculate_metadata(self, df: pd.DataFrame):
        """计算数据元信息"""
        self._metadata = {
            'total_records': len(df),
            'file_size_mb': self.data_path.stat().st_size / (1024 * 1024),
            'chromosomes': df['Chr'].unique().tolist() if 'Chr' in df.columns else [],
            'sv_types': df['SV_Type'].unique().tolist() if 'SV_Type' in df.columns else [],
            'genes': df['Gene'].nunique() if 'Gene' in df.columns else 0,
            'breed_count': len(self._breed_columns),
            'mean_frequency_stats': {
                'min': df['Mean_fre'].min() if 'Mean_fre' in df.columns else None,
                'max': df['Mean_fre'].max() if 'Mean_fre' in df.columns else None,
                'mean': df['Mean_fre'].mean() if 'Mean_fre' in df.columns else None
            }
        }
    
    def iter_records(self) -> Iterator[SVRecord]:
        """迭代所有SV记录"""
        if self._dataframe is None:
            self.load()
        
        for _, row in self._dataframe.iterrows():
            yield self._row_to_record(row)
    
    def _row_to_record(self, row: pd.Series) -> SVRecord:
        """将DataFrame行转换为SVRecord"""
        breed_freqs = {}
        for col in self._breed_columns:
            if col in row and pd.notna(row[col]):
                try:
                    breed_freqs[col] = float(row[col])
                except (ValueError, TypeError):
                    pass
        
        return SVRecord(
            sv_id=str(row.get('ID', '')),
            chromosome=str(row.get('Chr', '')),
            position=int(row.get('POS', 0)) if pd.notna(row.get('POS')) else 0,
            end=int(row.get('End', 0)) if pd.notna(row.get('End')) else 0,
            ref=str(row.get('REF', '')),
            alt=str(row.get('ALT', '')),
            sv_type=str(row.get('SV_Type', '')),
            region=str(row.get('Region', '')),
            gene=str(row.get('Gene', '')),
            mean_frequency=float(row.get('Mean_fre', 0)) if pd.notna(row.get('Mean_fre')) else 0,
            breed_frequencies=breed_freqs
        )
    
    def get_metadata(self) -> Dict[str, Any]:
        """获取数据元信息"""
        return self._metadata.copy()
    
    def get_breed_columns(self) -> List[str]:
        """获取品种列列表"""
        if not self._breed_columns and self._dataframe is not None:
            self._breed_columns = self._extract_breed_columns(self._dataframe)
        return self._breed_columns.copy()
    
    def query_by_chromosome(self, chromosome: str) -> pd.DataFrame:
        """按染色体查询"""
        if self._dataframe is None:
            self.load()
        
        chr_num = chromosome.replace('chr', '')
        return self._dataframe[self._dataframe['Chr'] == chr_num]
    
    def query_by_gene(self, gene_name: str) -> pd.DataFrame:
        """按基因名查询"""
        if self._dataframe is None:
            self.load()
        
        if 'Gene' not in self._dataframe.columns:
            return pd.DataFrame()
        
        mask = self._dataframe['Gene'].str.contains(gene_name, case=False, na=False)
        return self._dataframe[mask]
    
    def query_by_region(
        self,
        chromosome: str,
        start: int,
        end: int
    ) -> pd.DataFrame:
        """按基因组区域查询"""
        if self._dataframe is None:
            self.load()
        
        chr_num = chromosome.replace('chr', '')
        
        mask = (
            (self._dataframe['Chr'] == chr_num) &
            (self._dataframe['POS'] >= start) &
            (self._dataframe['POS'] <= end)
        )
        
        return self._dataframe[mask]
    
    def get_frequency_distribution(self) -> Dict[str, Any]:
        """获取频率分布统计"""
        if self._dataframe is None:
            self.load()
        
        if 'Mean_fre' not in self._dataframe.columns:
            return {}
        
        freqs = self._dataframe['Mean_fre'].dropna()
        
        return {
            'count': len(freqs),
            'mean': float(freqs.mean()),
            'std': float(freqs.std()),
            'min': float(freqs.min()),
            'max': float(freqs.max()),
            'percentiles': {
                '25%': float(freqs.quantile(0.25)),
                '50%': float(freqs.quantile(0.50)),
                '75%': float(freqs.quantile(0.75))
            }
        }
