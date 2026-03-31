"""
Retrieval route — the main RAG endpoint.

Agentic Pattern: TOOL USE
    - This endpoint IS the "tool" that AI agents call
    - Via MCP or direct API, agents send queries here and get grounded answers
    - The response includes sources for citation (NotebookLM-style)
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from centrag.middleware import RequestContext
from centrag.middleware.auth import resolve_api_key

router = APIRouter(tags=["retrieval"])


class RetrieveRequest(BaseModel):
    """Request body for the retrieval endpoint."""

    query: str = Field(..., min_length=1, max_length=5000)
    namespace: str = "default"
    max_results: int = Field(5, ge=1, le=20)
    include_memory: bool = True
    include_sources: bool = True
    mode: str = Field("rag", pattern="^(rag|full_context)$")
    temperature: float = Field(0.1, ge=0.0, le=1.0)


class SourceResponse(BaseModel):
    content: str
    document_id: str
    chunk_index: int
    relevance_score: float


class RetrieveResponse(BaseModel):
    answer: str
    sources: list[SourceResponse]
    query_complexity: str
    cache_tier: str
    memory_used: bool


@router.post("/retrieve", operation_id="retrieve", response_model=RetrieveResponse)
async def retrieve(
    body: RetrieveRequest,
    ctx: RequestContext = Depends(resolve_api_key),
) -> RetrieveResponse:
    """
    Main RAG retrieval endpoint.

    Pipeline: Auth → Cache → Embed → Search → Rerank → Validate → Memory → Generate

    The RequestContext (ctx) ensures ALL operations are scoped to ctx.team_id.
    """
    # TODO: Wire to RetrievalEngine once implementations exist
    return RetrieveResponse(
        answer="Retrieval engine not yet implemented. This is the scaffold.",
        sources=[],
        query_complexity="moderate",
        cache_tier="MISS",
        memory_used=False,
    )
