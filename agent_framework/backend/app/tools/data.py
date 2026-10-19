"""
数据查询工具集
"""

import asyncio
import json
import logging
import os
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from app.tools.common import (
    _get_gff3_parser,
_build_chicken_sv_tool,
_csv_path,
_ensure_list,
_extract_sv_id,
_load_csv_data,
_load_phenotype_data,
_looks_like_sv_id,
_mcp_tool_available,
_normalize_chrom,
_normalize_text,
)
from app.tools.stats import _permutation_p_value, _weighted_pearson, _weighted_spearman
from app.paths import annotation_dir

logger = logging.getLogger(__name__)


_breed_category_cache_raw: Optional[Dict[str, str]] = None
_breed_category_cache_norm: Optional[Dict[str, str]] = None
_breed_category_metric_name: Optional[str] = None


def _get_breed_category_maps() -> tuple:
    global _breed_category_cache_raw, _breed_category_cache_norm, _breed_category_metric_name

    if _breed_category_cache_raw is not None and _breed_category_cache_norm is not None:
        return _breed_category_cache_raw, _breed_category_cache_norm, _breed_category_metric_name or "大分类"

    raw_map: Dict[str, str] = {}
    norm_map: Dict[str, str] = {}
    metric_name = "大分类"

    phenotype_df = _load_phenotype_data()
    if phenotype_df is None or phenotype_df.empty or len(phenotype_df.columns) < 2:
        _breed_category_cache_raw = raw_map
        _breed_category_cache_norm = norm_map
        _breed_category_metric_name = metric_name
        return raw_map, norm_map, metric_name

    metric_col = phenotype_df.columns[0]
    target_keys = {_normalize_text("大分类"), _normalize_text("驯化程度分类"), _normalize_text("category")}

    selected_row = None
    selected_metric = None
    for _, row in phenotype_df.iterrows():
        metric_value = str(row.get(metric_col, "")).strip()
        if not metric_value or metric_value.lower() == "nan":
            continue
        metric_key = _normalize_text(metric_value)
        if metric_key in target_keys:
            selected_row = row
            selected_metric = metric_value
            break

    if selected_row is None:
        for _, row in phenotype_df.iterrows():
            metric_value = str(row.get(metric_col, "")).strip()
            if not metric_value or metric_value.lower() == "nan":
                continue
            metric_key = _normalize_text(metric_value)
            if "驯化程度" in metric_value or "大分类" in metric_value or "category" in metric_key:
                selected_row = row
                selected_metric = metric_value
                break

    if selected_row is not None:
        metric_name = selected_metric or metric_name
        for breed_col in phenotype_df.columns[1:]:
            cat_value = selected_row.get(breed_col)
            if pd.isna(cat_value):
                continue

            category_text = str(cat_value).strip()
            if not category_text or category_text.lower() == "nan":
                continue

            breed_name = str(breed_col).strip()
            if not breed_name:
                continue

            raw_map[breed_name] = category_text

            normalized = _normalize_text(breed_name)
            if normalized:
                norm_map[normalized] = category_text
                if normalized.endswith("鸡"):
                    norm_map.setdefault(normalized[:-1], category_text)

    _breed_category_cache_raw = raw_map
    _breed_category_cache_norm = norm_map
    _breed_category_metric_name = metric_name
    return raw_map, norm_map, metric_name


def _resolve_breed_category(breed_name: str, raw_map: Dict[str, str], norm_map: Dict[str, str]) -> Optional[str]:
    if breed_name in raw_map:
        return raw_map[breed_name]

    key = _normalize_text(breed_name)
    if key in norm_map:
        return norm_map[key]
    if key.endswith("鸡") and key[:-1] in norm_map:
        return norm_map[key[:-1]]
    return None


