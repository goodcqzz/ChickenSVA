"""
Dify 知识库 Dataset API 客户端（retrieve / list datasets）
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_client: Optional["DifyKnowledgeClient"] = None


class DifyKnowledgeClient:
    def __init__(
        self,
        api_base: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
    ):
        base = (api_base or settings.dify_api_base or "").rstrip("/")
        if not base:
            raise ValueError("DIFY_API_BASE 未配置")
        key = api_key or settings.dify_api_key
        if not key:
            raise ValueError("DIFY_API_KEY 未配置")

        self._api_base = base
        read_timeout = float(timeout_seconds or settings.dify_http_timeout_seconds or 60.0)
        self._client = httpx.AsyncClient(
            base_url=self._api_base,
            timeout=httpx.Timeout(read_timeout, connect=10.0),
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
        )

    @property
    def api_base(self) -> str:
        return self._api_base

    @property
    def is_configured(self) -> bool:
        return bool(self._api_base and settings.dify_api_key)

    async def close(self) -> None:
        await self._client.aclose()

    async def list_datasets(self, page: int = 1, limit: int = 20) -> Dict[str, Any]:
        resp = await self._client.get("/datasets", params={"page": page, "limit": limit})
        resp.raise_for_status()
        return resp.json()

    async def retrieve(
        self,
        dataset_id: str,
        query: str,
        *,
        search_method: Optional[str] = None,
        top_k: Optional[int] = None,
        reranking_enable: Optional[bool] = None,
        score_threshold_enabled: Optional[bool] = None,
        score_threshold: Optional[float] = None,
    ) -> Dict[str, Any]:
        if not query.strip():
            raise ValueError("query 不能为空")

        method = search_method or settings.dify_default_search_method
        k = top_k if top_k is not None else settings.dify_default_top_k
        rerank = (
            reranking_enable
            if reranking_enable is not None
            else settings.dify_reranking_enable
        )
        threshold_enabled = (
            score_threshold_enabled
            if score_threshold_enabled is not None
            else settings.dify_score_threshold_enabled
        )
        threshold = (
            score_threshold
            if score_threshold is not None
            else settings.dify_score_threshold
        )

        payload: Dict[str, Any] = {
            "query": query,
            "retrieval_model": {
                "search_method": method,
                "reranking_enable": rerank,
                "top_k": k,
                "score_threshold_enabled": threshold_enabled,
            },
        }
        if threshold_enabled and threshold is not None:
            payload["retrieval_model"]["score_threshold"] = threshold

        resp = await self._client.post(f"/datasets/{dataset_id}/retrieve", json=payload)
        if resp.status_code >= 400:
            try:
                detail = resp.json()
            except Exception:
                detail = resp.text
            raise httpx.HTTPStatusError(
                f"Dify retrieve 失败: {detail}",
                request=resp.request,
                response=resp,
            )
        return resp.json()

    async def retrieve_many(
        self,
        dataset_ids: List[str],
        query: str,
        **kwargs: Any,
    ) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        for dataset_id in dataset_ids:
            try:
                data = await self.retrieve(dataset_id, query, **kwargs)
                for record in data.get("records") or []:
                    record["_dataset_id"] = dataset_id
                    results.append(record)
            except Exception as exc:
                logger.warning("Dify retrieve 失败 dataset=%s: %s", dataset_id, exc)
                results.append(
                    {
                        "_dataset_id": dataset_id,
                        "_error": str(exc),
                    }
                )
        results.sort(key=lambda r: float(r.get("score") or 0), reverse=True)
        top_k = kwargs.get("top_k") or settings.dify_default_top_k
        return results[:top_k]


def get_dify_client() -> DifyKnowledgeClient:
    global _client
    if _client is None:
        _client = DifyKnowledgeClient()
    return _client


async def close_dify_client() -> None:
    global _client
    if _client is not None:
        await _client.close()
        _client = None
