from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from centrag.abstractions.cache import CacheTier
from centrag.abstractions.llm import LLMResponse, QueryComplexity


@dataclass(frozen=True)
class RetrievalRequest:
    """
    Immutable retrieval request.

    Supports dual-path retrieval:
        mode="auto"      → QueryRouter decides (Day 3)
        mode="pageindex"  → VECTORLESS path only
        mode="vector"     → VECTOR path only
        mode="hybrid"     → Both paths + RRF fusion (Day 3)
        mode="rag"        → Legacy: vector search (backward compat)
    """

    query: str
    namespace: str = "default"
    max_results: int = 5
    include_memory: bool = True
    include_sources: bool = True
    mode: str = "rag"  # "auto" | "pageindex" | "vector" | "hybrid" | "rag"
    target_doc_id: str = ""  # Scope to a specific document (enables PageIndex)
    metadata_filter: dict[str, Any] | None = None  # Explicit filters (e.g., {"post_year": "2024"})

    # Internal: Populated by RetrievalEngine after intent transformation
    query_intent: Any | None = None  # Use Any to avoid circular import if needed


@dataclass(frozen=True)
class SourceChunk:
    """A retrieved source chunk with citation metadata."""

    content: str
    document_id: str
    chunk_index: int
    relevance_score: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RetrievalResult:
    """An intermediate result from a specific retrieval path (Graph, Multivector)."""

    content: str
    score: float
    doc_id: str
    filename: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RetrievalResponse:
    """Immutable retrieval response."""

    answer: str
    sources: list[SourceChunk]
    cache_tier: CacheTier
    query_complexity: QueryComplexity
    llm_response: LLMResponse | None = None
    memory_context: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-safe dict for cache storage."""
        return {
            "answer": self.answer,
            "sources": [
                {
                    "content": s.content,
                    "document_id": s.document_id,
                    "chunk_index": s.chunk_index,
                    "relevance_score": s.relevance_score,
                    "metadata": s.metadata,
                }
                for s in self.sources
            ],
            "cache_tier": self.cache_tier.value,
            "query_complexity": self.query_complexity.value,
            "memory_context": self.memory_context,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RetrievalResponse:
        """Reconstruct from cached dict."""
        return cls(
            answer=data["answer"],
            sources=[
                SourceChunk(
                    content=s["content"],
                    document_id=s["document_id"],
                    chunk_index=s["chunk_index"],
                    relevance_score=s["relevance_score"],
                    metadata=s.get("metadata", {}),
                )
                for s in data.get("sources", [])
            ],
            cache_tier=CacheTier(data.get("cache_tier", "MISS")),
            query_complexity=QueryComplexity(data.get("query_complexity", "moderate")),
            memory_context=data.get("memory_context", []),
            metadata=data.get("metadata", {}),
        )