def _build_domestication_summary(breed_frequencies: Dict[str, float]) -> Dict[str, Any]:
    raw_map, norm_map, metric_name = _get_breed_category_maps()
    if not breed_frequencies:
        return {"available": False, "metric": metric_name, "groups": []}

    category_bucket: Dict[str, Dict[str, Any]] = {}
    unmatched_count = 0

    for breed_name, freq in breed_frequencies.items():
        category = _resolve_breed_category(breed_name, raw_map, norm_map)
        if not category:
            unmatched_count += 1
            continue

        bucket = category_bucket.setdefault(category, {"values": [], "top_breeds": []})
        try:
            freq_value = float(freq)
        except (TypeError, ValueError):
            continue
        bucket["values"].append(freq_value)
        bucket["top_breeds"].append((breed_name, freq_value))

    if not category_bucket:
        return {
            "available": False,
            "metric": metric_name,
            "groups": [],
            "unmatched_breed_count": unmatched_count,
        }

    groups: List[Dict[str, Any]] = []
    for category, bucket in category_bucket.items():
        values = bucket["values"]
        top_breeds = sorted(bucket["top_breeds"], key=lambda x: x[1], reverse=True)[:3]
        groups.append(
            {
                "category": category,
                "breed_count": len(values),
                "mean_frequency": round(sum(values) / len(values), 4),
                "high_frequency_breed_count": sum(1 for v in values if v >= 0.8),
                "top_breeds": [
                    {"breed": breed, "frequency": round(value, 4)} for breed, value in top_breeds
                ],
            }
        )

    groups.sort(key=lambda g: (g["mean_frequency"], g["breed_count"]), reverse=True)

    highest = groups[0]
    lowest = groups[-1]
    if len(groups) >= 2:
        diff = round(highest["mean_frequency"] - lowest["mean_frequency"], 4)
        observation = (
            f"{highest['category']}组平均频率最高（{highest['mean_frequency']}），"
            f"与{lowest['category']}组差异约{diff}。"
        )
    else:
        observation = f"该SV在{highest['category']}组中平均频率为{highest['mean_frequency']}。"

    return {
        "available": True,
        "metric": metric_name,
        "group_count": len(groups),
        "groups": groups,
        "highest_group": highest["category"],
        "lowest_group": lowest["category"],
        "observation": observation,
        "unmatched_breed_count": unmatched_count,
    }


def _build_frequency_tier_summary(breed_frequencies: Dict[str, float]) -> Dict[str, Any]:
    """按固定/高/中/低/缺失分层汇总品种频率，供 Agent 与 LLM 上下文使用。"""
    if not breed_frequencies:
        return {"available": False, "tiers": []}

    tier_defs = [
        ("fixed", "固定 (freq=1.0)", lambda f: f >= 1.0),
        ("high", "高频 (0.8≤freq<1.0)", lambda f: 0.8 <= f < 1.0),
        ("mid", "中频 (0.5≤freq<0.8)", lambda f: 0.5 <= f < 0.8),
        ("low", "低频 (0<freq<0.5)", lambda f: 0.0 < f < 0.5),
        ("zero", "缺失 (freq=0)", lambda f: f <= 0.0),
    ]

    tiers: List[Dict[str, Any]] = []
    for tier_id, label, pred in tier_defs:
        pairs = sorted(
            [(breed, float(freq)) for breed, freq in breed_frequencies.items() if pred(float(freq))],
            key=lambda x: (-x[1], x[0]),
        )
        if not pairs:
            continue
        sample = [{"breed": b, "frequency": round(f, 4)} for b, f in pairs[:10]]
        tiers.append(
            {
                "tier": tier_id,
                "label": label,
                "breed_count": len(pairs),
                "sample_breeds": sample,
                "has_more": len(pairs) > len(sample),
                "omitted_count": max(0, len(pairs) - len(sample)),
            }
        )

    values = [float(v) for v in breed_frequencies.values()]
    return {
        "available": bool(tiers),
        "breed_total": len(breed_frequencies),
        "mean_frequency": round(sum(values) / len(values), 4) if values else None,
        "tiers": tiers,
    }

