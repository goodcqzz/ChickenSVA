#!/usr/bin/env python3
"""
表型数据管理器 - 处理鸡种表型数据的管理和查询
支持表型标准化、品种匹配和关联分析准备
"""

import re
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Set
from dataclasses import dataclass, field

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class BreedPhenotype:
    """品种表型数据结构"""
    breed: str
    breed_normalized: str
    alias: Optional[str] = None
    sample_size: Optional[float] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    category: Optional[str] = None
    subcategory: Optional[str] = None
    numeric_traits: Dict[str, float] = field(default_factory=dict)
    categorical_traits: Dict[str, str] = field(default_factory=dict)
    match_keys: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "breed": self.breed,
            "alias": self.alias,
            "sample_size": self.sample_size,
            "location": {
                "latitude": self.latitude,
                "longitude": self.longitude
            } if self.latitude and self.longitude else None,
            "category": self.category,
            "subcategory": self.subcategory,
            "numeric_traits": self.numeric_traits,
            "categorical_traits": self.categorical_traits
        }


class PhenotypeManager:
    """
    表型数据管理器
    
    功能：
    1. 加载和管理鸡种表型数据
    2. 品种名称标准化和匹配
    3. 表型数据查询和筛选
    4. 为关联分析准备数据
    """
    
    CSV_ENCODINGS = ['utf-8', 'gbk', 'gb2312', 'gb18030', 'latin1']
    
    # 元数据性状
    METADATA_TRAITS = {
        '标签', '数量', '纬度', '经度', '大分类', '细分', '驯化程度分类', '用途分类',
        'alias', 'sample_size', 'latitude', 'longitude', 
        'category', 'subcategory'
    }
    
    def __init__(self, phenotype_path: str):
        self.phenotype_path = Path(phenotype_path)
        
        # 数据存储
        self._raw_data: Optional[pd.DataFrame] = None
        self._breed_data: Dict[str, BreedPhenotype] = {}
        self._breed_lookup: Dict[str, str] = {}  # 标准化名称 -> 原始名称
        
        # 性状分类
        self._all_traits: List[str] = []
        self._numeric_traits: List[str] = []
        self._categorical_traits: List[str] = []
        
        # 初始化
        self._load_data()
    
    def _load_data(self):
        """加载表型数据"""
        if not self.phenotype_path.exists():
            logger.warning(f"表型文件不存在: {self.phenotype_path}")
            return
        
        try:
            df = self._read_csv_with_encoding(self.phenotype_path)
            if df is None or df.empty:
                logger.error("表型文件为空")
                return
            
            self._raw_data = df
            self._process_phenotype_data(df)
            
            logger.info(f"✓ 表型数据加载完成: {len(self._breed_data)} 个品种, "
                       f"{len(self._all_traits)} 个性状")
            
        except Exception as e:
            logger.error(f"加载表型数据失败: {e}")
    
    def _read_csv_with_encoding(self, file_path: Path) -> Optional[pd.DataFrame]:
        """尝试多种编码读取CSV"""
        for encoding in self.CSV_ENCODINGS:
            try:
                df = pd.read_csv(file_path, encoding=encoding)
                df.columns = [str(col).strip() for col in df.columns]
                return df
            except UnicodeDecodeError:
                continue
            except Exception as e:
                logger.debug(f"编码 {encoding} 失败: {e}")
                continue
        return None
    
    def _process_phenotype_data(self, df: pd.DataFrame):
        """处理表型数据"""
        if len(df.columns) < 2:
            raise ValueError("表型数据至少需要2列")
        
        # 第一列为性状名称，其余为品种
        trait_col = df.columns[0]
        breed_columns = [str(col).strip() for col in df.columns[1:]]
        
        # 初始化品种数据结构
        for breed in breed_columns:
            self._breed_data[breed] = BreedPhenotype(
                breed=breed,
                breed_normalized=self._normalize_breed_name(breed)
            )
        
        # 处理每个性状
        for _, row in df.iterrows():
            trait_name = str(row[trait_col]).strip()
            if not trait_name or trait_name.lower() == 'nan':
                continue
            
            self._all_traits.append(trait_name)
            
            # 判断性状类型
            values = row.iloc[1:]
            is_numeric = self._is_numeric_trait(trait_name, values)
            
            if is_numeric:
                self._numeric_traits.append(trait_name)
            else:
                self._categorical_traits.append(trait_name)
            
            # 填充数据
            for breed, value in zip(breed_columns, values):
                self._fill_trait_data(breed, trait_name, value, is_numeric)
        
        # 去重
        self._all_traits = list(dict.fromkeys(self._all_traits))
        self._numeric_traits = list(dict.fromkeys(self._numeric_traits))
        self._categorical_traits = list(dict.fromkeys(self._categorical_traits))
        
        # 构建查找表
        self._build_lookup_tables()
    
    def _is_numeric_trait(self, trait_name: str, values: pd.Series) -> bool:
        """判断是否为数值性状"""
        # 已知数值元数据
        if trait_name in {'数量', '纬度', '经度', 'sample_size', 'latitude', 'longitude'}:
            return True
        
        # 已知分类元数据
        if trait_name in {'标签', '大分类', '细分', '驯化程度分类', '用途分类', 'alias', 'category', 'subcategory'}:
            return False
        
        # 自动判断：如果超过1/3可以转换为数字，则认为是数值性状
        numeric_values = pd.to_numeric(values, errors='coerce')
        return numeric_values.notna().sum() >= len(values) / 3
    
    def _fill_trait_data(self, breed: str, trait_name: str, value: Any, is_numeric: bool):
        """填充性状数据"""
        entry = self._breed_data[breed]
        
        # 元数据字段
        if trait_name == '标签':
            entry.alias = None if pd.isna(value) else str(value).strip()
        elif trait_name == '数量':
            entry.sample_size = None if pd.isna(value) else float(value)
        elif trait_name == '纬度':
            entry.latitude = None if pd.isna(value) else float(value)
        elif trait_name == '经度':
            entry.longitude = None if pd.isna(value) else float(value)
        elif trait_name in {'大分类', '驯化程度分类'}:
            entry.category = None if pd.isna(value) else str(value).strip()
        elif trait_name in {'细分', '用途分类'}:
            entry.subcategory = None if pd.isna(value) else str(value).strip()
        else:
            # 普通性状
            if is_numeric and not pd.isna(value):
                try:
                    entry.numeric_traits[trait_name] = float(value)
                except (ValueError, TypeError):
                    pass
            elif not is_numeric and not pd.isna(value):
                entry.categorical_traits[trait_name] = str(value).strip()
    
    def _build_lookup_tables(self):
        """构建查找表"""
        for breed, entry in self._breed_data.items():
            # 生成匹配键
            match_keys = self._generate_match_keys(breed, entry.alias)
            entry.match_keys = match_keys
            
            # 添加到查找表
            for key in match_keys:
                self._breed_lookup[key] = breed
    
    def _generate_match_keys(self, breed: str, alias: Optional[str]) -> List[str]:
        """生成品种匹配键"""
        keys = set()
        
        # 原始名称
        keys.add(breed)
        keys.add(self._normalize_breed_name(breed))
        
        # 别名
        if alias:
            keys.add(alias)
            keys.add(self._normalize_breed_name(alias))
        
        return list(keys)
    
    def _normalize_breed_name(self, name: str) -> str:
        """标准化品种名称"""
        if not name:
            return ""
        
        # 转小写
        normalized = name.lower().strip()
        
        # 移除特殊字符
        normalized = re.sub(r'[^\w\s]', '', normalized)
        
        # 移除多余空格
        normalized = re.sub(r'\s+', '', normalized)
        
        return normalized
    
    def find_breed(self, query: str, exact: bool = False) -> Optional[BreedPhenotype]:
        """
        查找品种
        
        Args:
            query: 查询名称
            exact: 是否精确匹配
            
        Returns:
            品种表型数据
        """
        query_normalized = self._normalize_breed_name(query)
        
        # 精确匹配
        if query_normalized in self._breed_lookup:
            breed_name = self._breed_lookup[query_normalized]
            return self._breed_data.get(breed_name)
        
        if exact:
            return None
        
        # 模糊匹配
        for key, breed_name in self._breed_lookup.items():
            if query_normalized in key or key in query_normalized:
                return self._breed_data.get(breed_name)
        
        return None
    
    def find_breeds(
        self,
        queries: List[str],
        exact: bool = False,
        max_results: int = 20
    ) -> List[BreedPhenotype]:
        """批量查找品种"""
        results = []
        seen = set()
        
        for query in queries:
            breed = self.find_breed(query, exact)
            if breed and breed.breed not in seen:
                results.append(breed)
                seen.add(breed.breed)
                
                if len(results) >= max_results:
                    break
        
        return results
    
    def get_breed_list(self) -> List[str]:
        """获取所有品种列表"""
        return list(self._breed_data.keys())
    
    def get_traits(self) -> Dict[str, List[str]]:
        """获取所有性状分类"""
        return {
            'all': self._all_traits,
            'numeric': self._numeric_traits,
            'categorical': self._categorical_traits
        }
    
    def get_trait_values(self, trait_name: str) -> Dict[str, Any]:
        """获取某个性状的所有品种值"""
        values = {}
        
        for breed, entry in self._breed_data.items():
            if trait_name in entry.numeric_traits:
                values[breed] = entry.numeric_traits[trait_name]
            elif trait_name in entry.categorical_traits:
                values[breed] = entry.categorical_traits[trait_name]
        
        return values
    
    def get_summary(self) -> Dict[str, Any]:
        """获取表型数据摘要"""
        return {
            'loaded': len(self._breed_data) > 0,
            'breed_count': len(self._breed_data),
            'trait_count': len(self._all_traits),
            'numeric_traits': len(self._numeric_traits),
            'categorical_traits': len(self._categorical_traits),
            'trait_examples': self._all_traits[:10],
            'covariates_available': ['驯化程度分类', '用途分类', '纬度', '经度']
        }
    
    def prepare_for_association(
        self,
        sv_breeds: List[str],
        trait_name: str
    ) -> Tuple[List[float], List[float], List[str]]:
        """
        为关联分析准备数据
        
        Args:
            sv_breeds: SV数据中的品种列表
            trait_name: 要分析的性状
            
        Returns:
            (sv_frequencies, trait_values, matched_breeds)
        """
        sv_freqs = []
        trait_vals = []
        matched = []
        
        for breed in sv_breeds:
            phenotype = self.find_breed(breed)
            if phenotype and trait_name in phenotype.numeric_traits:
                sv_freqs.append(1.0)  # 占位，实际应从SV数据获取
                trait_vals.append(phenotype.numeric_traits[trait_name])
                matched.append(breed)
        
        return sv_freqs, trait_vals, matched
