"""
Retrieval route — the main RAG endpoint.

Agentic Pattern: TOOL USE
    - This endpoint IS the "tool" that AI agents call
    - Via MCP or direct API, agents send queries here and get grounded answers
    - The response includes sources for citation (NotebookLM-style)

Now WIRED to the real RetrievalEngine built in app.py lifespan.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from centrag.middleware import RequestContext
from centrag.middleware.auth import resolve_api_key
from centrag.retrieval.engine import RetrievalEngine, RetrievalRequest

router = APIRouter(tags=["retrieval"])


class RetrieveRequestBody(BaseModel):
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


def _get_engine(request: Request) -> RetrievalEngine:
    """FastAPI dependency: retrieve the engine from app.state."""
    return request.app.state.retrieval_engine


@router.post("/retrieve", operation_id="retrieve", response_model=RetrieveResponse)
async def retrieve(
    body: RetrieveRequestBody,
    ctx: RequestContext = Depends(resolve_api_key),
    engine: RetrievalEngine = Depends(_get_engine),
) -> RetrieveResponse:
    """
    Main RAG retrieval endpoint.

    Pipeline: Auth → Cache → Embed → Search → Rerank → Validate → Memory → Generate

    The RequestContext (ctx) ensures ALL operations are scoped to ctx.team_id.
    """
    request = RetrievalRequest(
        query=body.query,
        namespace=body.namespace,
        max_results=body.max_results,
        include_memory=body.include_memory,
        include_sources=body.include_sources,
        mode=body.mode,
    )

    response = await engine.retrieve(request, ctx)

    return RetrieveResponse(
        answer=response.answer,
        sources=[
            SourceResponse(
                content=s.content[:1000],  # Cap content in API response
                document_id=s.document_id,
                chunk_index=s.chunk_index,
                relevance_score=round(s.relevance_score, 4),
            )
            for s in response.sources
        ],
        query_complexity=response.query_complexity.value,
        cache_tier=response.cache_tier.value,
        memory_used=len(response.memory_context) > 0,
    )