async def get_database_info(info_type: str = "overview") -> Dict[str, Any]:
    """获取数据库信息 - 使用真实MCP工具"""
    if not _mcp_tool_available:
        return {
            "status": "error",
            "error": "MCP工具未加载，无法获取数据库信息。请检查ChickenSVTool模块是否正确安装。",
            "data_source": "error"
        }

    try:
        tool = _build_chicken_sv_tool()
        if tool is None:
            return {
                "status": "error",
                "error": "MCP工具构建失败，无法获取数据库信息。",
                "data_source": "error"
            }

        result = await asyncio.to_thread(tool.get_database_info, info_type=info_type)

        if result.get('success'):
            return {
                "status": "success",
                "data_source": "真实MCP工具 + CSV数据",
                "info_type": info_type,
                "data": result,
                "note": "使用ChickenSVTool从真实数据中提取"
            }
        else:
            return {
                "status": "error",
                "error": result.get('error', '未知错误'),
                "data_source": "MCP工具返回错误"
            }
    except Exception as e:
        logger.error(f"MCP工具调用失败: {e}")
        return {
            "status": "error",
            "error": f"MCP工具调用失败: {e}",
            "data_source": "error"
        }

async def genome_wide_association_scan(
    phenotype_name: str,
    method: str = "auto",
    covariate_mode: str = "none",
    categorical_covariates: Optional[List[str]] = None,
    numeric_covariates: Optional[List[str]] = None,
    stratify_by: Optional[List[str]] = None,
    min_breeds: int = 8,
    min_stratum_breeds: int = 4,
    database_name: Optional[str] = None,
    search_all_databases: bool = False,
    sv_type: Optional[str] = None,
    chromosomes: Optional[List[str]] = None,
    include_annotation: bool = False,
    top_n: int = 20,
    rank_by: str = "p_value",
    sort_order: str = "asc",
    min_abs_correlation: Optional[float] = None,
) -> Dict[str, Any]:
    """全基因组SV-表型关联扫描 - 复用MCP实现"""
    if not _mcp_tool_available:
        return {"status": "error", "error": "MCP工具不可用"}

    try:
        tool = _build_chicken_sv_tool(load_annotation=bool(include_annotation))
        if tool is None:
            return {"status": "error", "error": "MCP工具不可用"}

        normalized_sv_type = sv_type.upper().strip() if isinstance(sv_type, str) and sv_type.strip().upper() in {'DEL', 'INS'} else None

        result = await asyncio.to_thread(
            tool.genome_wide_association_scan,
            phenotype_name=phenotype_name,
            method=method,
            covariate_mode=covariate_mode,
            categorical_covariates=_ensure_list(categorical_covariates),
            numeric_covariates=_ensure_list(numeric_covariates),
            stratify_by=_ensure_list(stratify_by),
            min_breeds=min_breeds,
            min_stratum_breeds=min_stratum_breeds,
            database_name=database_name,
            search_all_databases=search_all_databases,
            sv_type=normalized_sv_type,
            chromosomes=_ensure_list(chromosomes),
            include_annotation=include_annotation,
            top_n=top_n,
            rank_by=rank_by,
            sort_order=sort_order,
            min_abs_correlation=min_abs_correlation,
        )
        logger.info("genome_wide_association_scan wrapper result: tested=%s, returned=%s, sv_type=%s", result.get('tested_variant_count'), result.get('returned_top_n'), normalized_sv_type)
        return {"status": "success", "data_source": "真实MCP工具 + CSV数据", "data": result}
    except Exception as e:
        logger.error(f"全基因组扫描调用失败: {e}")
        return {"status": "error", "error": str(e)}

