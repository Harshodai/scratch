"""
FlashRank Reranker — Free, local cross-encoder reranking (no API key).

The WHY:
    FlashRank fills the gap between NoOpReranker (keyword heuristic) and
    CohereReranker (requires API key + network).  It runs a lightweight
    TinyBERT cross-encoder (~4 MB) locally on CPU, delivering real
    semantic reranking with <100 ms latency and zero external calls.

    Selection Hierarchy (wired in wiring.py):
      1. CENTRAG_COHERE_API_KEY set  →  CohereReranker (production, best quality)
      2. flashrank importable         →  FlashRankReranker (local, free, good quality)
      3. fallback                     →  NoOpReranker (keyword overlap, dev only)

    Why FlashRank?
      - No API key, no GPU, no PyTorch dependency
      - ~4 MB model (ms-marco-TinyBERT-L-2-v2), auto-downloaded on first use
      - Apache 2.0 license — safe for enterprise
      - pip install flashrank

Design Pattern: STRATEGY — implements RerankerProtocol.
SOLID: Liskov — drop-in replacement for NoOpReranker and CohereReranker.
"""

from __future__ import annotations

from centrag.abstractions.reranker import RerankResult
from centrag.utils.logger import get_logger

logger = get_logger("implementations.flashrank_reranker")


class FlashRankReranker:
    """Local cross-encoder reranker using FlashRank (TinyBERT).

    Runs entirely on CPU with no API key required.
    Uses the ms-marco-TinyBERT-L-2-v2 model by default (~4 MB).

    Implements RerankerProtocol for seamless integration with the
    CentRAG retrieval pipeline.

    Usage:
        reranker = FlashRankReranker()
        results = await reranker.rerank(
            query="What are the compliance risks?",
            documents=retrieved_chunks,
            top_n=5,
        )
    """

    def __init__(
        self,
        model_name: str = "ms-marco-TinyBERT-L-2-v2",
    ) -> None:
        """
        Args:
            model_name: FlashRank model identifier. Options:
                - "ms-marco-TinyBERT-L-2-v2": Ultra-light, ~4 MB (default)
                - "ms-marco-MiniLM-L-12-v2": Better quality, ~120 MB
                - "rank-T5-flan": T5-based, largest/best quality
        """
        self._model_name = model_name
        self._ranker = None

    def _get_ranker(self):
        """Lazy-initialize FlashRank Ranker.

        The WHY:
            Lazy loading avoids model download at import time.
            First call triggers ~4 MB download; subsequent calls are instant.
        """
        if self._ranker is None:
            from flashrank import Ranker

            self._ranker = Ranker(model_name=self._model_name)
            logger.info(
                "flashrank_model_loaded",
                model=self._model_name,
            )
        return self._ranker

    async def rerank(
        self,
        query: str,
        documents: list[str],
        top_n: int = 5,
    ) -> list[RerankResult]:
        """Rerank documents using local FlashRank cross-encoder.

        The WHY:
            Provides real semantic reranking without any external API call.
            The TinyBERT cross-encoder jointly attends to (query, document)
            pairs, producing higher-fidelity relevance scores than
            bi-encoder cosine similarity alone.

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
            logger.warning("flashrank_rerank_empty_query")
            return [RerankResult(index=i, text=doc, relevance_score=0.0) for i, doc in enumerate(documents[:top_n])]

        try:
            ranker = self._get_ranker()

            # FlashRank expects list of dicts with "id" and "text" keys
            passages = [{"id": str(i), "text": doc} for i, doc in enumerate(documents)]

            # FlashRank Ranker.rerank() is synchronous and CPU-bound.
            # Wrap in asyncio.to_thread to avoid blocking the event loop.
            import asyncio

            reranked = await asyncio.to_thread(
                ranker.rerank,
                query=query,
                passages=passages,
            )

            # Take top_n results and convert to RerankResult
            results = []
            for item in reranked[:top_n]:
                idx = int(item["id"])
                results.append(
                    RerankResult(
                        index=idx,
                        text=documents[idx],
                        relevance_score=round(float(item["score"]), 4),
                    )
                )

            logger.info(
                "flashrank_rerank_completed",
                query_len=len(query),
                input_docs=len(documents),
                output_docs=len(results),
                top_score=results[0].relevance_score if results else 0.0,
                model=self._model_name,
            )

            return results

        except ImportError:
            logger.error(
                "flashrank_not_installed",
                message="Install flashrank: pip install flashrank",
            )
            return self._fallback_rerank(documents, top_n)

        except Exception as e:
            logger.error("flashrank_rerank_failed", error=str(e))
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
        logger.warning("flashrank_rerank_fallback", message="Using original order")
        return [RerankResult(index=i, text=doc, relevance_score=0.5) for i, doc in enumerate(documents[:top_n])]


"""
Description:
    FlashRank fills the second tier in the reranker selection hierarchy.
    Cohere (API) > FlashRank (local) > NoOp (keyword).
    No GPU, no API key, no PyTorch. Just pip install flashrank.
"""
