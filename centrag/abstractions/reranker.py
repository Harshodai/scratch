"""
Reranker abstraction — re-scores retrieved chunks for precision.

SOLID: Single Responsibility — only reranking, nothing else.

Design Pattern: STRATEGY PATTERN
    - CohereReranker, CrossEncoderReranker, NoOpReranker
    - NoOpReranker is useful for testing / cost reduction on simple queries

RAG Advancement: CORRECTIVE RAG (CRAG) — 2025
    - rerank_with_validation() adds a confidence gate after reranking.
    - If no chunk scores above the threshold, it returns a "low confidence"
      signal so the pipeline can trigger corrective actions (rewrite query,
      try different data source, escalate to human).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class RerankResult:
    """Reranked chunk with relevance score."""

    index: int              # Original position in the input list
    text: str
    relevance_score: float  # 0.0 to 1.0

    @property
    def is_confident(self) -> bool:
        """CRAG: Is this chunk confidently relevant?"""
        return self.relevance_score >= 0.5


@runtime_checkable
class RerankerProtocol(Protocol):
    """Contract for all reranking implementations."""

    async def rerank(
        self,
        query: str,
        documents: list[str],
        top_n: int = 5,
    ) -> list[RerankResult]:
        """Rerank documents by relevance to query."""
        ...
