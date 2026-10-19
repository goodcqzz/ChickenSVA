#!/usr/bin/env python3
"""
鸡基因组 SV 数据库查询工具
提供 SV 查询、注释查询、表型标准化和品种层关联分析能力
"""

import math
import os
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

try:
    from scipy.stats import pearsonr, spearmanr
except ImportError:
    pearsonr = None
    spearmanr = None

try:
    from gff3_annotation import GFF3Annotation
except ImportError:
    GFF3Annotation = None


class ChickenSVTool:
    """鸡基因组 SV 数据库查询工具"""

    CSV_ENCODINGS = ['utf-8', 'gbk', 'gb2312', 'gb18030', 'latin1']
    PHENOTYPE_NUMERIC_METADATA = {'数量', '纬度', '经度'}
    PHENOTYPE_CATEGORICAL_METADATA = {'标签', '大分类', '细分', '驯化程度分类', '用途分类'}
    COVARIATE_ALIASES = {
        '大分类': 'category',
        '驯化程度分类': 'category',
        'category': 'category',
        'majorcategory': 'category',
        '细分': 'subcategory',
        '用途分类': 'subcategory',
        'subcategory': 'subcategory',
        'subtype': 'subcategory',
        '纬度': 'latitude',
        'latitude': 'latitude',
        'lat': 'latitude',
        '经度': 'longitude',
        'longitude': 'longitude',
        'lon': 'longitude',
        'lng': 'longitude',
        '数量': 'sample_size',
        'samplesize': 'sample_size',
        'sample_size': 'sample_size',
        '标签': 'alias',
        'label': 'alias',
        'alias': 'alias',
    }
    TASK_TOOL_WHITELIST = {'get_database_info', 'query_breed_profile', 'query_sv', 'query_annotation', 'analyze_breed_association', 'genome_wide_association_scan'}

    def __init__(
        self,
        data_path: str = '../data',
        database_name: Optional[str] = None,
        annotation_path: Optional[str] = None,
        phenotype_path: Optional[str] = None,
    ):
        self.data_path = data_path
        self.databases: Dict[str, pd.DataFrame] = {}
        self.database_names: List[str] = []
        self.current_database: Optional[str] = None
        self.df: Optional[pd.DataFrame] = None
        self.annotation = None

        self.phenotype_file: Optional[str] = None
        self.phenotype_raw: Optional[pd.DataFrame] = None
        self.phenotype_by_breed: Dict[str, Dict[str, Any]] = {}
        self.phenotype_breed_lookup: Dict[str, str] = {}
        self.phenotype_all_traits: List[str] = []
        self.phenotype_metadata_traits: List[str] = []
        self.phenotype_numeric_traits: List[str] = []
        self.phenotype_categorical_traits: List[str] = []
        self.phenotype_numeric_lookup: Dict[str, str] = {}
        self.phenotype_categorical_lookup: Dict[str, str] = {}

        if os.path.isfile(data_path):
            self._load_single_file(data_path)
        else:
            self._load_databases_from_folder(data_path, database_name)

        if annotation_path and GFF3Annotation and os.path.exists(annotation_path):
            try:
                self.annotation = GFF3Annotation(annotation_path)
                print(f"✓ 加载注释文件: {annotation_path}")
            except Exception as exc:
                print(f"⚠ 注释文件加载失败: {exc}")

        phenotype_file = phenotype_path or self._discover_phenotype_file(data_path)
        if phenotype_file and os.path.exists(phenotype_file):
            try:
                self._load_phenotype_data(phenotype_file)
                print(f"✓ 加载表型文件: {phenotype_file}")
            except Exception as exc:
                print(f"⚠ 表型文件加载失败: {exc}")

    def _read_csv_with_fallback(self, csv_file: str) -> Tuple[pd.DataFrame, str]:
        last_error = None
        for encoding in self.CSV_ENCODINGS:
            try:
                return pd.read_csv(csv_file, low_memory=False, encoding=encoding), encoding
            except UnicodeDecodeError as exc:
                last_error = exc
        raise ValueError(f"无法识别文件编码: {csv_file}, error={last_error}")

    def _load_single_file(self, csv_file: str):
        df, _ = self._read_csv_with_fallback(csv_file)
        db_name = os.path.basename(csv_file)
        self.databases[db_name] = df
        self.database_names = [db_name]
        self.current_database = db_name
        self.df = df
        print(f"✓ 加载数据库: {db_name} ({len(df)} 条记录)")

    def _load_databases_from_folder(self, folder_path: str, database_name: Optional[str] = None):
        folder = Path(folder_path)
        if not folder.exists():
            raise FileNotFoundError(f"数据文件夹不存在: {folder_path}")

        csv_files = list(folder.glob('*.csv'))
        if not csv_files:
            raise ValueError(f"文件夹中没有CSV文件: {folder_path}")

        for csv_file in csv_files:
            if '表型' in csv_file.name:
                continue
            try:
                df, encoding = self._read_csv_with_fallback(str(csv_file))
                db_name = csv_file.name
                self.databases[db_name] = df
                self.database_names.append(db_name)
                print(f"✓ 加载数据库: {db_name} ({len(df)} 条记录, 编码: {encoding})")
            except Exception as exc:
                print(f"⚠ 跳过文件 {csv_file.name}: {exc}")

        if not self.databases:
            raise ValueError('没有成功加载任何数据库')

        self.current_database = database_name if database_name in self.databases else self.database_names[0]
        self.df = self.databases[self.current_database]
        print(f"✓ 默认使用数据库: {self.current_database}")
        print(f"✓ 共加载 {len(self.databases)} 个数据库")

    def _discover_phenotype_file(self, data_path: str) -> Optional[str]:
        folder = Path(data_path).parent if os.path.isfile(data_path) else Path(data_path)
        if not folder.exists():
            return None
        candidates = sorted(folder.glob('*表型*.csv'))
        return str(candidates[0]) if candidates else None

    def _normalize_text_key(self, value: Any) -> str:
        if value is None:
            return ''
        return ''.join(ch for ch in str(value).strip().lower() if not ch.isspace() and ch not in '()[]{}<>-_/.，。；：、,;:')

    def _phenotype_alias_keys(self, trait_name: Any) -> List[str]:
        if trait_name is None:
            return []

        trait_text = str(trait_name).strip()
        keys = {self._normalize_text_key(trait_text)}
        if not trait_text:
            return sorted(key for key in keys if key)

        left_paren = trait_text.find('(')
        right_paren = trait_text.rfind(')')
        if left_paren != -1 and right_paren > left_paren:
            display_name = trait_text[:left_paren].strip()
            alias_name = trait_text[left_paren + 1:right_paren].strip()
            for candidate in (display_name, alias_name):
                if candidate:
                    keys.add(self._normalize_text_key(candidate))

        return sorted(key for key in keys if key)

    def _normalize_breed_name(self, value: Any) -> str:
        return self._normalize_text_key(value)

    def _breed_match_keys(self, breed_name: Any, alias: Optional[Any] = None) -> List[str]:
        keys = set()
        for value in [breed_name, alias]:
            normalized = self._normalize_breed_name(value)
            if not normalized:
                continue
            keys.add(normalized)
            if normalized.endswith('鸡'):
                keys.add(normalized[:-1])
            if normalized.endswith('鸡r'):
                keys.add(normalized[:-2])
        return sorted(keys)

    def _resolve_covariate_field(self, field_name: str) -> Optional[str]:
        return self.COVARIATE_ALIASES.get(self._normalize_text_key(field_name))

    def _resolve_covariate_fields(self, field_names: Optional[List[str]]) -> List[str]:
        resolved = []
        for field_name in field_names or []:
            resolved_name = self._resolve_covariate_field(field_name)
            if resolved_name and resolved_name not in resolved:
                resolved.append(resolved_name)
        return resolved

    def _has_valid_value(self, value: Any) -> bool:
        if value is None:
            return False
        if isinstance(value, float) and np.isnan(value):
            return False
        return True

    def _get_breed_columns(self, df: pd.DataFrame) -> List[str]:
        breed_start = 10 if 'Mean_fre' in df.columns else 8
        return list(df.columns[breed_start:])

    def _load_phenotype_data(self, phenotype_file: str):
        df, _ = self._read_csv_with_fallback(phenotype_file)
        if df.empty or len(df.columns) < 2:
            raise ValueError('表型文件为空或结构不正确')

        metric_col = df.columns[0]
        breed_columns = [str(col).strip() for col in df.columns[1:]]
        phenotype_by_breed: Dict[str, Dict[str, Any]] = {}

        for breed in breed_columns:
            phenotype_by_breed[breed] = {
                'breed': breed,
                'breed_normalized': self._normalize_breed_name(breed),
                'alias': None,
                'sample_size': None,
                'latitude': None,
                'longitude': None,
                'category': None,
                'subcategory': None,
                'numeric_traits': {},
                'categorical_traits': {},
                'match_keys': [],
            }

        all_traits: List[str] = []
        metadata_traits: List[str] = []
        numeric_traits: List[str] = []
        categorical_traits: List[str] = []

        for _, row in df.iterrows():
            trait_name = str(row[metric_col]).strip()
            if not trait_name or trait_name == 'nan':
                continue

            all_traits.append(trait_name)

            values = row.iloc[1:]
            numeric_values = pd.to_numeric(values, errors='coerce')
            numeric_count = int(numeric_values.notna().sum())
            is_numeric_trait = trait_name in self.PHENOTYPE_NUMERIC_METADATA or (
                trait_name not in self.PHENOTYPE_CATEGORICAL_METADATA and numeric_count >= max(3, len(breed_columns) // 3)
            )

            if trait_name in self.PHENOTYPE_NUMERIC_METADATA or trait_name in self.PHENOTYPE_CATEGORICAL_METADATA:
                metadata_traits.append(trait_name)

            if is_numeric_trait:
                numeric_traits.append(trait_name)
            else:
                categorical_traits.append(trait_name)

            for breed, raw_value, numeric_value in zip(breed_columns, values, numeric_values):
                entry = phenotype_by_breed[breed]
                if trait_name == '标签':
                    entry['alias'] = None if pd.isna(raw_value) else str(raw_value).strip()
                elif trait_name == '数量':
                    entry['sample_size'] = None if pd.isna(numeric_value) else float(numeric_value)
                elif trait_name == '纬度':
                    entry['latitude'] = None if pd.isna(numeric_value) else float(numeric_value)
                elif trait_name == '经度':
                    entry['longitude'] = None if pd.isna(numeric_value) else float(numeric_value)
                elif trait_name == '大分类':
                    entry['category'] = None if pd.isna(raw_value) else str(raw_value).strip()
                elif trait_name == '细分':
                    entry['subcategory'] = None if pd.isna(raw_value) else str(raw_value).strip()

                if is_numeric_trait and trait_name not in self.PHENOTYPE_NUMERIC_METADATA:
                    if not pd.isna(numeric_value):
                        entry['numeric_traits'][trait_name] = float(numeric_value)
                elif not is_numeric_trait and trait_name not in self.PHENOTYPE_CATEGORICAL_METADATA:
                    if not pd.isna(raw_value):
                        entry['categorical_traits'][trait_name] = str(raw_value).strip()

        self.phenotype_file = phenotype_file
        self.phenotype_raw = df
        self.phenotype_by_breed = phenotype_by_breed
        self.phenotype_all_traits = list(dict.fromkeys(all_traits))
        self.phenotype_metadata_traits = list(dict.fromkeys(metadata_traits))
        self.phenotype_numeric_traits = list(dict.fromkeys(name for name in numeric_traits if name not in self.PHENOTYPE_NUMERIC_METADATA))
        self.phenotype_categorical_traits = list(dict.fromkeys(name for name in categorical_traits if name not in self.PHENOTYPE_CATEGORICAL_METADATA))
        self.phenotype_numeric_lookup = {}
        for name in self.phenotype_numeric_traits:
            for key in self._phenotype_alias_keys(name):
                self.phenotype_numeric_lookup[key] = name
        self.phenotype_categorical_lookup = {}
        for name in self.phenotype_categorical_traits:
            for key in self._phenotype_alias_keys(name):
                self.phenotype_categorical_lookup[key] = name
        self.phenotype_breed_lookup = {}
        for breed, entry in self.phenotype_by_breed.items():
            entry['match_keys'] = self._breed_match_keys(breed, entry.get('alias'))
            for key in entry['match_keys']:
                self.phenotype_breed_lookup[key] = breed

    def _resolve_breed_to_phenotype(self, breed_name: str) -> Optional[Dict[str, Any]]:
        for key in self._breed_match_keys(breed_name):
            phenotype_breed = self.phenotype_breed_lookup.get(key)
            if phenotype_breed:
                return self.phenotype_by_breed.get(phenotype_breed)
        return None

    def _find_breed_matches(self, breed_queries: Optional[List[str]], breed_columns: List[str]) -> List[str]:
        if not breed_queries:
            return []

        matched: List[str] = []
        breed_column_keys: Dict[str, List[str]] = {}
        for col in breed_columns:
            phenotype_info = self._resolve_breed_to_phenotype(col)
            alias = phenotype_info.get('alias') if phenotype_info else None
            breed_column_keys[col] = self._breed_match_keys(col, alias)

        for query in breed_queries:
            query_keys = self._breed_match_keys(query)
            for breed, candidate_keys in breed_column_keys.items():
                exact_hit = set(query_keys) & set(candidate_keys)
                fuzzy_hit = any(q and (q in candidate or candidate in q) for q in query_keys for candidate in candidate_keys)
                if (exact_hit or fuzzy_hit) and breed not in matched:
                    matched.append(breed)
        return matched


    def _get_phenotype_distribution_summary(self) -> Dict[str, Any]:
        if not self.phenotype_by_breed:
            return {'loaded': False}

        entries = list(self.phenotype_by_breed.values())
        locations = [entry for entry in entries if entry.get('latitude') is not None and entry.get('longitude') is not None]

        def _counter(field_name: str) -> List[Dict[str, Any]]:
            counts = Counter()
            for entry in entries:
                value = entry.get(field_name)
                if value is None:
                    continue
                value_text = str(value).strip()
                if not value_text:
                    continue
                counts[value_text] += 1
            return [{'name': name, 'count': count} for name, count in counts.most_common()]

        latitude_values = [float(entry['latitude']) for entry in locations if isinstance(entry.get('latitude'), (int, float))]
        longitude_values = [float(entry['longitude']) for entry in locations if isinstance(entry.get('longitude'), (int, float))]
        sample_sizes = [float(entry['sample_size']) for entry in entries if isinstance(entry.get('sample_size'), (int, float))]

        return {
            'loaded': True,
            'breed_count': len(entries),
            'location': {
                'known_count': len(locations),
                'missing_count': len(entries) - len(locations),
                'latitude': {
                    'min': round(min(latitude_values), 6) if latitude_values else None,
                    'max': round(max(latitude_values), 6) if latitude_values else None,
                    'mean': round(sum(latitude_values) / len(latitude_values), 6) if latitude_values else None,
                },
                'longitude': {
                    'min': round(min(longitude_values), 6) if longitude_values else None,
                    'max': round(max(longitude_values), 6) if longitude_values else None,
                    'mean': round(sum(longitude_values) / len(longitude_values), 6) if longitude_values else None,
                },
                'examples': [
                    {
                        'breed': entry.get('breed'),
                        'latitude': entry.get('latitude'),
                        'longitude': entry.get('longitude'),
                    }
                    for entry in locations[:10]
                ],
            },
            '驯化程度分类_distribution': _counter('category'),
            '用途分类_distribution': _counter('subcategory'),
            'sample_size': {
                'known_count': len(sample_sizes),
                'min': round(min(sample_sizes), 2) if sample_sizes else None,
                'max': round(max(sample_sizes), 2) if sample_sizes else None,
                'mean': round(sum(sample_sizes) / len(sample_sizes), 2) if sample_sizes else None,
            },
        }

    def _get_current_phenotype_summary(self) -> Dict[str, Any]:
        if not self.phenotype_by_breed:
            return {'loaded': False}

        sv_breeds = self._get_breed_columns(self.df) if self.df is not None else []
        matched = [breed for breed in sv_breeds if self._resolve_breed_to_phenotype(breed)]
        return {
            'loaded': True,
            'source': '品种表型库',
            'breed_count': len(self.phenotype_by_breed),
            'trait_count': len(self.phenotype_all_traits),
            'all_traits': self.phenotype_all_traits,
            'metadata_traits': self.phenotype_metadata_traits,
            'matched_sv_breeds': len(matched),
            'numeric_traits': len(self.phenotype_numeric_traits),
            'categorical_traits': len(self.phenotype_categorical_traits),
            'sample_traits': self.phenotype_numeric_traits[:10],
            'trait_examples': self.phenotype_all_traits[:10],
            'covariates_available': ['驯化程度分类', '用途分类', '纬度', '经度'],
            'distribution_summary': self._get_phenotype_distribution_summary(),
            'alias_examples': [
                {'breed': breed, 'alias': info.get('alias')}
                for breed, info in list(self.phenotype_by_breed.items())[:10]
                if info.get('alias')
            ],
        }

    def _match_breed_profile_entries(
        self,
        breed_queries: Optional[List[str]],
        exact_match: bool = False,
        max_matches: int = 20,
    ) -> List[Dict[str, Any]]:
        if not breed_queries:
            return []

        matched: List[Dict[str, Any]] = []
        seen_breeds = set()
        for query in breed_queries:
            query_key = self._normalize_breed_name(query)
            if not query_key:
                continue
            for breed, entry in self.phenotype_by_breed.items():
                match_keys = entry.get('match_keys') or self._breed_match_keys(breed, entry.get('alias'))
                exact_hit = query_key in match_keys or any(query_key == candidate for candidate in match_keys)
                fuzzy_hit = any(query_key in candidate or candidate in query_key for candidate in match_keys)
                if not (exact_hit or (not exact_match and fuzzy_hit)):
                    continue
                if breed in seen_breeds:
                    continue
                matched.append({'breed': breed, 'query': query, 'match_type': 'exact' if exact_hit else 'fuzzy'})
                seen_breeds.add(breed)
                if len(matched) >= max_matches:
                    return matched
        return matched

    def _build_breed_profile(self, breed: str, entry: Dict[str, Any]) -> Dict[str, Any]:
        numeric_traits = dict(entry.get('numeric_traits') or {})
        categorical_traits = dict(entry.get('categorical_traits') or {})
        trait_values: Dict[str, Any] = {}
        trait_values.update(numeric_traits)
        trait_values.update(categorical_traits)

        morphology = {
            'body_size_g': numeric_traits.pop('平均体重(Body_size_g)', None),
            'feather_color': categorical_traits.pop('羽色(Feather_color)', None),
            'shank_color': categorical_traits.pop('胫色(Shank_color)', None),
            'skin_color': categorical_traits.pop('肤色(Skin_color)', None),
        }
        climate_trait_names = [
            '年平均温度(Bio1)', '平均昼夜温差(Bio2)', '等温性(Bio3)', '温度季节性(Bio4)',
            '最热月份的最高温度(Bio5)', '最冷月份的最低温度(Bio6)', '温度年范围(Bio7)',
            '最潮湿地区的平均温度(Bio8)', '最干燥季度的平均温度(Bio9)', '最热季度的平均温度(Bio10)',
            '最冷季度的平均温度(Bio11)', '年降水量(Bio12)', '最湿月的降水量(Bio13)',
            '最干燥月份的降水量(Bio14)', '降水季节性(Bio15)', '最湿季度的降水量(Bio16)',
            '最干燥季度的降水量(Bio17)', '最温暖季度的降水量(Bio18)', '最冷季度的降水量(Bio19)',
        ]
        climate = {}
        for trait_name in climate_trait_names:
            if trait_name in numeric_traits:
                climate[trait_name] = numeric_traits.pop(trait_name)

        location = {
            'latitude': entry.get('latitude'),
            'longitude': entry.get('longitude'),
            'elevation': numeric_traits.pop('海拔高度(Elevation)', None),
        }

        return {
            'breed': breed,
            'alias': entry.get('alias'),
            'collected_sample_size': entry.get('sample_size'),
            'sample_size_note': '数据库收录数量，不代表该品种全部样本或总体数量',
            '驯化程度分类': entry.get('category'),
            '用途分类': entry.get('subcategory'),
            'match_keys': entry.get('match_keys', []),
            'location': location,
            'morphology': morphology,
            'climate': climate,
            'numeric_traits': numeric_traits,
            'categorical_traits': categorical_traits,
            'trait_values': trait_values,
            'trait_count': len(trait_values),
        }

    def query_breed_profile(
        self,
        breed_names: Optional[List[str]] = None,
        exact_match: bool = False,
        max_results: int = 20,
        include_trait_values: bool = True,
    ) -> Dict[str, Any]:
        if not self.phenotype_by_breed:
            return {'success': False, 'error': '表型数据未加载'}
        if not breed_names:
            return {'success': False, 'error': '请提供 breed_names 参数'}

        matches = self._match_breed_profile_entries(breed_names, exact_match=exact_match, max_matches=max_results)
        profiles: List[Dict[str, Any]] = []
        matched_queries = set()
        for item in matches:
            breed = item['breed']
            entry = self.phenotype_by_breed.get(breed)
            if not entry:
                continue
            profile = self._build_breed_profile(breed, entry)
            profile['match_type'] = item['match_type']
            profile['matched_query'] = item['query']
            if not include_trait_values:
                profile.pop('trait_values', None)
            profiles.append(profile)
            matched_queries.add(item['query'])

        result = {
            'success': True,
            'query_type': 'breed_profile',
            'requested_breeds': breed_names,
            'exact_match': exact_match,
            'matched_count': len(profiles),
            'returned_count': len(profiles),
            'profiles': profiles,
            'unmatched_queries': [query for query in breed_names if query not in matched_queries],
            'available_sections': ['metadata', 'location', 'morphology', 'climate', 'numeric_traits', 'categorical_traits', 'trait_values'],
            'phenotype': self._get_current_phenotype_summary(),
            'statistical_note': '这是表型库的直接查询结果，可用于品种知识库问答，不是关联分析。',
        }
        if profiles:
            result['profile_examples'] = [
                {'breed': profile['breed'], 'alias': profile.get('alias'), 'match_type': profile.get('match_type'), 'collected_sample_size': profile.get('collected_sample_size'), 'sample_size_note': profile.get('sample_size_note')}
                for profile in profiles[:5]
            ]
        else:
            result['suggestion'] = '请尝试使用品种全名、标签别名或更短的模糊片段。'
        return result

    def _select_databases(self, database_name: Optional[str], search_all: bool) -> List[str]:
        if search_all:
            return self.database_names
        if database_name and database_name in self.databases:
            return [database_name]
        return [self.current_database]

    def _build_variant_result(
        self,
        row: pd.Series,
        db_name: str,
        breed_cols: List[str],
        include_annotation: bool,
        breeds: Optional[List[str]] = None,
        include_all_breeds: bool = False,
    ) -> Dict[str, Any]:
        result = {
            'ID': str(row['ID']),
            'Chr': str(row['Chr']),
            'POS': int(row['POS']),
            'database': self._display_db_name(db_name),
            'REF': str(row['REF']) if pd.notna(row.get('REF')) else '-',
            'ALT': str(row['ALT']) if pd.notna(row.get('ALT')) else '-',
            'Region': str(row['Region']) if 'Region' in row.index and pd.notna(row['Region']) else '-',
            'Gene': str(row['Gene']) if 'Gene' in row.index and pd.notna(row['Gene']) else '-',
            'Mean_fre': round(float(row['Mean_fre']), 4) if 'Mean_fre' in row.index and pd.notna(row['Mean_fre']) else 0.0,
        }

        if 'End' in row.index and pd.notna(row['End']):
            result['End'] = int(row['End'])
            result['Length'] = int(row['End']) - int(row['POS'])
        if 'SV_Type' in row.index and pd.notna(row['SV_Type']):
            result['SV_Type'] = str(row['SV_Type'])

        if include_all_breeds:
            result['breed_frequencies'] = {
                breed: round(float(row[breed]), 4) if pd.notna(row[breed]) else 0.0
                for breed in breed_cols
            }
        elif breeds:
            matched_breeds = self._find_breed_matches(breeds, breed_cols)
            result['breed_frequencies'] = {
                breed: round(float(row[breed]), 4) if pd.notna(row[breed]) else 0.0
                for breed in matched_breeds
            }

        if include_annotation and self.annotation and result['Gene'] != '-':
            gene_anno = self.annotation.get_gene_annotation(result['Gene'])
            if gene_anno:
                result['Gene_Name'] = gene_anno.get('name', '')
                result['Gene_Biotype'] = gene_anno.get('biotype', '')
                result['Gene_Description'] = (gene_anno.get('description', '') or '')[:100]

        return result

    def _search_sv_by_region(
        self,
        chromosome: str,
        start_pos: int,
        end_pos: int,
        max_results: int = 100,
        database_name: Optional[str] = None,
        search_all: bool = False,
        sv_type: Optional[str] = None,
        include_annotation: bool = True,
        breeds: Optional[List[str]] = None,
        include_all_breeds: bool = False,
    ) -> Dict[str, Any]:
        try:
            chr_str = str(chromosome).replace('chr', '').replace('Chr', '')
            all_results: List[Dict[str, Any]] = []

            for db_name in self._select_databases(database_name, search_all):
                df = self.databases[db_name]
                breed_cols = self._get_breed_columns(df)

                chr_mask = df['Chr'].astype(str) == chr_str
                pos_series = pd.to_numeric(df['POS'], errors='coerce')
                end_series = pd.to_numeric(df.get('End', pos_series), errors='coerce').fillna(pos_series)
                overlap_mask = (end_series >= start_pos) & (pos_series <= end_pos)
                filtered = df[chr_mask & overlap_mask]

                if sv_type and 'SV_Type' in df.columns:
                    filtered = filtered[filtered['SV_Type'].astype(str).str.upper() == sv_type.upper()]

                for _, row in filtered.iterrows():
                    all_results.append(
                        self._build_variant_result(
                            row=row,
                            db_name=db_name,
                            breed_cols=breed_cols,
                            include_annotation=include_annotation,
                            breeds=breeds,
                            include_all_breeds=include_all_breeds,
                        )
                    )

            total = len(all_results)
            return {
                'success': True,
                'count': min(total, max_results),
                'total_matched': total,
                'results': all_results[:max_results],
            }
        except Exception as exc:
            return {'success': False, 'error': str(exc), 'count': 0, 'results': []}

    def _get_sv_detail(self, sv_id: str, database_name: Optional[str] = None, search_all: bool = False) -> Dict[str, Any]:
        try:
            for db_name in self._select_databases(database_name, search_all):
                df = self.databases.get(db_name)
                if df is None:
                    continue
                row_data = df[df['ID'] == sv_id]
                if row_data.empty:
                    continue

                row = row_data.iloc[0]
                detail = self._build_variant_result(
                    row=row,
                    db_name=db_name,
                    breed_cols=self._get_breed_columns(df),
                    include_annotation=True,
                    include_all_breeds=True,
                )
                return {'success': True, 'detail': detail}

            return {'success': False, 'error': f'未找到 ID: {sv_id}'}
        except Exception as exc:
            return {'success': False, 'error': str(exc)}

    def _resolve_phenotype_name(self, phenotype_name: str) -> Optional[str]:
        if not self.phenotype_numeric_lookup:
            return None

        query_key = self._normalize_text_key(phenotype_name)
        if query_key in self.phenotype_numeric_lookup:
            return self.phenotype_numeric_lookup[query_key]

        for key, actual in self.phenotype_numeric_lookup.items():
            if query_key and (query_key in key or key in query_key):
                return actual
        return None

    def _rank_array(self, values: np.ndarray) -> np.ndarray:
        return pd.Series(values).rank(method='average').to_numpy(dtype=float)

    def _weighted_mean(self, values: np.ndarray, weights: np.ndarray) -> float:
        return float(np.sum(values * weights) / np.sum(weights))

    def _weighted_pearson(self, x: np.ndarray, y: np.ndarray, weights: np.ndarray) -> float:
        if np.sum(weights) <= 0:
            return np.nan
        x_mean = self._weighted_mean(x, weights)
        y_mean = self._weighted_mean(y, weights)
        cov = np.sum(weights * (x - x_mean) * (y - y_mean))
        x_var = np.sum(weights * (x - x_mean) ** 2)
        y_var = np.sum(weights * (y - y_mean) ** 2)
        if x_var <= 0 or y_var <= 0:
            return np.nan
        return float(cov / np.sqrt(x_var * y_var))

    def _pearson(self, x: np.ndarray, y: np.ndarray) -> float:
        if len(x) < 2 or np.std(x) == 0 or np.std(y) == 0:
            return np.nan
        return float(np.corrcoef(x, y)[0, 1])

    def _compute_association_stat(
        self,
        x: np.ndarray,
        y: np.ndarray,
        method: str,
        weights: Optional[np.ndarray] = None,
    ) -> float:
        if method == 'pearson':
            return self._pearson(x, y)
        if method == 'spearman':
            return self._pearson(self._rank_array(x), self._rank_array(y))
        if method == 'weighted_pearson':
            return self._weighted_pearson(x, y, weights)
        if method == 'weighted_spearman':
            return self._weighted_pearson(self._rank_array(x), self._rank_array(y), weights)
        return np.nan

    def _select_analysis_method(self, method: str, weights: np.ndarray) -> str:
        if method != 'auto':
            return method
        if len(weights) >= 8 and np.nanmax(weights) > np.nanmin(weights):
            return 'weighted_spearman'
        return 'spearman'

    def _permutation_p_value(
        self,
        x: np.ndarray,
        y: np.ndarray,
        method: str,
        observed: float,
        weights: Optional[np.ndarray],
        permutations: int,
        rng: np.random.Generator,
    ) -> Optional[float]:
        if permutations <= 0 or np.isnan(observed):
            return None

        exceed = 0
        for _ in range(permutations):
            shuffled_y = y[rng.permutation(len(y))]
            perm_stat = self._compute_association_stat(x, shuffled_y, method, weights)
            if not np.isnan(perm_stat) and abs(perm_stat) >= abs(observed):
                exceed += 1
        return float((exceed + 1) / (permutations + 1))

    def _apply_bh_fdr(self, associations: List[Dict[str, Any]], score_field: str = 'correlation'):
        indexed = [(idx, item['p_value']) for idx, item in enumerate(associations) if item.get('p_value') is not None]
        if indexed:
            indexed.sort(key=lambda item: item[1])
            m = len(indexed)
            adjusted = [None] * m
            running = 1.0
            for i in range(m - 1, -1, -1):
                _, p_value = indexed[i]
                current = min(running, p_value * m / (i + 1))
                running = current
                adjusted[i] = max(0.0, min(1.0, float(current)))
            for (original_idx, _), fdr in zip(indexed, adjusted):
                associations[original_idx]['fdr'] = fdr

        associations.sort(
            key=lambda item: (
                -abs(item.get(score_field, 0.0)),
                item.get('p_value') if item.get('p_value') is not None else 1.0,
            )
        )

    def _build_breed_aligned_arrays(self, breed_frequencies: Dict[str, float], phenotype_name: str) -> Dict[str, Any]:
        aligned_rows = []
        for breed, frequency in breed_frequencies.items():
            phenotype_info = self._resolve_breed_to_phenotype(breed)
            if phenotype_info is None:
                continue

            phenotype_value = phenotype_info['numeric_traits'].get(phenotype_name)
            if phenotype_value is None or pd.isna(phenotype_value):
                continue

            aligned_rows.append({
                'breed': breed,
                'frequency': float(frequency),
                'phenotype_value': float(phenotype_value),
                'sample_size': float(phenotype_info['sample_size']) if phenotype_info['sample_size'] is not None else 1.0,
                'category': phenotype_info.get('category'),
                'subcategory': phenotype_info.get('subcategory'),
                'latitude': phenotype_info.get('latitude'),
                'longitude': phenotype_info.get('longitude'),
                'alias': phenotype_info.get('alias'),
            })

        return {
            'rows': aligned_rows,
            'matched_breeds': [row['breed'] for row in aligned_rows],
        }

    def _filter_rows_by_fields(self, rows: List[Dict[str, Any]], fields: List[str]) -> List[Dict[str, Any]]:
        if not fields:
            return rows
        return [row for row in rows if all(self._has_valid_value(row.get(field)) for field in fields)]

    def _build_design_matrix(self, rows: List[Dict[str, Any]], numeric_fields: List[str], categorical_fields: List[str]) -> Tuple[np.ndarray, Dict[str, Any]]:
        matrices = [np.ones((len(rows), 1), dtype=float)]
        summary = {'numeric_covariates': [], 'categorical_covariates': []}

        for field in numeric_fields:
            values = np.array([float(row[field]) for row in rows], dtype=float)
            if np.std(values) == 0:
                continue
            centered = (values - np.mean(values)) / np.std(values)
            matrices.append(centered.reshape(-1, 1))
            summary['numeric_covariates'].append(field)

        for field in categorical_fields:
            levels = sorted({str(row[field]) for row in rows if self._has_valid_value(row.get(field))})
            if len(levels) <= 1:
                continue
            for level in levels[1:]:
                dummy = np.array([1.0 if str(row[field]) == level else 0.0 for row in rows], dtype=float)
                matrices.append(dummy.reshape(-1, 1))
            summary['categorical_covariates'].append({'field': field, 'levels': levels})

        return np.hstack(matrices), summary

    def _weighted_residualize(self, target: np.ndarray, design: np.ndarray, weights: np.ndarray) -> np.ndarray:
        if design.shape[1] <= 1:
            return target - self._weighted_mean(target, weights)
        sqrt_w = np.sqrt(weights).reshape(-1, 1)
        weighted_design = design * sqrt_w
        weighted_target = target * sqrt_w[:, 0]
        beta, _, _, _ = np.linalg.lstsq(weighted_design, weighted_target, rcond=None)
        return target - design @ beta

    def _within_group_residualize(self, values: np.ndarray, groups: List[Tuple[Any, ...]], weights: np.ndarray) -> np.ndarray:
        residuals = values.copy()
        group_to_indices: Dict[Tuple[Any, ...], List[int]] = {}
        for idx, group in enumerate(groups):
            group_to_indices.setdefault(group, []).append(idx)
        for indices in group_to_indices.values():
            idx_array = np.array(indices, dtype=int)
            group_values = values[idx_array]
            group_weights = weights[idx_array]
            residuals[idx_array] = group_values - self._weighted_mean(group_values, group_weights)
        return residuals

    def _compute_stratum_results(
        self,
        rows: List[Dict[str, Any]],
        groups: List[Tuple[Any, ...]],
        method: str,
        min_stratum_breeds: int,
    ) -> List[Dict[str, Any]]:
        stratum_results = []
        group_to_rows: Dict[Tuple[Any, ...], List[Dict[str, Any]]] = {}
        for row, group in zip(rows, groups):
            group_to_rows.setdefault(group, []).append(row)

        for group, group_rows in group_to_rows.items():
            if len(group_rows) < min_stratum_breeds:
                continue
            x = np.array([row['frequency'] for row in group_rows], dtype=float)
            y = np.array([row['phenotype_value'] for row in group_rows], dtype=float)
            weights = np.array([row['sample_size'] for row in group_rows], dtype=float)
            stat = self._compute_association_stat(x, y, method, weights)
            if np.isnan(stat):
                continue
            stratum_results.append({
                'stratum': '|'.join(map(str, group)),
                'n_breeds': len(group_rows),
                'correlation': round(float(stat), 6),
                'breeds': [row['breed'] for row in group_rows],
            })

        stratum_results.sort(key=lambda item: (-abs(item['correlation']), -item['n_breeds']))
        return stratum_results

    def _resolve_effect_direction(self, score: float, threshold: float = 1e-9) -> str:
        if abs(float(score)) <= threshold:
            return 'neutral'
        return 'positive' if score > 0 else 'negative'

    def _build_stratified_results_overview(self, stratum_results: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not stratum_results:
            return {
                'has_strata': False,
                'strata_count': 0,
                'positive_strata': 0,
                'negative_strata': 0,
                'neutral_strata': 0,
                'direction_consistency': 'not_available',
                'top_strata': [],
            }

        directions = [self._resolve_effect_direction(item['correlation']) for item in stratum_results]
        positive_count = directions.count('positive')
        negative_count = directions.count('negative')
        neutral_count = directions.count('neutral')

        if positive_count and not negative_count:
            consistency = 'all_positive'
        elif negative_count and not positive_count:
            consistency = 'all_negative'
        elif positive_count or negative_count:
            consistency = 'mixed'
        else:
            consistency = 'all_neutral'

        return {
            'has_strata': True,
            'strata_count': len(stratum_results),
            'positive_strata': positive_count,
            'negative_strata': negative_count,
            'neutral_strata': neutral_count,
            'direction_consistency': consistency,
            'top_strata': [
                {
                    'stratum': item['stratum'],
                    'correlation': item['correlation'],
                    'effect_direction': self._resolve_effect_direction(item['correlation']),
                    'n_breeds': item['n_breeds'],
                }
                for item in stratum_results[:3]
            ],
        }

    def _build_association_summary(
        self,
        entity_label: str,
        score: float,
        p_value: Optional[float],
        fdr: Optional[float],
        n_breeds: int,
        covariate_mode: str,
    ) -> Dict[str, Any]:
        effect_direction = self._resolve_effect_direction(score)

        significance = 'not_computed'
        if fdr is not None:
            if fdr < 0.05:
                significance = 'fdr_significant'
            elif fdr < 0.1:
                significance = 'fdr_suggestive'
            else:
                significance = 'not_significant'
        elif p_value is not None:
            if p_value < 0.05:
                significance = 'nominal_significant'
            elif p_value < 0.1:
                significance = 'nominal_suggestive'
            else:
                significance = 'not_significant'

        p_text = 'NA' if p_value is None else f"{p_value:.4g}"
        fdr_text = 'NA' if fdr is None else f"{fdr:.4g}"
        headline = (
            f"{entity_label}: {effect_direction} association (score={score:.4f}, "
            f"p={p_text}, fdr={fdr_text}, n_breeds={n_breeds}, covariate_mode={covariate_mode})"
        )

        return {
            'headline': headline,
            'effect_direction': effect_direction,
            'score': round(float(score), 6),
            'p_value': p_value,
            'fdr': fdr,
            'significance': significance,
            'n_breeds': n_breeds,
            'covariate_mode': covariate_mode,
        }

    def _attach_display_fields(
        self,
        associations: List[Dict[str, Any]],
        score_field: str,
        label_field: str,
    ) -> None:
        for item in associations:
            score = float(item.get(score_field, 0.0))
            item['effect_direction'] = self._resolve_effect_direction(score)
            item['stratified_results_overview'] = self._build_stratified_results_overview(item.get('stratified_results', []))

            label_value = str(item.get(label_field) or 'unknown')
            summary = self._build_association_summary(
                entity_label=label_value,
                score=score,
                p_value=item.get('p_value'),
                fdr=item.get('fdr'),
                n_breeds=int(item.get('n_breeds') or 0),
                covariate_mode=str(item.get('covariate_control', {}).get('mode', 'none')),
            )
            item['summary'] = summary
            item['p_value_sci'] = None if item.get('p_value') is None else f"{float(item['p_value']):.3e}"
            item['fdr_sci'] = None if item.get('fdr') is None else f"{float(item['fdr']):.3e}"
            item['effect_direction_detail'] = {
                'label': summary['effect_direction'],
                'score': summary['score'],
            }

    def _prepare_association_rows(
        self,
        rows: List[Dict[str, Any]],
        method: str,
        covariate_mode: str,
        categorical_covariates: Optional[List[str]],
        numeric_covariates: Optional[List[str]],
        stratify_by: Optional[List[str]],
        min_breeds: int,
        min_stratum_breeds: int,
    ) -> Optional[Dict[str, Any]]:
        selected_method = self._select_analysis_method(method, np.array([row['sample_size'] for row in rows], dtype=float))
        categorical_fields = self._resolve_covariate_fields(categorical_covariates)
        numeric_fields = self._resolve_covariate_fields(numeric_covariates)
        stratify_fields = self._resolve_covariate_fields(stratify_by)

        working_rows = rows
        x_original = np.array([row['frequency'] for row in working_rows], dtype=float)
        y_original = np.array([row['phenotype_value'] for row in working_rows], dtype=float)
        weights_original = np.array([row['sample_size'] for row in working_rows], dtype=float)
        covariate_control = {
            'mode': covariate_mode,
            'categorical_covariates': categorical_fields,
            'numeric_covariates': numeric_fields,
            'stratify_by': stratify_fields,
        }
        stratum_results = []

        if covariate_mode == 'adjust':
            required_fields = categorical_fields + numeric_fields
            working_rows = self._filter_rows_by_fields(rows, required_fields)
            if len(working_rows) < min_breeds:
                return None
            design, summary = self._build_design_matrix(working_rows, numeric_fields, categorical_fields)
            x = np.array([row['frequency'] for row in working_rows], dtype=float)
            y = np.array([row['phenotype_value'] for row in working_rows], dtype=float)
            weights = np.array([row['sample_size'] for row in working_rows], dtype=float)
            x_used = self._weighted_residualize(x, design, weights)
            y_used = self._weighted_residualize(y, design, weights)
            covariate_control['applied_design'] = summary
        elif covariate_mode == 'stratify':
            if not stratify_fields:
                return None
            working_rows = self._filter_rows_by_fields(rows, stratify_fields)
            if len(working_rows) < min_breeds:
                return None
            group_keys = [tuple(row[field] for field in stratify_fields) for row in working_rows]
            counts = pd.Series(group_keys).value_counts().to_dict()
            filtered_pairs = [(row, group) for row, group in zip(working_rows, group_keys) if counts.get(group, 0) >= min_stratum_breeds]
            if len(filtered_pairs) < min_breeds:
                return None
            working_rows = [pair[0] for pair in filtered_pairs]
            group_keys = [pair[1] for pair in filtered_pairs]
            x = np.array([row['frequency'] for row in working_rows], dtype=float)
            y = np.array([row['phenotype_value'] for row in working_rows], dtype=float)
            weights = np.array([row['sample_size'] for row in working_rows], dtype=float)
            x_used = self._within_group_residualize(x, group_keys, weights)
            y_used = self._within_group_residualize(y, group_keys, weights)
            stratum_results = self._compute_stratum_results(working_rows, group_keys, selected_method, min_stratum_breeds)
        else:
            if len(working_rows) < min_breeds:
                return None
            x_used = x_original
            y_used = y_original
            weights = weights_original

        if covariate_mode != 'stratify':
            weights = np.array([row['sample_size'] for row in working_rows], dtype=float)

        return {
            'selected_method': selected_method,
            'working_rows': working_rows,
            'x_used': x_used,
            'y_used': y_used,
            'weights': weights,
            'covariate_control': covariate_control,
            'stratum_results': stratum_results,
        }

    def _compute_analytical_p_value(
        self,
        x: np.ndarray,
        y: np.ndarray,
        method: str,
        observed: Optional[float] = None,
        weights: Optional[np.ndarray] = None,
        permutations: int = 200,
    ) -> Optional[float]:
        if len(x) < 3:
            return None

        p_value: Optional[float] = None
        if method in {'spearman', 'weighted_spearman'} and spearmanr is not None:
            _, p = spearmanr(x, y)
            p_value = None if np.isnan(p) else float(p)
        elif method in {'pearson', 'weighted_pearson'} and pearsonr is not None:
            _, p = pearsonr(x, y)
            p_value = None if np.isnan(p) else float(p)

        if p_value is not None:
            return p_value

        if observed is None:
            return None

        # 当 scipy 不可用时，使用 Fisher z 近似避免全基因组扫描退化为高成本置换检验
        try:
            corr = float(observed)
            if np.isnan(corr):
                return None
            corr = max(min(corr, 0.999999), -0.999999)
            if len(x) > 3:
                z = abs(np.arctanh(corr)) * math.sqrt(len(x) - 3)
                p_approx = math.erfc(z / math.sqrt(2.0))
                return float(max(0.0, min(1.0, p_approx)))
        except Exception:
            pass

        rng = np.random.default_rng(42)
        return self._permutation_p_value(
            x=x,
            y=y,
            method=method,
            observed=observed,
            weights=weights,
            permutations=permutations,
            rng=rng,
        )

    def _sort_results(self, items: List[Dict[str, Any]], rank_by: str, descending: bool) -> List[Dict[str, Any]]:
        if rank_by == 'abs_correlation':
            key_fn = lambda item: abs(float(item.get('correlation', item.get('aggregate_score', 0.0))))
        else:
            key_fn = lambda item: item.get(rank_by)

        def normalize(value: Any) -> Tuple[int, Any]:
            if value is None:
                return (1, float('inf'))
            return (0, value)

        return sorted(items, key=lambda item: normalize(key_fn(item)), reverse=descending)

    def _association_priority_key(self, item: Dict[str, Any]) -> Tuple[float, float, int]:
        p_value = item.get('p_value')
        try:
            p_rank = float(p_value) if p_value is not None else float('inf')
        except (TypeError, ValueError):
            p_rank = float('inf')

        try:
            corr_rank = -abs(float(item.get('correlation', 0.0)))
        except (TypeError, ValueError):
            corr_rank = 0.0

        n_breeds = int(item.get('n_breeds') or 0)
        return (p_rank, corr_rank, -n_breeds)

    def _deduplicate_sv_associations(self, associations: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], int]:
        if not associations:
            return [], 0

        best_by_sv: Dict[str, Dict[str, Any]] = {}
        removed_count = 0

        for idx, item in enumerate(associations):
            key = str(item.get('sv_id') or f'__row_{idx}')
            existing = best_by_sv.get(key)
            if existing is None:
                best_by_sv[key] = item
                continue

            removed_count += 1
            if self._association_priority_key(item) < self._association_priority_key(existing):
                best_by_sv[key] = item

        return list(best_by_sv.values()), removed_count

    def _compact_scan_hit(self, hit: Dict[str, Any], rank: int) -> Dict[str, Any]:
        p_value = hit.get('p_value')
        fdr = hit.get('fdr')
        try:
            p_value_sci = f"{float(p_value):.3e}" if p_value is not None else None
        except (TypeError, ValueError):
            p_value_sci = None
        try:
            fdr_sci = f"{float(fdr):.3e}" if fdr is not None else None
        except (TypeError, ValueError):
            fdr_sci = None

        return {
            'rank': rank,
            'sv_id': hit.get('sv_id'),
            'chromosome': hit.get('chromosome'),
            'position': hit.get('position'),
            'end': hit.get('end'),
            'sv_type': hit.get('sv_type'),
            'gene': hit.get('gene'),
            'correlation': hit.get('correlation'),
            'effect_direction': hit.get('effect_direction'),
            'n_breeds': hit.get('n_breeds'),
            'mean_frequency': hit.get('mean_frequency'),
            'p_value': p_value,
            'fdr': fdr,
            'p_value_sci': p_value_sci,
            'fdr_sci': fdr_sci,
        }

    def genome_wide_association_scan(
        self,
        phenotype_name: str,
        method: str = 'auto',
        covariate_mode: str = 'none',
        categorical_covariates: Optional[List[str]] = None,
        numeric_covariates: Optional[List[str]] = None,
        stratify_by: Optional[List[str]] = None,
        min_breeds: int = 8,
        min_stratum_breeds: int = 4,
        database_name: Optional[str] = None,
        search_all_databases: bool = False,
        sv_type: Optional[str] = None,
        chromosomes: Optional[List[str]] = None,
        include_annotation: bool = True,
        top_n: int = 20,
        rank_by: str = 'p_value',
        sort_order: str = 'asc',
        min_abs_correlation: Optional[float] = None,
    ) -> Dict[str, Any]:
        if not self.phenotype_by_breed:
            return {'success': False, 'error': '表型数据未加载'}
        if covariate_mode not in {'none', 'adjust', 'stratify'}:
            return {'success': False, 'error': f'未知的 covariate_mode: {covariate_mode}'}

        try:
            top_n = max(1, int(top_n))
        except (TypeError, ValueError):
            top_n = 20
        compact_hits = top_n > 20

        resolved_phenotype = self._resolve_phenotype_name(phenotype_name)
        if not resolved_phenotype:
            return {'success': False, 'error': f'未找到数值型表型: {phenotype_name}'}

        chromosome_set = {str(item).replace('chr', '').replace('Chr', '') for item in (chromosomes or [])}
        associations: List[Dict[str, Any]] = []
        tested_rows = 0

        for db_name in self._select_databases(database_name, search_all_databases):
            df = self.databases[db_name]
            breed_cols = self._get_breed_columns(df)
            working_df = df
            if sv_type and 'SV_Type' in working_df.columns:
                working_df = working_df[working_df['SV_Type'].astype(str).str.upper() == sv_type.upper()]
            if chromosome_set:
                working_df = working_df[working_df['Chr'].astype(str).isin(chromosome_set)]

            for _, row in working_df.iterrows():
                breed_frequencies = {
                    breed: float(row[breed])
                    for breed in breed_cols
                    if pd.notna(row[breed])
                }
                aligned = self._build_breed_aligned_arrays(breed_frequencies, resolved_phenotype)
                prepared = self._prepare_association_rows(
                    rows=aligned['rows'],
                    method=method,
                    covariate_mode=covariate_mode,
                    categorical_covariates=categorical_covariates,
                    numeric_covariates=numeric_covariates,
                    stratify_by=stratify_by,
                    min_breeds=min_breeds,
                    min_stratum_breeds=min_stratum_breeds,
                )
                if not prepared:
                    continue
                stat = self._compute_association_stat(
                    prepared['x_used'],
                    prepared['y_used'],
                    prepared['selected_method'],
                    prepared['weights'],
                )
                if np.isnan(stat):
                    continue
                if min_abs_correlation is not None and abs(float(stat)) < float(min_abs_correlation):
                    continue
                p_value = self._compute_analytical_p_value(
                    prepared['x_used'],
                    prepared['y_used'],
                    prepared['selected_method'],
                    observed=stat,
                    weights=prepared['weights'],
                    permutations=200,
                )
                if p_value is None:
                    continue
                tested_rows += 1

                entry = {
                    'sv_id': str(row['ID']),
                    'database': self._display_db_name(db_name),
                    'gene': str(row['Gene']) if 'Gene' in row.index and pd.notna(row['Gene']) else '-',
                    'chromosome': str(row['Chr']),
                    'position': int(row['POS']),
                    'end': int(row['End']) if 'End' in row.index and pd.notna(row['End']) else None,
                    'sv_type': str(row['SV_Type']) if 'SV_Type' in row.index and pd.notna(row['SV_Type']) else None,
                    'region': str(row['Region']) if 'Region' in row.index and pd.notna(row['Region']) else '-',
                    'mean_frequency': round(float(row['Mean_fre']), 4) if 'Mean_fre' in row.index and pd.notna(row['Mean_fre']) else None,
                    'correlation': round(float(stat), 6),
                    'effect_direction': self._resolve_effect_direction(stat),
                    'method': prepared['selected_method'],
                    'n_breeds': len(prepared['working_rows']),
                    'p_value': float(p_value),
                    'covariate_control': prepared['covariate_control'],
                    'stratified_results': prepared['stratum_results'],
                }
                if compact_hits:
                    entry['matched_breed_count'] = len(prepared['working_rows'])
                else:
                    entry['matched_breeds'] = [item['breed'] for item in prepared['working_rows']]
                    entry['top_breeds_by_frequency'] = sorted(prepared['working_rows'], key=lambda item: item['frequency'], reverse=True)[:3]
                    entry['top_breeds_by_phenotype'] = sorted(prepared['working_rows'], key=lambda item: item['phenotype_value'], reverse=True)[:3]
                if include_annotation and self.annotation and entry['gene'] != '-':
                    anno = self.annotation.get_gene_annotation(entry['gene'])
                    if anno:
                        entry['gene_name'] = anno.get('name') or entry['gene']
                        entry['gene_biotype'] = anno.get('biotype')
                        entry['gene_description'] = (anno.get('description') or '')[:160]
                associations.append(entry)

        raw_association_count = len(associations)
        associations, deduplicated_count = self._deduplicate_sv_associations(associations)

        self._apply_bh_fdr(associations, score_field='correlation')
        self._attach_display_fields(associations, score_field='correlation', label_field='sv_id')

        descending = sort_order.lower() == 'desc'
        associations = self._sort_results(associations, rank_by=rank_by, descending=descending)
        significant_count = sum(1 for item in associations if item.get('fdr') is not None and item['fdr'] < 0.05)

        selected_hits = associations[:top_n]
        if compact_hits:
            selected_hits = [self._compact_scan_hit(hit, rank=idx + 1) for idx, hit in enumerate(selected_hits)]

        return {
            'success': True,
            'analysis_type': 'genome_wide_scan',
            'analysis_level': 'breed_aggregate',
            'phenotype_name': resolved_phenotype,
            'method': method,
            'rank_by': rank_by,
            'sort_order': sort_order,
            'tested_row_count': tested_rows,
            'tested_variant_count': len(associations),
            'deduplicated_count': deduplicated_count,
            'significant_variant_count': significant_count,
            'returned_top_n': len(selected_hits),
            'top_hits': selected_hits,
            'scan_summary': {
                'covariate_mode': covariate_mode,
                'categorical_covariates': categorical_covariates or [],
                'numeric_covariates': numeric_covariates or [],
                'stratify_by': stratify_by or [],
                'sv_type': sv_type,
                'chromosomes': sorted(chromosome_set) if chromosome_set else [],
                'result_mode': 'compact' if compact_hits else 'detailed',
                'raw_association_count': raw_association_count,
                'note': 'P 值使用解析型相关检验，适合全基因组候选扫描；不等同于个体级 GWAS。',
            },
        }

    def _resolve_task_path(self, source: Any, path: str) -> Any:
        current = source
        if not path:
            return current
        for part in path.split('.'):
            if isinstance(current, list):
                try:
                    current = current[int(part)]
                except (ValueError, IndexError):
                    raise KeyError(f'无法在列表中解析路径片段: {part}')
            elif isinstance(current, dict):
                if part not in current:
                    raise KeyError(f'无法在字典中解析路径片段: {part}')
                current = current[part]
            else:
                raise KeyError(f'路径在非容器对象处中断: {part}')
        return current

    def _resolve_task_value(self, value: Any, step_results: Dict[str, Any]) -> Any:
        if isinstance(value, dict):
            if '$ref' in value:
                ref = str(value['$ref']).strip()
                if not ref:
                    raise KeyError('空的 $ref')
                step_id, _, path = ref.partition('.')
                if step_id not in step_results:
                    raise KeyError(f'未找到引用步骤: {step_id}')
                return self._resolve_task_path(step_results[step_id], path)
            return {key: self._resolve_task_value(sub_value, step_results) for key, sub_value in value.items()}
        if isinstance(value, list):
            return [self._resolve_task_value(item, step_results) for item in value]
        return value

    def _evaluate_task_condition(self, condition: Any, context: Dict[str, Any]) -> bool:
        if condition is None:
            return True
        resolved = self._resolve_task_value(condition, context)
        if isinstance(resolved, bool):
            return resolved
        if not isinstance(resolved, dict):
            return bool(resolved)
        if 'all' in resolved:
            return all(self._evaluate_task_condition(item, context) for item in resolved['all'])
        if 'any' in resolved:
            return any(self._evaluate_task_condition(item, context) for item in resolved['any'])
        if 'not' in resolved:
            return not self._evaluate_task_condition(resolved['not'], context)

        left = resolved.get('left')
        right = resolved.get('right')
        op = str(resolved.get('op', 'truthy')).lower()

        if op == 'exists':
            return left is not None
        if op == 'truthy':
            return bool(left)
        if op == 'eq':
            return left == right
        if op == 'ne':
            return left != right
        if op == 'gt':
            return left > right
        if op == 'ge':
            return left >= right
        if op == 'lt':
            return left < right
        if op == 'le':
            return left <= right
        if op == 'contains':
            return right in left if left is not None else False
        if op == 'in':
            return left in right if right is not None else False
        if op == 'not_empty':
            return left is not None and len(left) > 0
        raise ValueError(f'不支持的条件操作符: {op}')

    def _project_task_fields(self, target: Any, project_fields: List[Any]) -> Any:
        if not project_fields:
            return target

        def project_record(record: Any) -> Dict[str, Any]:
            output: Dict[str, Any] = {}
            for field in project_fields:
                if isinstance(field, str):
                    field_path = field
                    field_name = field.split('.')[-1]
                else:
                    field_path = field.get('path')
                    field_name = field.get('name') or str(field_path).split('.')[-1]
                if not field_path:
                    continue
                try:
                    output[field_name] = self._resolve_task_path(record, field_path)
                except KeyError:
                    output[field_name] = None
            return output

        if isinstance(target, list):
            return [project_record(item) for item in target]
        if isinstance(target, dict):
            return project_record(target)
        return target

    def _sort_task_target(self, target: Any, sort_spec: Any) -> Any:
        if not isinstance(target, list) or not sort_spec:
            return target
        specs = sort_spec if isinstance(sort_spec, list) else [sort_spec]
        sorted_target = list(target)

        for spec in reversed(specs):
            if isinstance(spec, str):
                path = spec
                reverse = False
            else:
                path = spec.get('path')
                reverse = str(spec.get('order', 'asc')).lower() == 'desc'
            if not path:
                continue

            def key_fn(item: Any) -> Tuple[int, Any]:
                try:
                    value = self._resolve_task_path(item, path)
                except KeyError:
                    value = None
                if value is None:
                    return (1, float('inf'))
                return (0, value)

            sorted_target = sorted(sorted_target, key=key_fn, reverse=reverse)
        return sorted_target

    def _transform_task_result(self, result: Dict[str, Any], transform: Optional[Dict[str, Any]], step_results: Dict[str, Any]) -> Dict[str, Any]:
        if not transform:
            return result

        resolved_transform = self._resolve_task_value(transform, step_results)
        target_path = resolved_transform.get('path', '')
        target = self._resolve_task_path(result, target_path) if target_path else result
        target = self._sort_task_target(target, resolved_transform.get('sort'))

        offset = int(resolved_transform.get('offset', 0) or 0)
        limit = resolved_transform.get('limit')
        if isinstance(target, list):
            if limit is not None:
                target = target[offset:offset + int(limit)]
            elif offset:
                target = target[offset:]

        target = self._project_task_fields(target, resolved_transform.get('project', []))

        transformed = dict(result)
        transformed['transform_applied'] = resolved_transform
        transformed['transformed_result'] = target
        return transformed

    def _build_task_step_summary(self, tool_name: str, result: Dict[str, Any]) -> Dict[str, Any]:
        if tool_name == 'get_database_info':
            return {
                'info_type': result.get('info_type'),
                'success': result.get('success', False),
            }
        if tool_name == 'query_breed_profile':
            return {
                'query_type': result.get('query_type'),
                'matched_count': result.get('matched_count', 0),
                'returned_count': result.get('returned_count', 0),
            }
        if tool_name == 'query_sv':
            return {
                'query_type': result.get('query_type'),
                'total_results': result.get('total_results', 0),
                'total_queries': result.get('query_summary', {}).get('total_queries', 0),
            }
        if tool_name == 'query_annotation':
            return {
                'query_type': result.get('query_type'),
                'total_results': result.get('total_results', 0),
            }
        if tool_name == 'analyze_breed_association':
            return {
                'analysis_type': result.get('analysis_type'),
                'phenotype_name': result.get('phenotype_name'),
                'analysis_level': result.get('analysis_level'),
                'tested_variant_count': result.get('tested_variant_count'),
                'tested_gene_count': result.get('tested_gene_count'),
                'returned_top_n': result.get('returned_top_n'),
            }
        return {'success': result.get('success', False)}

    def _dispatch_task_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        if tool_name == 'get_database_info':
            return self.get_database_info(
                info_type=arguments.get('info_type', 'overview'),
                database_name=arguments.get('database_name'),
            )
        if tool_name == 'query_breed_profile':
            return self.query_breed_profile(
                breed_names=arguments.get('breed_names') or arguments.get('breeds'),
                exact_match=arguments.get('exact_match', False),
                max_results=arguments.get('max_results', 20),
                include_trait_values=arguments.get('include_trait_values', True),
            )
        if tool_name == 'query_sv':
            return self.query_sv(
                query_type=arguments.get('query_type', 'region'),
                genes=arguments.get('genes'),
                window=arguments.get('window', 0),
                upstream=arguments.get('upstream'),
                downstream=arguments.get('downstream'),
                regions=arguments.get('regions'),
                chromosome=arguments.get('chromosome'),
                start_pos=arguments.get('start_pos'),
                end_pos=arguments.get('end_pos'),
                sv_ids=arguments.get('sv_ids'),
                filters=arguments.get('filters'),
                sv_type=arguments.get('sv_type'),
                database_name=arguments.get('database_name'),
                search_all_databases=arguments.get('search_all_databases', False),
                include_annotation=arguments.get('include_annotation', True),
                max_results=arguments.get('max_results', 100),
                breeds=arguments.get('breeds'),
                include_all_breeds=arguments.get('include_all_breeds', False),
            )
        if tool_name == 'query_annotation':
            return self.query_annotation_v2(
                query_type=arguments.get('query_type', 'search'),
                queries=arguments.get('queries'),
                exact_match=arguments.get('exact_match', False),
                regions=arguments.get('regions'),
                chromosome=arguments.get('chromosome'),
                start_pos=arguments.get('start_pos'),
                end_pos=arguments.get('end_pos'),
                positions=arguments.get('positions'),
                max_results=arguments.get('max_results', 50),
            )
        if tool_name == 'analyze_breed_association':
            return self.analyze_breed_association(
                analysis_type=arguments.get('analysis_type', 'phenotype_overview'),
                phenotype_name=arguments.get('phenotype_name'),
                genes=arguments.get('genes'),
                window=arguments.get('window', 0),
                upstream=arguments.get('upstream'),
                downstream=arguments.get('downstream'),
                regions=arguments.get('regions'),
                chromosome=arguments.get('chromosome'),
                start_pos=arguments.get('start_pos'),
                end_pos=arguments.get('end_pos'),
                sv_ids=arguments.get('sv_ids'),
                sv_type=arguments.get('sv_type'),
                database_name=arguments.get('database_name'),
                search_all_databases=arguments.get('search_all_databases', False),
                include_annotation=arguments.get('include_annotation', True),
                method=arguments.get('method', 'auto'),
                aggregate_method=arguments.get('aggregate_method', 'mean'),
                covariate_mode=arguments.get('covariate_mode', 'none'),
                categorical_covariates=arguments.get('categorical_covariates'),
                numeric_covariates=arguments.get('numeric_covariates'),
                stratify_by=arguments.get('stratify_by'),
                min_breeds=arguments.get('min_breeds', 8),
                min_stratum_breeds=arguments.get('min_stratum_breeds', 4),
                max_variants=arguments.get('max_variants', 100),
                top_n=arguments.get('top_n', 20),
                permutations=arguments.get('permutations', 200),
                random_seed=arguments.get('random_seed', 42),
            )
        if tool_name == 'genome_wide_association_scan':
            return self.genome_wide_association_scan(
                phenotype_name=arguments.get('phenotype_name'),
                method=arguments.get('method', 'auto'),
                covariate_mode=arguments.get('covariate_mode', 'none'),
                categorical_covariates=arguments.get('categorical_covariates'),
                numeric_covariates=arguments.get('numeric_covariates'),
                stratify_by=arguments.get('stratify_by'),
                min_breeds=arguments.get('min_breeds', 8),
                min_stratum_breeds=arguments.get('min_stratum_breeds', 4),
                database_name=arguments.get('database_name'),
                search_all_databases=arguments.get('search_all_databases', False),
                sv_type=arguments.get('sv_type'),
                chromosomes=arguments.get('chromosomes'),
                include_annotation=arguments.get('include_annotation', True),
                top_n=arguments.get('top_n', 20),
                rank_by=arguments.get('rank_by', 'p_value'),
                sort_order=arguments.get('sort_order', 'asc'),
                min_abs_correlation=arguments.get('min_abs_correlation'),
            )
        return {'success': False, 'error': f'不支持的任务工具: {tool_name}'}

    def run_analysis_task(
        self,
        task_name: str = 'analysis_task',
        description: Optional[str] = None,
        steps: Optional[List[Dict[str, Any]]] = None,
        stop_on_error: bool = True,
    ) -> Dict[str, Any]:
        if not steps:
            return {'success': False, 'error': '请提供 steps 参数'}

        try:
            step_results: Dict[str, Any] = {}
            execution_log: List[Dict[str, Any]] = []

            for index, step in enumerate(steps, start=1):
                step_id = str(step.get('id') or f'step_{index}')
                tool_name = str(step.get('tool') or '').strip()
                if not tool_name:
                    return {'success': False, 'error': f'第 {index} 步缺少 tool 字段'}
                if tool_name not in self.TASK_TOOL_WHITELIST:
                    return {'success': False, 'error': f'第 {index} 步使用了未授权工具: {tool_name}'}
                if step_id in step_results:
                    return {'success': False, 'error': f'步骤 id 重复: {step_id}'}

                if not self._evaluate_task_condition(step.get('when'), step_results):
                    skipped_result = {'success': True, 'skipped': True, 'skip_reason': 'condition_not_met'}
                    step_results[step_id] = skipped_result
                    execution_log.append({
                        'id': step_id,
                        'tool': tool_name,
                        'success': True,
                        'skipped': True,
                        'summary': {'reason': 'condition_not_met'},
                    })
                    continue

                raw_arguments = step.get('arguments') or {}
                resolved_arguments = self._resolve_task_value(raw_arguments, step_results)
                result = self._dispatch_task_tool(tool_name, resolved_arguments)
                result = self._transform_task_result(result, step.get('transform'), step_results)
                step_results[step_id] = result

                execution_item = {
                    'id': step_id,
                    'tool': tool_name,
                    'success': bool(result.get('success', True)),
                    'arguments': resolved_arguments,
                    'summary': self._build_task_step_summary(tool_name, result),
                }
                if not execution_item['success']:
                    execution_item['error'] = result.get('error')
                execution_log.append(execution_item)

                if not execution_item['success'] and stop_on_error:
                    return {
                        'success': False,
                        'task_name': task_name,
                        'description': description,
                        'failed_step': step_id,
                        'execution_log': execution_log,
                        'step_results': step_results,
                        'error': result.get('error', f'步骤失败: {step_id}'),
                    }

            final_step_id = execution_log[-1]['id'] if execution_log else None
            return {
                'success': True,
                'task_name': task_name,
                'description': description,
                'step_count': len(execution_log),
                'stop_on_error': stop_on_error,
                'available_tools': sorted(self.TASK_TOOL_WHITELIST),
                'execution_log': execution_log,
                'step_results': step_results,
                'final_step_id': final_step_id,
                'final_result': step_results.get(final_step_id) if final_step_id else None,
            }
        except Exception as exc:
            return {'success': False, 'task_name': task_name, 'description': description, 'error': str(exc)}

    def _evaluate_association_rows(
        self,
        rows: List[Dict[str, Any]],
        method: str,
        covariate_mode: str,
        categorical_covariates: Optional[List[str]],
        numeric_covariates: Optional[List[str]],
        stratify_by: Optional[List[str]],
        min_breeds: int,
        min_stratum_breeds: int,
        permutations: int,
        rng: np.random.Generator,
    ) -> Optional[Dict[str, Any]]:
        selected_method = self._select_analysis_method(method, np.array([row['sample_size'] for row in rows], dtype=float))
        categorical_fields = self._resolve_covariate_fields(categorical_covariates)
        numeric_fields = self._resolve_covariate_fields(numeric_covariates)
        stratify_fields = self._resolve_covariate_fields(stratify_by)

        working_rows = rows
        x_original = np.array([row['frequency'] for row in working_rows], dtype=float)
        y_original = np.array([row['phenotype_value'] for row in working_rows], dtype=float)
        weights_original = np.array([row['sample_size'] for row in working_rows], dtype=float)
        covariate_control = {'mode': covariate_mode, 'categorical_covariates': categorical_fields, 'numeric_covariates': numeric_fields, 'stratify_by': stratify_fields}
        stratum_results = []

        if covariate_mode == 'adjust':
            required_fields = categorical_fields + numeric_fields
            working_rows = self._filter_rows_by_fields(rows, required_fields)
            if len(working_rows) < min_breeds:
                return None
            design, summary = self._build_design_matrix(working_rows, numeric_fields, categorical_fields)
            x = np.array([row['frequency'] for row in working_rows], dtype=float)
            y = np.array([row['phenotype_value'] for row in working_rows], dtype=float)
            weights = np.array([row['sample_size'] for row in working_rows], dtype=float)
            x_used = self._weighted_residualize(x, design, weights)
            y_used = self._weighted_residualize(y, design, weights)
            covariate_control['applied_design'] = summary
        elif covariate_mode == 'stratify':
            if not stratify_fields:
                return None
            working_rows = self._filter_rows_by_fields(rows, stratify_fields)
            if len(working_rows) < min_breeds:
                return None
            group_keys = [tuple(row[field] for field in stratify_fields) for row in working_rows]
            counts = pd.Series(group_keys).value_counts().to_dict()
            filtered_pairs = [(row, group) for row, group in zip(working_rows, group_keys) if counts.get(group, 0) >= min_stratum_breeds]
            if len(filtered_pairs) < min_breeds:
                return None
            working_rows = [pair[0] for pair in filtered_pairs]
            group_keys = [pair[1] for pair in filtered_pairs]
            x = np.array([row['frequency'] for row in working_rows], dtype=float)
            y = np.array([row['phenotype_value'] for row in working_rows], dtype=float)
            weights = np.array([row['sample_size'] for row in working_rows], dtype=float)
            x_used = self._within_group_residualize(x, group_keys, weights)
            y_used = self._within_group_residualize(y, group_keys, weights)
            stratum_results = self._compute_stratum_results(working_rows, group_keys, selected_method, min_stratum_breeds)
        else:
            if len(working_rows) < min_breeds:
                return None
            x_used = x_original
            y_used = y_original
            weights = weights_original

        if covariate_mode != 'stratify':
            weights = np.array([row['sample_size'] for row in working_rows], dtype=float)

        stat = self._compute_association_stat(x_used, y_used, selected_method, weights)
        if np.isnan(stat):
            return None

        p_value = self._permutation_p_value(x_used, y_used, selected_method, stat, weights, permutations, rng)
        effect_direction = self._resolve_effect_direction(stat)
        return {
            'correlation': round(float(stat), 6),
            'effect_direction': effect_direction,
            'method': selected_method,
            'n_breeds': len(working_rows),
            'p_value': round(p_value, 6) if p_value is not None else None,
            'matched_breeds': [row['breed'] for row in working_rows],
            'top_breeds_by_frequency': sorted(working_rows, key=lambda item: item['frequency'], reverse=True)[:3],
            'top_breeds_by_phenotype': sorted(working_rows, key=lambda item: item['phenotype_value'], reverse=True)[:3],
            'covariate_control': covariate_control,
            'stratified_results': stratum_results,
            'stratified_results_overview': self._build_stratified_results_overview(stratum_results),
        }

    def _analyze_variant_associations(
        self,
        variants: List[Dict[str, Any]],
        phenotype_name: str,
        method: str,
        covariate_mode: str,
        categorical_covariates: Optional[List[str]],
        numeric_covariates: Optional[List[str]],
        stratify_by: Optional[List[str]],
        min_breeds: int,
        min_stratum_breeds: int,
        permutations: int,
        top_n: int,
        random_seed: int,
    ) -> Dict[str, Any]:
        resolved_phenotype = self._resolve_phenotype_name(phenotype_name)
        if not resolved_phenotype:
            return {'success': False, 'error': f'未找到数值型表型: {phenotype_name}'}

        associations: List[Dict[str, Any]] = []
        rng = np.random.default_rng(random_seed)

        for variant in variants:
            breed_frequencies = variant.get('breed_frequencies') or {}
            aligned = self._build_breed_aligned_arrays(breed_frequencies, resolved_phenotype)
            eval_result = self._evaluate_association_rows(
                rows=aligned['rows'],
                method=method,
                covariate_mode=covariate_mode,
                categorical_covariates=categorical_covariates,
                numeric_covariates=numeric_covariates,
                stratify_by=stratify_by,
                min_breeds=min_breeds,
                min_stratum_breeds=min_stratum_breeds,
                permutations=permutations,
                rng=rng,
            )
            if not eval_result:
                continue

            associations.append({
                'sv_id': variant.get('ID'),
                'database': variant.get('database'),
                'gene': variant.get('Gene'),
                'gene_name': variant.get('Gene_Name'),
                'chromosome': variant.get('Chr'),
                'position': variant.get('POS'),
                'end': variant.get('End'),
                'sv_type': variant.get('SV_Type'),
                'mean_frequency': variant.get('Mean_fre'),
                **eval_result,
            })

        self._apply_bh_fdr(associations, score_field='correlation')
        self._attach_display_fields(associations, score_field='correlation', label_field='sv_id')
        return {
            'success': True,
            'phenotype_name': resolved_phenotype,
            'tested_variants': len(associations),
            'top_associations': associations[:top_n],
        }

    def _aggregate_breed_frequencies(self, variants: List[Dict[str, Any]], aggregate_method: str) -> Dict[str, float]:
        by_breed: Dict[str, List[float]] = {}
        for variant in variants:
            for breed, value in (variant.get('breed_frequencies') or {}).items():
                by_breed.setdefault(breed, []).append(float(value))

        aggregated: Dict[str, float] = {}
        for breed, values in by_breed.items():
            arr = np.array(values, dtype=float)
            if aggregate_method == 'max':
                aggregated[breed] = float(np.max(arr))
            elif aggregate_method == 'sum':
                aggregated[breed] = float(np.sum(arr))
            else:
                aggregated[breed] = float(np.mean(arr))
        return aggregated

    def _analyze_gene_level_associations(
        self,
        gene_variants: List[Dict[str, Any]],
        phenotype_name: str,
        method: str,
        covariate_mode: str,
        categorical_covariates: Optional[List[str]],
        numeric_covariates: Optional[List[str]],
        stratify_by: Optional[List[str]],
        min_breeds: int,
        min_stratum_breeds: int,
        permutations: int,
        top_n: int,
        random_seed: int,
        aggregate_method: str,
    ) -> Dict[str, Any]:
        resolved_phenotype = self._resolve_phenotype_name(phenotype_name)
        if not resolved_phenotype:
            return {'success': False, 'error': f'未找到数值型表型: {phenotype_name}'}

        associations: List[Dict[str, Any]] = []
        rng = np.random.default_rng(random_seed)

        for gene_entry in gene_variants:
            aggregated_frequencies = self._aggregate_breed_frequencies(gene_entry['variants'], aggregate_method)
            aligned = self._build_breed_aligned_arrays(aggregated_frequencies, resolved_phenotype)
            eval_result = self._evaluate_association_rows(
                rows=aligned['rows'],
                method=method,
                covariate_mode=covariate_mode,
                categorical_covariates=categorical_covariates,
                numeric_covariates=numeric_covariates,
                stratify_by=stratify_by,
                min_breeds=min_breeds,
                min_stratum_breeds=min_stratum_breeds,
                permutations=permutations,
                rng=rng,
            )
            if not eval_result:
                continue

            associations.append({
                'gene_query': gene_entry['gene_query'],
                'gene_name': gene_entry['gene_name'],
                'gene_id': gene_entry['gene_id'],
                'chromosome': gene_entry['chromosome'],
                'search_region': gene_entry['search_region'],
                'variant_count': len(gene_entry['variants']),
                'aggregate_method': aggregate_method,
                'aggregate_score': eval_result['correlation'],
                'top_variant_ids': [variant.get('ID') for variant in gene_entry['variants'][:5]],
                **{key: value for key, value in eval_result.items() if key != 'correlation'},
            })

        self._apply_bh_fdr(associations, score_field='aggregate_score')
        self._attach_display_fields(associations, score_field='aggregate_score', label_field='gene_name')
        return {
            'success': True,
            'phenotype_name': resolved_phenotype,
            'tested_genes': len(associations),
            'top_gene_associations': associations[:top_n],
        }

    def _get_variants_for_gene_targets(
        self,
        genes: List[str],
        window: int,
        upstream: Optional[int],
        downstream: Optional[int],
        sv_type: Optional[str],
        database_name: Optional[str],
        search_all_databases: bool,
        include_annotation: bool,
        max_variants: int,
    ) -> List[Dict[str, Any]]:
        variants: List[Dict[str, Any]] = []
        if not self.annotation:
            return variants

        up = upstream if upstream is not None else window
        down = downstream if downstream is not None else window

        for gene_query in genes:
            gene_info = self.annotation.get_gene_annotation(gene_query)
            if not gene_info:
                search_res = self.annotation.search_gene(gene_query, exact_match=True)
                gene_info = search_res[0] if search_res else None
            if not gene_info:
                continue

            search_start = max(1, gene_info['start'] - up)
            search_end = gene_info['end'] + down
            sv_res = self._search_sv_by_region(
                chromosome=gene_info['chromosome'],
                start_pos=search_start,
                end_pos=search_end,
                max_results=max_variants,
                database_name=database_name,
                search_all=search_all_databases,
                sv_type=sv_type,
                include_annotation=include_annotation,
                include_all_breeds=True,
            )
            if sv_res['success']:
                variants.extend(sv_res['results'])
        return variants

    def _get_gene_variant_groups(
        self,
        genes: List[str],
        window: int,
        upstream: Optional[int],
        downstream: Optional[int],
        sv_type: Optional[str],
        database_name: Optional[str],
        search_all_databases: bool,
        include_annotation: bool,
        max_variants: int,
    ) -> List[Dict[str, Any]]:
        groups: List[Dict[str, Any]] = []
        if not self.annotation:
            return groups

        up = upstream if upstream is not None else window
        down = downstream if downstream is not None else window

        for gene_query in genes:
            gene_info = self.annotation.get_gene_annotation(gene_query)
            if not gene_info:
                search_res = self.annotation.search_gene(gene_query, exact_match=True)
                gene_info = search_res[0] if search_res else None
            if not gene_info:
                continue

            search_start = max(1, gene_info['start'] - up)
            search_end = gene_info['end'] + down
            sv_res = self._search_sv_by_region(
                chromosome=gene_info['chromosome'],
                start_pos=search_start,
                end_pos=search_end,
                max_results=max_variants,
                database_name=database_name,
                search_all=search_all_databases,
                sv_type=sv_type,
                include_annotation=include_annotation,
                include_all_breeds=True,
            )
            if sv_res['success'] and sv_res['results']:
                groups.append({
                    'gene_query': gene_query,
                    'gene_name': gene_info.get('name') or gene_query,
                    'gene_id': gene_info.get('gene_id'),
                    'chromosome': gene_info.get('chromosome'),
                    'search_region': f"{gene_info['chromosome']}:{search_start}-{search_end}",
                    'variants': self._deduplicate_variants(sv_res['results'], max_variants),
                })
        return groups

    def _get_variants_for_region_targets(
        self,
        regions: List[Dict[str, Any]],
        sv_type: Optional[str],
        database_name: Optional[str],
        search_all_databases: bool,
        include_annotation: bool,
        max_variants: int,
    ) -> List[Dict[str, Any]]:
        variants: List[Dict[str, Any]] = []
        for region in regions:
            sv_res = self._search_sv_by_region(
                chromosome=region['chromosome'],
                start_pos=region['start'],
                end_pos=region['end'],
                max_results=max_variants,
                database_name=database_name,
                search_all=search_all_databases,
                sv_type=sv_type,
                include_annotation=include_annotation,
                include_all_breeds=True,
            )
            if sv_res['success']:
                variants.extend(sv_res['results'])
        return variants

    def _deduplicate_variants(self, variants: List[Dict[str, Any]], max_variants: int) -> List[Dict[str, Any]]:
        seen = set()
        deduplicated = []
        for variant in variants:
            key = (variant.get('database'), variant.get('ID'))
            if key in seen:
                continue
            seen.add(key)
            deduplicated.append(variant)
            if len(deduplicated) >= max_variants:
                break
        return deduplicated

    def _display_db_name(self, internal_name: Optional[str]) -> str:
        """对外展示名：屏蔽底层数据文件名/路径，统一为业务名称。"""
        base = "鸡基因组结构变异(SV)数据库"
        if not internal_name or len(self.database_names) <= 1:
            return base
        try:
            idx = self.database_names.index(internal_name) + 1
            return f"{base}{idx}"
        except ValueError:
            return base

    def get_database_info(self, info_type: str = 'overview', database_name: Optional[str] = None) -> Dict[str, Any]:
        try:
            result: Dict[str, Any] = {'success': True, 'info_type': info_type}

            if info_type == 'overview':
                result['databases'] = [
                    {'name': self._display_db_name(name), 'records': len(self.databases[name]), 'is_current': name == self.current_database}
                    for name in self.database_names
                ]
                result['current_database'] = self._display_db_name(self.current_database)
                result['total_databases'] = len(self.databases)
                result['current_stats'] = {
                    'total_records': len(self.df),
                    'chromosomes': sorted([str(c) for c in self.df['Chr'].unique()]),
                    'sv_types': list(self.df['SV_Type'].unique()) if 'SV_Type' in self.df.columns else [],
                }
                result['annotation'] = {
                    'loaded': bool(self.annotation),
                    'total_genes': self.annotation.get_statistics()['total_genes'] if self.annotation else 0,
                }
                result['phenotype'] = self._get_current_phenotype_summary()

            elif info_type == 'databases':
                result['databases'] = []
                for name in self.database_names:
                    df = self.databases[name]
                    breed_columns = self._get_breed_columns(df)
                    result['databases'].append({
                        'name': self._display_db_name(name),
                        'records': len(df),
                        'columns': list(df.columns),
                        'breed_columns': breed_columns,
                        'num_breeds': len(breed_columns),
                    })

            elif info_type == 'structure':
                target = database_name if database_name in self.databases else self.current_database
                df = self.databases[target]
                result['database'] = self._display_db_name(target)
                result['total_columns'] = len(df.columns)
                result['all_column_names'] = list(df.columns)
                result['columns'] = [
                    {'name': col, 'dtype': str(df[col].dtype), 'non_null': int(df[col].notna().sum())}
                    for col in df.columns[:15]
                ]
                result['sample_data'] = df.head(3).to_dict('records')

            elif info_type == 'statistics':
                target = database_name if database_name in self.databases else self.current_database
                df = self.databases[target]
                result['database'] = self._display_db_name(target)
                result['total_records'] = len(df)
                result['by_chromosome'] = {str(k): int(v) for k, v in df['Chr'].value_counts().to_dict().items()}
                if 'SV_Type' in df.columns:
                    result['by_sv_type'] = {str(k): int(v) for k, v in df['SV_Type'].value_counts().to_dict().items()}
                result['position_range'] = {'min': int(df['POS'].min()), 'max': int(df['POS'].max())}
                if 'Mean_fre' in df.columns:
                    result['frequency_stats'] = {
                        'min': round(float(df['Mean_fre'].min()), 4),
                        'max': round(float(df['Mean_fre'].max()), 4),
                        'mean': round(float(df['Mean_fre'].mean()), 4),
                    }
                result['phenotype'] = self._get_current_phenotype_summary()
                result['phenotype_distribution'] = self._get_phenotype_distribution_summary()

            elif info_type == 'breeds':
                target = database_name if database_name in self.databases else self.current_database
                df = self.databases[target]
                breed_cols = self._get_breed_columns(df)
                result['database'] = target
                result['total_breeds'] = len(breed_cols)
                result['breeds'] = breed_cols

            elif info_type == 'phenotypes':
                result['phenotype'] = self._get_current_phenotype_summary()
                result['all_traits'] = self.phenotype_all_traits
                result['metadata_traits'] = self.phenotype_metadata_traits
                result['numeric_traits'] = self.phenotype_numeric_traits
                result['categorical_traits'] = self.phenotype_categorical_traits
                result['covariates_available'] = ['驯化程度分类', '用途分类', '纬度', '经度']
                result['breed_profile_available'] = True
                result['breed_profile_sections'] = ['metadata', 'location', 'morphology', 'climate', 'numeric_traits', 'categorical_traits', 'trait_values']
                result['breed_examples'] = list(self.phenotype_by_breed.keys())[:10]
                result['alias_examples'] = [
                    {'breed': breed, 'alias': info.get('alias')}
                    for breed, info in list(self.phenotype_by_breed.items())[:10]
                    if info.get('alias')
                ]

            else:
                return {'success': False, 'error': f'未知的 info_type: {info_type}'}

            return result
        except Exception as exc:
            return {'success': False, 'error': str(exc)}

    def query_sv(
        self,
        query_type: str = 'region',
        genes: Optional[List[str]] = None,
        window: int = 0,
        upstream: Optional[int] = None,
        downstream: Optional[int] = None,
        regions: Optional[List[Dict[str, Any]]] = None,
        chromosome: Optional[str] = None,
        start_pos: Optional[int] = None,
        end_pos: Optional[int] = None,
        sv_ids: Optional[List[str]] = None,
        filters: Optional[List[Dict[str, Any]]] = None,
        sv_type: Optional[str] = None,
        database_name: Optional[str] = None,
        search_all_databases: bool = False,
        include_annotation: bool = True,
        max_results: int = 100,
        breeds: Optional[List[str]] = None,
        include_all_breeds: bool = False,
    ) -> Dict[str, Any]:
        try:
            results: Dict[str, Any] = {'success': True, 'query_type': query_type, 'results_by_query': [], 'total_results': 0}
            up = upstream if upstream is not None else window
            down = downstream if downstream is not None else window

            if query_type == 'gene':
                if not genes:
                    return {'success': False, 'error': '请提供 genes 参数'}
                if not self.annotation:
                    return {'success': False, 'error': '注释数据未加载'}

                for gene_query in genes:
                    gene_result = {'query': gene_query, 'query_type': 'gene', 'gene_info': None, 'sv_count': 0, 'sv_results': []}
                    gene_info = self.annotation.get_gene_annotation(gene_query)
                    if not gene_info:
                        search_res = self.annotation.search_gene(gene_query, exact_match=True)
                        gene_info = search_res[0] if search_res else None
                    if not gene_info:
                        gene_result['error'] = f'未找到基因: {gene_query}'
                        results['results_by_query'].append(gene_result)
                        continue

                    gene_result['gene_info'] = {key: gene_info.get(key) for key in ['gene_id', 'name', 'chromosome', 'start', 'end', 'strand', 'biotype']}
                    search_start = max(1, gene_info['start'] - up)
                    search_end = gene_info['end'] + down
                    gene_result['search_region'] = f"{gene_info['chromosome']}:{search_start}-{search_end}"
                    gene_result['window_applied'] = {'upstream': up, 'downstream': down}

                    sv_res = self._search_sv_by_region(
                        gene_info['chromosome'],
                        search_start,
                        search_end,
                        max_results,
                        database_name,
                        search_all_databases,
                        sv_type,
                        include_annotation,
                        breeds,
                        include_all_breeds,
                    )
                    if sv_res['success']:
                        gene_result['sv_count'] = sv_res['count']
                        gene_result['sv_results'] = sv_res['results']
                        results['total_results'] += sv_res['count']
                    results['results_by_query'].append(gene_result)

            elif query_type == 'region':
                region_list = regions or ([{'chromosome': chromosome, 'start': start_pos, 'end': end_pos}] if chromosome else [])
                if not region_list:
                    return {'success': False, 'error': '请提供 regions 或 chromosome/start_pos/end_pos'}

                for region in region_list:
                    region_result = {'query': f"{region['chromosome']}:{region['start']}-{region['end']}", 'query_type': 'region', 'sv_count': 0, 'sv_results': []}
                    sv_res = self._search_sv_by_region(
                        region['chromosome'],
                        region['start'],
                        region['end'],
                        max_results,
                        database_name,
                        search_all_databases,
                        sv_type,
                        include_annotation,
                        breeds,
                        include_all_breeds,
                    )
                    if sv_res['success']:
                        region_result['sv_count'] = sv_res['count']
                        region_result['sv_results'] = sv_res['results']
                        results['total_results'] += sv_res['count']
                    results['results_by_query'].append(region_result)

            elif query_type == 'id':
                if not sv_ids:
                    return {'success': False, 'error': '请提供 sv_ids 参数'}

                for sv_id in sv_ids:
                    id_result = {'query': sv_id, 'query_type': 'id', 'found': False, 'sv_detail': None}
                    detail = self._get_sv_detail(sv_id, database_name, search_all_databases)
                    if detail['success']:
                        id_result['found'] = True
                        id_result['sv_detail'] = detail['detail']
                        results['total_results'] += 1
                    else:
                        id_result['error'] = detail.get('error')
                    results['results_by_query'].append(id_result)

            elif query_type == 'filter':
                filter_result = {'query': 'custom_filter', 'query_type': 'filter', 'sv_count': 0, 'sv_results': []}
                target = database_name if database_name in self.databases else self.current_database
                df = self.databases[target].copy()

                if filters:
                    for current_filter in filters:
                        col, op, val = current_filter.get('column'), current_filter.get('op', '='), current_filter.get('value')
                        if col not in df.columns:
                            continue
                        if op == '=':
                            df = df[df[col] == val]
                        elif op == '!=':
                            df = df[df[col] != val]
                        elif op == '>':
                            df = df[df[col] > val]
                        elif op == '<':
                            df = df[df[col] < val]
                        elif op == '>=':
                            df = df[df[col] >= val]
                        elif op == '<=':
                            df = df[df[col] <= val]
                        elif op == 'in':
                            df = df[df[col].isin(val if isinstance(val, list) else [val])]
                        elif op == 'contains':
                            df = df[df[col].astype(str).str.contains(str(val), case=False, na=False)]

                if sv_type and 'SV_Type' in df.columns:
                    df = df[df['SV_Type'].astype(str).str.upper() == sv_type.upper()]

                breed_cols = self._get_breed_columns(df)
                records = [
                    self._build_variant_result(row, target, breed_cols, include_annotation, breeds, include_all_breeds)
                    for _, row in df.head(max_results).iterrows()
                ]
                filter_result['sv_count'] = len(records)
                filter_result['sv_results'] = records
                results['total_results'] = len(records)
                results['results_by_query'].append(filter_result)

            else:
                return {'success': False, 'error': f'未知的 query_type: {query_type}'}

            results['query_summary'] = {
                'total_queries': len(results['results_by_query']),
                'total_results': results['total_results'],
                'sv_type_filter': sv_type,
                'database': database_name or self.current_database,
                'breeds_filter': breeds,
                'include_all_breeds': include_all_breeds,
            }
            return results
        except Exception as exc:
            return {'success': False, 'error': str(exc)}

    def query_annotation_v2(
        self,
        query_type: str = 'search',
        queries: Optional[List[str]] = None,
        exact_match: bool = False,
        regions: Optional[List[Dict[str, Any]]] = None,
        chromosome: Optional[str] = None,
        start_pos: Optional[int] = None,
        end_pos: Optional[int] = None,
        positions: Optional[List[Dict[str, Any]]] = None,
        max_results: int = 50,
    ) -> Dict[str, Any]:
        if not self.annotation:
            return {'success': False, 'error': '注释数据未加载'}

        try:
            results: Dict[str, Any] = {'success': True, 'query_type': query_type, 'results_by_query': [], 'total_results': 0}

            if query_type == 'search':
                if not queries:
                    return {'success': False, 'error': '请提供 queries 参数'}
                for query in queries:
                    found = self.annotation.search_gene(query, exact_match=exact_match, limit=max_results)
                    results['results_by_query'].append({
                        'query': query,
                        'query_type': 'search',
                        'genes_found': len(found),
                        'genes': found,
                    })
                    results['total_results'] += len(found)

            elif query_type == 'region':
                region_list = regions or ([{'chromosome': chromosome, 'start': start_pos, 'end': end_pos}] if chromosome else [])
                if not region_list:
                    return {'success': False, 'error': '请提供 regions 或 chromosome/start_pos/end_pos'}
                for region in region_list:
                    found = self.annotation.get_genes_in_region(region['chromosome'], region['start'], region['end'], limit=max_results)
                    results['results_by_query'].append({
                        'query': f"{region['chromosome']}:{region['start']}-{region['end']}",
                        'query_type': 'region',
                        'genes_found': len(found),
                        'genes': found,
                    })
                    results['total_results'] += len(found)

            elif query_type == 'position':
                if not positions:
                    return {'success': False, 'error': '请提供 positions 参数'}
                for pos in positions:
                    anno = self.annotation.annotate_position(pos['chromosome'], pos['position'])
                    results['results_by_query'].append({
                        'query': f"{pos['chromosome']}:{pos['position']}",
                        'query_type': 'position',
                        'in_gene': anno['in_gene'],
                        'genes_at_position': anno['genes_at_position'],
                        'nearest_gene': anno['nearest_gene'],
                        'nearest_distance': anno.get('nearest_distance'),
                    })
                    results['total_results'] += len(anno['genes_at_position']) or (1 if anno['nearest_gene'] else 0)

            else:
                return {'success': False, 'error': f'未知的 query_type: {query_type}'}

            results['query_summary'] = {'total_queries': len(results['results_by_query']), 'total_results': results['total_results']}
            return results
        except Exception as exc:
            return {'success': False, 'error': str(exc)}

    def analyze_breed_association(
        self,
        analysis_type: str = 'phenotype_overview',
        phenotype_name: Optional[str] = None,
        genes: Optional[List[str]] = None,
        window: int = 0,
        upstream: Optional[int] = None,
        downstream: Optional[int] = None,
        regions: Optional[List[Dict[str, Any]]] = None,
        chromosome: Optional[str] = None,
        start_pos: Optional[int] = None,
        end_pos: Optional[int] = None,
        sv_ids: Optional[List[str]] = None,
        sv_type: Optional[str] = None,
        database_name: Optional[str] = None,
        search_all_databases: bool = False,
        include_annotation: bool = True,
        method: str = 'auto',
        aggregate_method: str = 'mean',
        covariate_mode: str = 'none',
        categorical_covariates: Optional[List[str]] = None,
        numeric_covariates: Optional[List[str]] = None,
        stratify_by: Optional[List[str]] = None,
        min_breeds: int = 8,
        min_stratum_breeds: int = 4,
        max_variants: int = 100,
        top_n: int = 20,
        permutations: int = 200,
        random_seed: int = 42,
    ) -> Dict[str, Any]:
        if not self.phenotype_by_breed:
            return {'success': False, 'error': '表型数据未加载'}

        try:
            if analysis_type == 'phenotype_overview':
                return {
                    'success': True,
                    'analysis_type': analysis_type,
                    'analysis_level': 'breed_aggregate',
                    'phenotype': self._get_current_phenotype_summary(),
                    'all_traits': self.phenotype_all_traits,
                    'metadata_traits': self.phenotype_metadata_traits,
                    'numeric_traits': self.phenotype_numeric_traits,
                    'categorical_traits': self.phenotype_categorical_traits,
                    'recommended_method': 'weighted_spearman',
                    'method_note': '当前数据是品种聚合频率，默认更适合使用带样本量权重的秩相关。',
                    'aggregate_methods': ['mean', 'max', 'sum'],
                    'covariate_modes': ['none', 'adjust', 'stratify'],
                    'covariates_available': ['驯化程度分类', '用途分类', '纬度', '经度'],
                }

            if covariate_mode not in {'none', 'adjust', 'stratify'}:
                return {'success': False, 'error': f'未知的 covariate_mode: {covariate_mode}'}
            if not phenotype_name:
                return {'success': False, 'error': '请提供 phenotype_name 参数'}

            variants: List[Dict[str, Any]] = []
            query_context: Dict[str, Any] = {
                'analysis_type': analysis_type,
                'covariate_mode': covariate_mode,
                'categorical_covariates': categorical_covariates or [],
                'numeric_covariates': numeric_covariates or [],
                'stratify_by': stratify_by or [],
            }

            if analysis_type == 'sv_trait':
                if not sv_ids:
                    return {'success': False, 'error': '请提供 sv_ids 参数'}
                for sv_id in sv_ids:
                    detail = self._get_sv_detail(sv_id, database_name, search_all_databases)
                    if detail['success']:
                        variants.append(detail['detail'])
                query_context['sv_ids'] = sv_ids

            elif analysis_type == 'gene_trait':
                if not genes:
                    return {'success': False, 'error': '请提供 genes 参数'}
                variants = self._get_variants_for_gene_targets(
                    genes=genes,
                    window=window,
                    upstream=upstream,
                    downstream=downstream,
                    sv_type=sv_type,
                    database_name=database_name,
                    search_all_databases=search_all_databases,
                    include_annotation=include_annotation,
                    max_variants=max_variants,
                )
                query_context.update({'genes': genes, 'window': {'upstream': upstream if upstream is not None else window, 'downstream': downstream if downstream is not None else window}})

            elif analysis_type == 'gene_summary_trait':
                if not genes:
                    return {'success': False, 'error': '请提供 genes 参数'}
                groups = self._get_gene_variant_groups(
                    genes=genes,
                    window=window,
                    upstream=upstream,
                    downstream=downstream,
                    sv_type=sv_type,
                    database_name=database_name,
                    search_all_databases=search_all_databases,
                    include_annotation=include_annotation,
                    max_variants=max_variants,
                )
                query_context.update({
                    'genes': genes,
                    'window': {'upstream': upstream if upstream is not None else window, 'downstream': downstream if downstream is not None else window},
                    'aggregate_method': aggregate_method,
                })
                analysis = self._analyze_gene_level_associations(
                    gene_variants=groups,
                    phenotype_name=phenotype_name,
                    method=method,
                    covariate_mode=covariate_mode,
                    categorical_covariates=categorical_covariates,
                    numeric_covariates=numeric_covariates,
                    stratify_by=stratify_by,
                    min_breeds=min_breeds,
                    min_stratum_breeds=min_stratum_breeds,
                    permutations=permutations,
                    top_n=top_n,
                    random_seed=random_seed,
                    aggregate_method=aggregate_method,
                )
                if not analysis['success']:
                    return analysis
                return {
                    'success': True,
                    'analysis_type': analysis_type,
                    'analysis_level': 'gene_aggregate',
                    'query_context': query_context,
                    'phenotype_name': analysis['phenotype_name'],
                    'method': method,
                    'aggregate_method': aggregate_method,
                    'tested_gene_count': analysis['tested_genes'],
                    'returned_top_n': min(top_n, len(analysis['top_gene_associations'])),
                    'top_gene_associations': analysis['top_gene_associations'],
                    'statistical_note': '这是基于基因窗口内多位点聚合频率与品种表型的相关分析，用于基因级候选优先级排序。',
                }

            elif analysis_type == 'region_trait':
                region_list = regions or ([{'chromosome': chromosome, 'start': start_pos, 'end': end_pos}] if chromosome else [])
                if not region_list:
                    return {'success': False, 'error': '请提供 regions 或 chromosome/start_pos/end_pos'}
                variants = self._get_variants_for_region_targets(
                    regions=region_list,
                    sv_type=sv_type,
                    database_name=database_name,
                    search_all_databases=search_all_databases,
                    include_annotation=include_annotation,
                    max_variants=max_variants,
                )
                query_context['regions'] = region_list

            else:
                return {'success': False, 'error': f'未知的 analysis_type: {analysis_type}'}

            variants = self._deduplicate_variants(variants, max_variants)
            analysis = self._analyze_variant_associations(
                variants=variants,
                phenotype_name=phenotype_name,
                method=method,
                covariate_mode=covariate_mode,
                categorical_covariates=categorical_covariates,
                numeric_covariates=numeric_covariates,
                stratify_by=stratify_by,
                min_breeds=min_breeds,
                min_stratum_breeds=min_stratum_breeds,
                permutations=permutations,
                top_n=top_n,
                random_seed=random_seed,
            )
            if not analysis['success']:
                return analysis

            return {
                'success': True,
                'analysis_type': analysis_type,
                'analysis_level': 'breed_aggregate',
                'query_context': query_context,
                'phenotype_name': analysis['phenotype_name'],
                'method': method,
                'tested_variant_count': analysis['tested_variants'],
                'returned_top_n': min(top_n, len(analysis['top_associations'])),
                'top_associations': analysis['top_associations'],
                'statistical_note': '这是基于品种层聚合频率与品种表型的相关分析，用于候选发现，不代表个体层因果关联。',
            }
        except Exception as exc:
            return {'success': False, 'error': str(exc)}


if __name__ == '__main__':
    print('=' * 60)
    print('鸡基因组 SV 数据库工具测试')
    print('=' * 60)

    tool = ChickenSVTool('../data', annotation_path='../annotation/Gallus_gallus.bGalGal1.mat.broiler.GRCg7b.115.gff3')

    print('\n[测试1] get_database_info(overview)')
    result = tool.get_database_info('overview')
    print(f"  数据库: {result.get('current_database')}, 记录: {result.get('current_stats', {}).get('total_records')}")

    print('\n[测试2] get_database_info(phenotypes)')
    result = tool.get_database_info('phenotypes')
    print(f"  表型已加载: {result.get('phenotype', {}).get('loaded')}, 数值型表型数: {len(result.get('numeric_traits', []))}")

    print('\n[测试3] query_sv - 品种别名频率查询')
    result = tool.query_sv(query_type='gene', genes=['IGF2BP1'], window=5000, max_results=3, breeds=['HGS', 'BJY'])
    print(f"  结果: {result.get('total_results')} 个SV")

    print('\n[测试4] analyze_breed_association - 协变量校正')
    result = tool.analyze_breed_association(
        analysis_type='gene_trait',
        genes=['IGF2BP1'],
        phenotype_name='平均体重g',
        window=5000,
        covariate_mode='adjust',
        categorical_covariates=['大分类'],
        numeric_covariates=['纬度', '经度'],
        top_n=3,
        permutations=20,
    )
    print(f"  测试位点数: {result.get('tested_variant_count')}, 返回结果数: {len(result.get('top_associations', []))}")

    print('\n[测试5] analyze_breed_association - 分层控制')
    result = tool.analyze_breed_association(
        analysis_type='gene_summary_trait',
        genes=['IGF2BP1', 'BMP2'],
        phenotype_name='平均体重g',
        window=5000,
        covariate_mode='stratify',
        stratify_by=['大分类'],
        top_n=3,
        permutations=20,
    )
    print(f"  测试基因数: {result.get('tested_gene_count')}, 返回结果数: {len(result.get('top_gene_associations', []))}")

    print('\n[测试6] run_analysis_task - DSL 执行器')
    result = tool.run_analysis_task(
        task_name='demo_dsl_task',
        steps=[
            {'id': 'step1', 'tool': 'get_database_info', 'arguments': {'info_type': 'phenotypes'}},
            {'id': 'step2', 'tool': 'query_sv', 'arguments': {'query_type': 'gene', 'genes': ['IGF2BP1'], 'window': 5000, 'max_results': 2}},
            {'id': 'step3', 'tool': 'analyze_breed_association', 'arguments': {'analysis_type': 'gene_trait', 'genes': ['IGF2BP1'], 'phenotype_name': '平均体重g', 'window': 5000, 'top_n': 1}},
        ],
    )
    print(f"  DSL 执行成功: {result.get('success')}, 步骤数: {result.get('step_count')}")

    print('\n[测试7] genome_wide_association_scan - topN')
    result = tool.genome_wide_association_scan(
        phenotype_name='平均体重g',
        top_n=3,
        rank_by='p_value',
    )
    print(f"  全基因组测试位点数: {result.get('tested_variant_count')}, 返回结果数: {len(result.get('top_hits', []))}")

    print('\n[测试8] run_analysis_task - 条件/排序/投影')
    result = tool.run_analysis_task(
        task_name='dsl_transform_demo',
        steps=[
            {
                'id': 'scan',
                'tool': 'genome_wide_association_scan',
                'arguments': {'phenotype_name': '平均体重g', 'top_n': 10, 'rank_by': 'p_value'},
                'transform': {
                    'path': 'top_hits',
                    'sort': {'path': 'p_value', 'order': 'asc'},
                    'limit': 3,
                    'project': ['sv_id', 'gene', 'chromosome', 'position', 'p_value', 'fdr'],
                },
            },
            {
                'id': 'followup',
                'tool': 'get_database_info',
                'when': {'left': {'$ref': 'scan.transformed_result'}, 'op': 'not_empty'},
                'arguments': {'info_type': 'overview'},
            },
        ],
    )
    print(f"  DSL 变换执行成功: {result.get('success')}, 最终步骤: {result.get('final_step_id')}")

    print('\n✓ 测试完成')
