"""
Cohere Reranker — Production cross-encoder reranking via Cohere Rerank v3.

The WHY:
    Initial retrieval (Bi-Encoder, BM25) is FAST but IMPRECISE because it
    processes query and document independently. Cross-encoder reranking
    processes query AND document TOGETHER through an attention mechanism,
    yielding much higher-fidelity relevance scores.

    Impact: Consistently improves Precision@5 by 15-30% over Bi-Encoder alone.

    Why Cohere over a local CrossEncoder?
      - No GPU needed (API-based) → simpler deployment
      - Rerank v3 handles 100+ documents in ~200ms
      - Language-agnostic (multilingual enterprise support)
      - Already a dependency in pyproject.toml (cohere>=5.11.0)

Design Pattern: STRATEGY — implements RerankerProtocol.
SOLID: Liskov — drop-in replacement for NoOpReranker.
"""

from __future__ import annotations

from centrag.abstractions.reranker import RerankResult
from centrag.utils.logger import get_logger

logger = get_logger("implementations.cohere_reranker")


class CohereReranker:
    """Production reranker using Cohere's Rerank API (v3).

    Cross-encoder architecture: processes (query, document) pairs
    jointly through an attention mechanism for high-fidelity scoring.

    Implements RerankerProtocol for seamless integration with the
    CentRAG retrieval pipeline.

    Usage:
        reranker = CohereReranker(api_key="co-...")
        results = await reranker.rerank(
            query="What are the compliance risks?",
            documents=retrieved_chunks,
            top_n=5,
        )
        # Results are sorted by relevance_score (descending)
        # Use results[0].is_confident for CRAG gating
    """

    def __init__(
        self,
        api_key: str,
        model: str = "rerank-v3.5",
    ) -> None:
        """
        Args:
            api_key: Cohere API key.
            model: Rerank model identifier. Options:
                - "rerank-v3.5": Latest, best quality (default)
                - "rerank-english-v3.0": English-only, slightly faster
                - "rerank-multilingual-v3.0": Multilingual support
        """
        self._api_key = api_key
        self._model = model
        self._client = None

    def _get_client(self):
        """Lazy-initialize Cohere client."""
        if self._client is None:
            import cohere

            self._client = cohere.Client(api_key=self._api_key)
        return self._client

    async def rerank(
        self,
        query: str,
        documents: list[str],
        top_n: int = 5,
    ) -> list[RerankResult]:
        """Rerank documents by cross-encoder relevance to query.

        The WHY:
            Stage 1 (Bi-Encoder + BM25) retrieves ~20-50 candidate chunks.
            Stage 2 (this method) re-scores them with a cross-encoder
            to surface the most relevant chunks for the LLM context window.

        Args:
            query: The user's search query.
            documents: Candidate chunks from Stage 1 retrieval.
            top_n: Number of top results to return.

        Returns:
            List of RerankResult sorted by descending relevance_score.
        """
        if not documents:
            return []

        if not query.strip():
            logger.warning("cohere_rerank_empty_query")
            return [RerankResult(index=i, text=doc, relevance_score=0.0) for i, doc in enumerate(documents[:top_n])]

        try:
            client = self._get_client()

            # Cohere Rerank API call
            # Using sync client in async context (Cohere SDK is sync)
            # For production, wrap in asyncio.to_thread()
            import asyncio

            response = await asyncio.to_thread(
                client.rerank,
                model=self._model,
                query=query,
                documents=documents,
                top_n=min(top_n, len(documents)),
            )

            results = []
            for item in response.results:
                results.append(
                    RerankResult(
                        index=item.index,
                        text=documents[item.index],
                        relevance_score=round(item.relevance_score, 4),
                    )
                )

            logger.info(
                "cohere_rerank_completed",
                query_len=len(query),
                input_docs=len(documents),
                output_docs=len(results),
                top_score=results[0].relevance_score if results else 0.0,
                model=self._model,
            )

            return results

        except ImportError:
            logger.error(
                "cohere_not_installed",
                message="Install cohere: pip install cohere>=5.11.0",
            )
            return self._fallback_rerank(documents, top_n)

        except Exception as e:
            logger.error("cohere_rerank_failed", error=str(e))
            return self._fallback_rerank(documents, top_n)

    def _fallback_rerank(
        self,
        documents: list[str],
        top_n: int,
    ) -> list[RerankResult]:
        """Graceful degradation: return documents in original order.

        The WHY:
            Never let a reranker failure block the pipeline. Original
            Bi-Encoder ordering is "good enough" as a fallback.
        """
        logger.warning("cohere_rerank_fallback", message="Using original order")
        return [RerankResult(index=i, text=doc, relevance_score=0.5) for i, doc in enumerate(documents[:top_n])]