async def query_breed_profile(
    breed_name: str = "",
    trait: str = "",
) -> Dict[str, Any]:
    if not _mcp_tool_available:
        return {
            "status": "error",
            "error": "MCP工具未加载，无法获取品种信息。请检查ChickenSVTool模块是否正确安装。",
            "data_source": "error",
        }

    try:
        tool = _build_chicken_sv_tool()
        if tool is None:
            return {
                "status": "error",
                "error": "MCP工具构建失败，无法获取品种信息。",
                "data_source": "error",
            }

        breed_names = [breed_name] if breed_name else None
        result = await asyncio.to_thread(
            tool.query_breed_profile,
            breed_names=breed_names,
            include_trait_values=True,
        )

        if result.get('success'):
            return {
                "status": "success",
                "data_source": "真实MCP工具 + 表型数据",
                "data": result,
            }
        else:
            return {
                "status": "error",
                "error": result.get('error', '品种查询失败'),
                "data_source": "MCP工具返回错误",
            }
    except Exception as e:
        logger.error(f"品种查询失败: {e}")
        return {
            "status": "error",
            "error": f"品种查询失败: {e}",
            "data_source": "error",
        }

async def query_sv(
    query_type: str = "gene",
    query_value: str = "",
    sample_filter: str = "",
    sv_type: str = "",
    limit: int = 20,
) -> Dict[str, Any]:
    """查询SV数据 - 使用真实CSV数据源"""
    df = _load_csv_data()
    if df is None:
        return {
            "status": "error",
            "error": "CSV数据未加载",
            "results": [],
            "total": 0,
        }

    # 获取列名映射
    col_map = {c.lower(): c for c in df.columns}
    logger.info(f"CSV列: {list(df.columns)[:10]}...")
    logger.info(f"查询: type={query_type}, value={query_value}, filter={sample_filter}")

    query_type = str(query_type).strip().lower()
    query_value = str(query_value).strip()
    should_add_domestication_summary = query_type in ("sv_id", "id")

    # 过滤数据
    filtered = df.copy()

    if query_type == "gene" and query_value:
        gene_col = col_map.get("gene")
        if gene_col:
            mask = filtered[gene_col].astype(str).str.contains(query_value, case=False, na=False)
            filtered = filtered[mask]
            logger.info(f"基因过滤后: {len(filtered)} 条")

    elif query_type == "region" and query_value:
        # 解析区域格式 chr1:1000000-2000000
        try:
            chrom, pos_range = query_value.split(":")
            start, end = map(int, pos_range.split("-"))
            chr_col = col_map.get("chr") or col_map.get("chromosome")
            pos_col = col_map.get("pos") or col_map.get("start")
            end_col = col_map.get("end")
            if chr_col and pos_col and end_col:
                query_chrom = _normalize_chrom(chrom)
                chrom_series = filtered[chr_col].astype(str).map(_normalize_chrom)
                filtered = filtered[chrom_series == query_chrom]
                filtered = filtered[filtered[end_col].astype(int) >= start]
                filtered = filtered[filtered[pos_col].astype(int) <= end]
        except Exception as e:
            logger.warning(f"区域解析失败: {e}")
            return {
                "status": "error",
                "error": f"区域格式错误: {query_value}",
                "results": [],
                "total": 0,
            }

    elif query_type in ("sv_id", "id") and query_value:
        id_col = col_map.get("id") or col_map.get("sv_id")
        if id_col:
            filtered = filtered[filtered[id_col].astype(str).str.lower() == query_value.lower()]
        else:
            return {
                "status": "error",
                "error": "未找到SV ID列",
                "results": [],
                "total": 0,
            }
    elif query_type not in ("gene", "region", "sv_id", "id"):
        return {
            "status": "error",
            "error": f"不支持的查询类型: {query_type}",
            "results": [],
            "total": 0,
        }

    # 应用sv_type过滤
    if sv_type:
        type_col = col_map.get("sv_type") or col_map.get("type")
        if type_col:
            filtered = filtered[filtered[type_col].astype(str).str.upper() == sv_type.upper()]

    total = len(filtered)
    limit = min(limit, 50)  # 最大50条
    filtered = filtered.head(limit)

    # 构建结果
    results = []
    id_col = col_map.get("id") or "ID"
    chr_col = col_map.get("chr") or col_map.get("chromosome") or "Chr"
    pos_col = col_map.get("pos") or col_map.get("start") or "POS"
    end_col = col_map.get("end") or "End"
    type_col = col_map.get("sv_type") or col_map.get("type") or "SV_Type"
    gene_col = col_map.get("gene") or "Gene"
    mean_freq_col = col_map.get("mean_fre") or col_map.get("mean_frequency") or "Mean_fre"

    # 品种频率列：除去元信息列之外的所有剩余列
    meta_cols = {
        id_col, chr_col, pos_col, end_col, type_col, gene_col, mean_freq_col,
        "REF", "ALT", "Region", "Length", "SV_Length", "Gene_ID"
    }
    breed_cols = [col for col in df.columns if col not in meta_cols]

    for _, row in filtered.iterrows():
        breed_frequencies: Dict[str, float] = {}
        for col in breed_cols:
            if pd.notna(row.get(col)):
                try:
                    breed_frequencies[str(col)] = float(row.get(col))
                except (TypeError, ValueError):
                    continue

        top_breeds = sorted(
            breed_frequencies.items(),
            key=lambda item: item[1],
            reverse=True,
        )[:10]

        result = {
            "id": str(row.get(id_col, "")),
            "chr": str(row.get(chr_col, "")),
            "start": int(row.get(pos_col, 0)) if pd.notna(row.get(pos_col)) else 0,
            "end": int(row.get(end_col, 0)) if pd.notna(row.get(end_col)) else 0,
            "type": str(row.get(type_col, "")),
            "gene": str(row.get(gene_col, "")) if pd.notna(row.get(gene_col)) else None,
            "mean_frequency": float(row.get(mean_freq_col, 0)) if pd.notna(row.get(mean_freq_col)) else 0,
            "breed_frequencies": breed_frequencies,
            "top_breed_frequencies": top_breeds,
        }

        if should_add_domestication_summary:
            domestication_summary = _build_domestication_summary(breed_frequencies)
            if domestication_summary.get("available"):
                result["domestication_summary"] = domestication_summary
            tier_summary = _build_frequency_tier_summary(breed_frequencies)
            if tier_summary.get("available"):
                result["frequency_tier_summary"] = tier_summary

        # 仅在用户显式按品种筛选时返回单品种频率
        if sample_filter:
            sample_name = str(sample_filter).strip()
            for col in breed_cols:
                if sample_name and sample_name in str(col):
                    try:
                        result["selected_breed_frequency"] = float(row.get(col, 0)) if pd.notna(row.get(col)) else 0
                    except (TypeError, ValueError):
                        pass
                    break

        results.append(result)

    logger.info(f"返回 {len(results)} 条结果")

    response_payload = {
        "status": "success",
        "query": {"type": query_type, "value": query_value, "filter": sample_filter},
        "results": results,
        "total": total,
        "has_more": total > limit,
        "data_source": "真实CSV数据",
        "csv_records": len(df),
    }

    if should_add_domestication_summary and results:
        first_row = results[0] if isinstance(results[0], dict) else {}
        first_summary = first_row.get("domestication_summary")
        if isinstance(first_summary, dict) and first_summary.get("available"):
            response_payload["default_summary"] = {
                "type": "domestication_category",
                "content": first_summary,
            }
        tier_summary = first_row.get("frequency_tier_summary")
        if isinstance(tier_summary, dict) and tier_summary.get("available"):
            response_payload["frequency_tier_summary"] = tier_summary

    return response_payload

