"""
Dify 知识库检索 REST API
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.config import settings
from app.tools.knowledge import query_literature_kb

router = APIRouter()


class RetrieveRequest(BaseModel):
    query: str = Field(..., min_length=1, description="检索问题")
    dataset: str = Field(default="auto", description="auto | parent_qa | pure_qa | english_qa | UUID")
    top_k: int = Field(default=5, ge=1, le=20)
    search_method: Optional[str] = Field(
        default=None,
        description="hybrid_search | full_text_search | semantic_search | keyword_search",
    )


class RetrieveResponse(BaseModel):
    configured: bool
    query: str
    search_method: str
    dataset_ids: List[str]
    hit_count: int
    hits: List[Dict[str, Any]]
    errors: Optional[List[Dict[str, Any]]] = None


@router.get("/rag/status", summary="Dify 知识库连接状态")
async def rag_status() -> Dict[str, Any]:
    return {
        "configured": bool(settings.dify_api_base and settings.dify_api_key),
        "api_base": settings.dify_api_base,
        "datasets": {
            "parent_qa": settings.dify_dataset_parent_qa,
            "pure_qa": settings.dify_dataset_pure_qa,
            "english_qa": settings.dify_dataset_english_qa,
        },
        "default_search_method": settings.dify_default_search_method,
    }


@router.post(
    "/rag/retrieve",
    response_model=RetrieveResponse,
    status_code=status.HTTP_200_OK,
    summary="检索 Dify 文献知识库",
)
async def rag_retrieve(body: RetrieveRequest) -> RetrieveResponse:
    if not settings.dify_api_base or not settings.dify_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Dify 未配置：请设置 DIFY_API_BASE 与 DIFY_API_KEY",
        )

    result = await query_literature_kb(
        query=body.query,
        dataset=body.dataset,
        top_k=body.top_k,
        search_method=body.search_method,
    )
    if result.get("error") and not result.get("hits"):
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=result["error"])

    return RetrieveResponse(
        configured=bool(result.get("configured")),
        query=result.get("query", body.query),
        search_method=result.get("search_method", settings.dify_default_search_method),
        dataset_ids=result.get("dataset_ids", []),
        hit_count=int(result.get("hit_count") or 0),
        hits=result.get("hits") or [],
        errors=result.get("errors"),
    )
