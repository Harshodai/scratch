"""
NoOp Reranker — Development/testing reranker implementation.

Returns results in original order with synthetic relevance scores
based on simple keyword overlap with the query.

Production replacement: CohereReranker, CrossEncoderReranker.
"""

from __future__ import annotations

from centrag.abstractions.reranker import RerankResult
from centrag.utils.logger import get_logger

logger = get_logger("implementations.reranker.noop")


class NoOpReranker:
    """
    Keyword-overlap reranker for development/testing.

    Scores documents by counting word overlap with the query,
    then sorts by score. Good enough to validate pipeline flow.

    Implements RerankerProtocol.
    """

    async def rerank(
        self,
        query: str,
        documents: list[str],
        top_n: int = 5,
    ) -> list[RerankResult]:
        """
        Rerank documents by keyword overlap with query.

        Returns top_n results sorted by relevance score.
        """
        if not documents:
            return []

        query_words = set(query.lower().split())

        scored: list[tuple[int, float, str]] = []
        for i, doc in enumerate(documents):
            doc_words = set(doc.lower().split())
            if not doc_words:
                score = 0.0
            else:
                overlap = len(query_words & doc_words)
                score = min(overlap / max(len(query_words), 1), 1.0)
                # Blend with position bias (earlier docs score slightly higher)
                position_bonus = 0.1 * (1.0 - i / max(len(documents), 1))
                score = min(score + position_bonus, 1.0)
            scored.append((i, score, doc))

        # Sort by score descending
        scored.sort(key=lambda x: x[1], reverse=True)

        results = [
            RerankResult(
                index=idx,
                text=text,
                relevance_score=round(score, 4),
            )
            for idx, score, text in scored[:top_n]
        ]

        logger.debug(
            "noop_rerank",
            query_preview=query[:50],
            input_count=len(documents),
            output_count=len(results),
            top_score=results[0].relevance_score if results else 0,
        )

        return results
