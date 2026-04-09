"""
Hybrid Retriever — Fuses results from BOTH retrieval paths.

SHARED INFRASTRUCTURE: Combines VECTORLESS (PageIndex) and VECTOR (Qdrant)
retrieval results using Reciprocal Rank Fusion (RRF).

RRF formula: score(d) = Σ 1/(k + rank_i(d))
    where k=60 (standard), rank_i(d) = rank of document d in result list i.

Why RRF over simple score averaging?
    - Scores from different systems are NOT comparable (cosine sim vs LLM confidence)
    - RRF is rank-based, so scale differences don't matter
    - Proven effective in MS MARCO, BEIR benchmarks

Design Pattern: COMPOSITE — combines two retrieval strategies into one result.

SOLID: Single Responsibility — only fuses results. No retrieval logic.
SOLID: Open/Closed — add more retrieval paths by extending the fusion, not modifying it.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger("retrieval.hybrid")


@dataclass(frozen=True)
class FusedResult:
    """
    A single result from RRF fusion, with provenance tracking.

    Tracks which path(s) contributed this result and the fusion score.
    """
    content: str
    document_id: str
    rrf_score: float
    sources: list[str]          # ["pageindex", "vector"] — which paths found this
    relevance_score: float = 0.0  # Original score from best source
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HybridResult:
    """
    Complete result from the hybrid retriever.

    Includes both fused results and per-path diagnostics for evaluation.
    """
    fused: list[FusedResult]
    pageindex_count: int = 0
    vector_count: int = 0
    fusion_method: str = "rrf"
    k_parameter: int = 60


class HybridRetriever:
    """
    Fuses results from PageIndex and Vector retrieval using RRF.

    SHARED INFRASTRUCTURE — runs both paths in parallel, then fuses.

    Usage:
        hybrid = HybridRetriever(k=60)
        result = hybrid.fuse(
            pageindex_results=pi_results,
            vector_results=vec_results,
            top_n=10,
        )

    Parallel execution:
        Both paths run concurrently via asyncio.gather().
        The engine calls this after collecting results from both paths.
    """

    def __init__(self, k: int = 60) -> None:
        """
        Args:
            k: RRF constant. Higher k = less emphasis on top ranks.
                k=60 is the standard from the original RRF paper.
        """
        self._k = k

    def fuse(
        self,
        pageindex_results: list[dict[str, Any]],
        vector_results: list[dict[str, Any]],
        top_n: int = 10,
    ) -> HybridResult:
        """
        Fuse results from both paths using RRF.

        Each result dict MUST have:
            - "content": str
            - "document_id": str
            - "relevance_score": float (optional, for metadata)
            - "metadata": dict (optional)

        Results are deduplicated by document_id + content hash.
        """
        # Build RRF score map: key → cumulative RRF score
        score_map: dict[str, float] = {}
        result_map: dict[str, dict[str, Any]] = {}
        source_map: dict[str, list[str]] = {}

        # Process PageIndex results
        for rank, result in enumerate(pageindex_results, start=1):
            key = self._result_key(result)
            rrf_score = 1.0 / (self._k + rank)
            score_map[key] = score_map.get(key, 0.0) + rrf_score
            if key not in result_map:
                result_map[key] = result
            source_map.setdefault(key, []).append("pageindex")

        # Process Vector results
        for rank, result in enumerate(vector_results, start=1):
            key = self._result_key(result)
            rrf_score = 1.0 / (self._k + rank)
            score_map[key] = score_map.get(key, 0.0) + rrf_score
            if key not in result_map:
                result_map[key] = result
            source_map.setdefault(key, []).append("vector")

        # Sort by RRF score (descending)
        sorted_keys = sorted(score_map.keys(), key=lambda k: score_map[k], reverse=True)

        # Build fused results
        fused: list[FusedResult] = []
        for key in sorted_keys[:top_n]:
            result = result_map[key]
            fused.append(FusedResult(
                content=result.get("content", ""),
                document_id=result.get("document_id", ""),
                rrf_score=score_map[key],
                sources=list(set(source_map.get(key, []))),
                relevance_score=result.get("relevance_score", 0.0),
                metadata=result.get("metadata", {}),
            ))

        logger.info(
            "hybrid_fusion_complete",
            pageindex_count=len(pageindex_results),
            vector_count=len(vector_results),
            fused_count=len(fused),
            top_rrf_score=fused[0].rrf_score if fused else 0.0,
        )

        return HybridResult(
            fused=fused,
            pageindex_count=len(pageindex_results),
            vector_count=len(vector_results),
            fusion_method="rrf",
            k_parameter=self._k,
        )

    @staticmethod
    def _result_key(result: dict[str, Any]) -> str:
        """
        Generate a deduplication key for a result.

        Uses document_id + first 100 chars of content for uniqueness.
        Two results from different paths that refer to the same content
        will be merged (their RRF scores will be summed).
        """
        doc_id = result.get("document_id", "")
        content_prefix = result.get("content", "")[:100]
        return f"{doc_id}:{hash(content_prefix)}"