async def query_annotation(
    gene_name: str = "",
    sv_id: str = "",
    annotation_type: str = "all",
) -> Dict[str, Any]:
    """查询基因注释 - 使用真实GFF3数据"""
    gff3_path = str(annotation_dir() / "Gallus_gallus.bGalGal1.mat.broiler.GRCg7b.115.gff3")

    # 如果没有指定基因名，返回数据库信息
    if not gene_name:
        return {
            "status": "info",
            "message": "请提供基因名进行查询",
            "supported_formats": ["基因符号 (如 BMP2, MSTN)", "Ensembl ID (如 ENSGALG00000012345)"],
            "data_source": "GFF3注释文件",
            "gff3_file": "Gallus_gallus.bGalGal1.mat.broiler.GRCg7b.115.gff3",
        }

    # 从CSV数据中获取基因相关的SV信息
    df = _load_csv_data()
    gene_sv_count = 0
    gene_sv_list = []

    if df is not None:
        col_map = {c.lower(): c for c in df.columns}
        gene_col = col_map.get("gene")
        if gene_col:
            # 查找包含该基因的所有SV
            matching_svs = df[df[gene_col].astype(str).str.contains(gene_name, case=False, na=False)]
            gene_sv_count = len(matching_svs)

            # 获取前5个SV的详细信息
            for _, row in matching_svs.head(5).iterrows():
                sv_info = {
                    "sv_id": str(row.get("ID", "")),
                    "chromosome": str(row.get("Chr", "")),
                    "position": f"{row.get('POS', 0)}-{row.get('End', 0)}",
                    "type": str(row.get("SV_Type", "")),
                    "region": str(row.get("Region", "")),
                    "mean_frequency": float(row.get("Mean_fre", 0)) if pd.notna(row.get("Mean_fre")) else 0,
                }
                gene_sv_list.append(sv_info)

    # 构建真实的注释结果
    result = {
        "status": "success",
        "query": {
            "gene_name": gene_name,
            "annotation_type": annotation_type,
        },
        "data_source": "真实GFF3注释 + CSV变异数据",
        "gene_info": {
            "name": gene_name,
            "species": "Gallus gallus (鸡)",
            "reference_genome": "GRCg7b (bGalGal1.mat.broiler.GRCg7b.115)",
        },
        "structural_variants": {
            "total_count": gene_sv_count,
            "sv_list": gene_sv_list,
        },
        "annotations": [],
        "gff3_file": "Gallus_gallus.bGalGal1.mat.broiler.GRCg7b.115.gff3 (228MB)",
    }

    # 尝试从真实 GFF3 注释获取基因信息
    gff3 = _get_gff3_parser()
    matched_gene = None
    if gff3:
        gene_model = gff3.find_gene_by_name(gene_name) or gff3.get_gene(gene_name)
        if gene_model:
            result["gene_info"]["gene_id"] = gene_model.gene_id
            result["gene_info"]["chromosome"] = gene_model.chromosome
            result["gene_info"]["start"] = gene_model.start
            result["gene_info"]["end"] = gene_model.end
            result["gene_info"]["strand"] = gene_model.strand
            result["gene_info"]["length"] = gene_model.end - gene_model.start + 1
            result["gene_info"]["transcript_count"] = len(gene_model.transcripts)
            structure = gff3.get_gene_structure(gene_model.gene_id)
            if structure:
                result["gene_structure"] = structure
            result["annotations"] = [
                {"type": "info", "description": f"基因 {gene_model.gene_name or gene_model.gene_id} 位于 {gene_model.chromosome}:{gene_model.start}-{gene_model.end}，链 {gene_model.strand}，包含 {len(gene_model.transcripts)} 个转录本", "source": "GFF3"}
            ]
            matched_gene = True

    if not matched_gene:
        result["status"] = "partial"
        result["annotations"] = [
            {"type": "info", "description": f"基因 {gene_name} 未在GFF3注释中找到匹配记录，无法提供详细功能注释。请检查基因名拼写或使用Ensembl ID查询。", "source": "GFF3"},
        ]

    return result

