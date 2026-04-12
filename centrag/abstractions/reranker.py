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
    """A single document chunk after being re-scored by a Cross-Encoder.

    The WHY:
        Initial vector retrieval (Bi-Encoder) is fast but sometimes
        imprecise. Reranking (Cross-Encoder) is slower but reflects
        the true semantic relationship between query and chunk.
        This object stores that high-fidelity relevance score.

    Attributes:
        index: Original position in the pre-reranked list (for traceability).
        text: The content of the chunk.
        relevance_score: A normalized score (0.0 to 1.0) of relevance.
    """

    index: int  # Original position in the input list
    text: str
    relevance_score: float  # 0.0 to 1.0

    @property
    def is_confident(self) -> bool:
        """CRAG: Is this chunk confidently relevant?

        The WHY:
            In Corrective RAG (CRAG), if no results meet a confidence
            threshold, the system should trigger a search rewrite or
            web-search fallback rather than hallucinating an answer.
        """
        return self.relevance_score >= 0.5


@runtime_checkable
class RerankerProtocol(Protocol):
    """Contract for precision reranking implementations.

    The WHY:
        This protocol enables a "Two-Stage Retrieval" architecture.
        Stage 1 filters millions of docs to hundreds; Stage 2
        (this protocol) re-scores those hundreds to provide the
        absolute best context to the LLM.

    Design Goal:
        Provide swappable reranking strategies (e.g., Cohere,
        BGE-Reranker, or NoOp for speed).
    """

    async def rerank(
        self,
        query: str,
        documents: list[str],
        top_n: int = 5,
    ) -> list[RerankResult]:
        """Rerank a set of documents based on a query.

        Args:
            query: The user's input string.
            documents: List of text chunks retrieved in Stage 1.
            top_n: Number of high-confidence results to return.

        Returns:
            list[RerankResult]: Sorted list of documents by descending relevance.

        Usage:
            >>> results = await reranker.rerank(query, chunks, top_n=3)
            >>> confident_results = [r for r in results if r.is_confident]
        """
        ...
