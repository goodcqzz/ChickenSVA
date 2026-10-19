"""
Dify 文献知识库检索工具
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.config import settings
from app.dify.client import get_dify_client

logger = logging.getLogger(__name__)

_DATASET_ALIASES = {
    "parent_qa": "dify_dataset_parent_qa",
    "pure_qa": "dify_dataset_pure_qa",
    "english": "dify_dataset_english_qa",
    "父子qa": "dify_dataset_parent_qa",
    "纯qa": "dify_dataset_pure_qa",
    "英文": "dify_dataset_english_qa",
}


def _dataset_catalog() -> Dict[str, str]:
    return {
        "parent_qa": settings.dify_dataset_parent_qa,
        "pure_qa": settings.dify_dataset_pure_qa,
        "english_qa": settings.dify_dataset_english_qa,
    }


def _resolve_dataset_ids(dataset: str) -> List[str]:
    catalog = _dataset_catalog()
    key = (dataset or "auto").strip().lower()
    if key in ("auto", "all", "default"):
        return [v for v in catalog.values() if v]
    if key in catalog:
        return [catalog[key]]
    attr = _DATASET_ALIASES.get(key)
    if attr:
        return [getattr(settings, attr)]
    # 允许直接传 UUID
    if len(key) >= 32 and "-" in key:
        return [dataset.strip()]
    raise ValueError(
        f"未知 dataset: {dataset}，可选 auto/all、parent_qa、pure_qa、english_qa 或 dataset UUID"
    )


def _format_record(record: Dict[str, Any]) -> Dict[str, Any]:
    if record.get("_error"):
        return {
            "dataset_id": record.get("_dataset_id"),
            "error": record.get("_error"),
        }
    segment = record.get("segment") or {}
    child_chunks = record.get("child_chunks") or []
    content = (segment.get("content") or "").strip()
    if not content and child_chunks:
        content = (child_chunks[0].get("content") or "").strip()
    doc = segment.get("document") or {}
    return {
        "dataset_id": record.get("_dataset_id"),
        "score": record.get("score"),
        "segment_id": segment.get("id"),
        "document_name": doc.get("name"),
        "content": content[:4000] if content else "",
        "child_chunk_count": len(child_chunks),
    }


async def query_literature_kb(
    query: str,
    dataset: str = "auto",
    top_k: int = 5,
    search_method: Optional[str] = None,
) -> Dict[str, Any]:
    """
    检索 Dify 期刊文献知识库，供 Agent 补充文献/方法学证据。
    """
    if not settings.dify_api_base or not settings.dify_api_key:
        return {
            "error": "Dify 未配置：请在 config/chickensv.env 设置 DIFY_API_BASE 与 DIFY_API_KEY",
            "configured": False,
        }

    try:
        dataset_ids = _resolve_dataset_ids(dataset)
    except ValueError as exc:
        return {"error": str(exc), "configured": True}

    client = get_dify_client()
    method = search_method or settings.dify_default_search_method
    try:
        if len(dataset_ids) == 1:
            raw = await client.retrieve(
                dataset_ids[0],
                query,
                search_method=method,
                top_k=top_k,
            )
            records = raw.get("records") or []
            for rec in records:
                rec["_dataset_id"] = dataset_ids[0]
        else:
            records = await client.retrieve_many(
                dataset_ids,
                query,
                search_method=method,
                top_k=top_k,
            )
    except Exception as exc:
        logger.exception("Dify 检索失败")
        return {"error": f"Dify 检索失败: {exc}", "configured": True}

    hits = [_format_record(r) for r in records if not r.get("_error")]
    errors = [_format_record(r) for r in records if r.get("_error")]
    return {
        "query": query,
        "search_method": method,
        "dataset_ids": dataset_ids,
        "hit_count": len(hits),
        "hits": hits,
        "errors": errors or None,
        "configured": True,
    }