async def analyze_breed_association(
    analysis_type: str = "",
    breed: str = "",
    trait: str = "",
    phenotype_name: str = "",
    sv_id: str = "",
    sv_ids: Any = None,
    genes: Any = None,
    chromosome: str = "",
    start_pos: int = 0,
    end_pos: int = 0,
    window: int = 0,
    method: str = "auto",
    aggregate_method: str = "mean",
    covariate_mode: str = "none",
    categorical_covariates: Any = None,
    numeric_covariates: Any = None,
    sv_type: str = "",
    p_threshold: float = 0.05,
    permutations: int = 200,
    random_seed: int = 42,
    **kwargs,
) -> Dict[str, Any]:
    analysis_type = (analysis_type or "").strip().lower()
    target_trait = phenotype_name or trait or kwargs.get("trait_name", "")
    target_sv_id = _extract_sv_id(sv_id) or _extract_sv_id(sv_ids)

    if not analysis_type:
        if target_sv_id or _looks_like_sv_id(breed):
            analysis_type = "sv_trait"
        else:
            analysis_type = "breed_trait"

    if analysis_type == "phenotype_overview":
        phenotype_df = _load_phenotype_data()
        if phenotype_df is None or phenotype_df.empty:
            return {"analysis_type": "phenotype_overview", "error": "表型数据未加载"}

        first_col = phenotype_df.columns[0]
        traits = [str(v).strip() for v in phenotype_df[first_col].dropna().tolist() if str(v).strip()]
        numeric_traits = []
        categorical_traits = []
        for trait_name in traits:
            row = phenotype_df[phenotype_df[first_col].astype(str).str.strip() == trait_name]
            if row.empty:
                continue
            values = row.iloc[0, 1:]
            numeric_count = pd.to_numeric(values, errors="coerce").notna().sum()
            if numeric_count >= max(1, len(values) // 2):
                numeric_traits.append(trait_name)
            else:
                categorical_traits.append(trait_name)

        return {
            "analysis_type": "phenotype_overview",
            "trait_count": len(traits),
            "numeric_traits_count": len(numeric_traits),
            "categorical_traits_count": len(categorical_traits),
            "trait_examples": traits[:10],
            "numeric_trait_examples": numeric_traits[:10],
            "categorical_trait_examples": categorical_traits[:10],
            "covariates_available": ["大分类", "细分", "纬度", "经度"],
        }

    if analysis_type == "sv_trait" or (not kwargs.get("analysis_type") and target_sv_id):
        if not target_sv_id and _looks_like_sv_id(breed):
            target_sv_id = breed.strip()

        if not target_sv_id:
            return {
                "analysis_type": "sv_trait",
                "error": "sv_trait 需要 sv_id 参数",
            }

        sv_result = await query_sv(query_type="id", query_value=target_sv_id, sv_type=sv_type, limit=1)
        if sv_result.get("status") != "success" or not sv_result.get("results"):
            return {
                "analysis_type": "sv_trait",
                "sv_id": target_sv_id,
                "error": "未找到该SV记录",
            }

        sv_record = sv_result["results"][0]
        breed_frequencies = sv_record.get("breed_frequencies", {}) or {}
        phenotype_df = _load_phenotype_data()

        correlation = None
        p_value = None
        matched_breeds: List[str] = []
        matched_frequencies: List[float] = []
        trait_values: List[float] = []
        matched_weights: List[float] = []
        used_method = method if method and method != "auto" else "weighted_spearman"

        if phenotype_df is not None and target_trait:
            first_col = phenotype_df.columns[0]
            trait_row = phenotype_df[phenotype_df[first_col].astype(str).str.strip() == target_trait]
            if trait_row.empty:
                trait_row = phenotype_df[phenotype_df[first_col].astype(str).str.contains(target_trait, case=False, na=False)]

            if not trait_row.empty:
                trait_row = trait_row.iloc[0]
                sample_row = phenotype_df[phenotype_df[first_col].astype(str).str.strip() == "数量"]
                sample_row = sample_row.iloc[0] if not sample_row.empty else None
                breed_columns = [str(c).strip() for c in phenotype_df.columns[1:]]
                breed_lookup = {_normalize_text(col): col for col in breed_columns}

                if not sample_row is None:
                    sample_lookup = {str(c).strip(): sample_row[c] for c in phenotype_df.columns[1:]}
                else:
                    sample_lookup = {}

                for breed_name, freq in breed_frequencies.items():
                    breed_key = _normalize_text(breed_name)
                    phenotype_col = breed_lookup.get(breed_key)
                    if not phenotype_col:
                        continue
                    try:
                        trait_value = float(trait_row[phenotype_col])
                    except Exception:
                        continue
                    if pd.isna(trait_value):
                        continue
                    matched_breeds.append(phenotype_col)
                    matched_frequencies.append(float(freq))
                    trait_values.append(trait_value)
                    weight = sample_lookup.get(phenotype_col, 1.0)
                    try:
                        weight = float(weight)
                    except Exception:
                        weight = 1.0
                    matched_weights.append(weight if weight > 0 else 1.0)

                if len(matched_frequencies) >= 3:
                    x = np.asarray(matched_frequencies, dtype=float)
                    y = np.asarray(trait_values, dtype=float)
                    w = np.asarray(matched_weights, dtype=float)
                    corr_func = _weighted_pearson if used_method in {"pearson", "weighted_pearson"} else _weighted_spearman
                    correlation = corr_func(x, y, w)
                    p_value = _permutation_p_value(x, y, w, corr_func, permutations=permutations, random_seed=random_seed)
                else:
                    used_method = "descriptive_only"

        result = {
            "analysis_type": "sv_trait",
            "sv_id": target_sv_id,
            "phenotype_name": target_trait,
            "method": used_method,
            "covariate_mode": covariate_mode,
            "matched_breeds": len(matched_breeds),
            "correlation": correlation,
            "p_value": p_value,
            "effect_direction": "positive" if correlation is not None and correlation > 0 else ("negative" if correlation is not None and correlation < 0 else "unknown"),
            "significant_associations": [
                {
                    "sv_id": target_sv_id,
                    "chr": sv_record.get("chr"),
                    "pos": f"{sv_record.get('start', 0)}-{sv_record.get('end', 0)}",
                    "type": sv_record.get("type"),
                    "p_value": p_value if p_value is not None else 1.0,
                    "effect_size": correlation if correlation is not None else 0.0,
                    "gene": sv_record.get("gene"),
                    "mean_frequency": sv_record.get("mean_frequency", 0),
                }
            ],
            "total_tested": len(matched_breeds),
            "significant_count": 1 if p_value is not None and p_value < p_threshold else 0,
            "manhattan_plot_available": False,
            "breed_frequencies": breed_frequencies,
            "matched_breed_values": [
                {"breed": breed, "frequency": freq, "trait_value": trait_value}
                for breed, freq, trait_value in zip(matched_breeds[:20], matched_frequencies[:20], trait_values[:20])
            ],
            "summary": {
                "sv_type": sv_record.get("type"),
                "gene": sv_record.get("gene"),
                "mean_frequency": sv_record.get("mean_frequency"),
                "top_breed_frequencies": sv_record.get("top_breed_frequencies", [])[:10],
            },
        }
        if sv_record.get("selected_breed_frequency") is not None:
            result["selected_breed_frequency"] = sv_record.get("selected_breed_frequency")
        return result

    return {
        "analysis_type": analysis_type or "breed_trait",
        "status": "error",
        "error": "breed_trait 分析类型需要提供 sv_id 参数以执行位点级关联分析。请使用 analysis_type='sv_trait' 并提供 sv_id 参数。",
        "suggestion": "示例: analyze_breed_association(analysis_type='sv_trait', sv_id='27_3284400_INS', phenotype_name='平均体重(Body_size_g)')",
    }

