"""
BGE Reranker v2 (M3) — State-of-the-art open-source reranking.

The WHY:
    While FlashRank is lightweight, BGE-Reranker-v2-m3 is a much more powerful
    Cross-Encoder that supports multi-lingual, multi-task, and multi-granularity
    reranking. It is essential for complex enterprise queries where semantic
    precision is more important than millisecond latency.

    The `normalize=True` flag (confirmed via FlagEmbedding docs and web research)
    applies a sigmoid function to raw logit scores, mapping them to [0, 1].
    This is REQUIRED because RerankResult.relevance_score is documented as 0.0-1.0.

    Reference: https://github.com/FlagOpen/FlagEmbedding

    Pattern: STRATEGY — implements RerankerProtocol.
    SOLID: Liskov — drop-in replacement for FlashRankReranker and CohereReranker.
"""

from __future__ import annotations

import asyncio

from centrag.abstractions.reranker import RerankResult
from centrag.utils.logger import get_logger

logger = get_logger("implementations.bge_reranker")


class BGEV2Reranker:
    """BAAI/bge-reranker-v2-m3 implementation.

    Requires `FlagEmbedding` package: ``pip install FlagEmbedding``

    Selection Hierarchy (wired in wiring.py):
      1. CENTRAG_COHERE_API_KEY set  →  CohereReranker (production, best quality)
      2. FlagEmbedding importable    →  BGEV2Reranker (local, free, SOTA quality)
      3. flashrank importable        →  FlashRankReranker (local, ultra-light, good quality)
      4. fallback                    →  NoOpReranker (keyword overlap, dev only)
    """

    def __init__(
        self,
        model_name: str = "BAAI/bge-reranker-v2-m3",
        use_fp16: bool = True,
    ) -> None:
        """
        Args:
            model_name: HuggingFace model identifier.
            use_fp16: Use half-precision for faster inference on supported hardware.
        """
        self._model_name = model_name
        self._use_fp16 = use_fp16
        self._model = None

    def _load_model(self):
        """Lazy-initialize FlagReranker.

        The WHY:
            Lazy loading avoids model download at import time.
            First call triggers model download; subsequent calls are instant.
        """
        if self._model is None:
            try:
                from FlagEmbedding import FlagReranker

                self._model = FlagReranker(self._model_name, use_fp16=self._use_fp16)
                logger.info("bge_reranker_loaded", model=self._model_name)
            except ImportError:
                logger.error(
                    "flag_embedding_not_installed",
                    message="Install FlagEmbedding: pip install FlagEmbedding",
                )
                raise
        return self._model

    async def rerank(
        self,
        query: str,
        documents: list[str],
        top_n: int = 5,
    ) -> list[RerankResult]:
        """Rerank documents using BGE-v2-M3 cross-encoder.

        The WHY:
            Provides SOTA semantic reranking locally without any external API call.
            The cross-encoder jointly attends to (query, document) pairs, producing
            higher-fidelity relevance scores than bi-encoder cosine similarity alone.

        Args:
            query: The user's search query.
            documents: Candidate chunks from Stage 1 retrieval.
            top_n: Number of top results to return.

        Returns:
            List of RerankResult sorted by descending relevance_score (0.0-1.0).
        """
        if not documents:
            return []

        if not query.strip():
            logger.warning("bge_rerank_empty_query")
            return [RerankResult(index=i, text=doc, relevance_score=0.0) for i, doc in enumerate(documents[:top_n])]

        try:
            model = await asyncio.to_thread(self._load_model)

            # BGE expects pairs: [[query, doc1], [query, doc2], ...]
            pairs = [[query, doc] for doc in documents]

            # CRITICAL: normalize=True applies sigmoid to raw logits,
            # mapping scores to [0, 1] range. Without this, scores can be
            # negative or >1, breaking RerankResult.is_confident checks.
            # Verified via: FlagEmbedding docs + HuggingFace model card.
            scores = await asyncio.to_thread(model.compute_score, pairs, normalize=True)

            # If only one document, scores is a float, not a list
            if isinstance(scores, (int, float)):
                scores = [scores]

            # Combine with indices and sort by descending score
            results = []
            for i, (doc, score) in enumerate(zip(documents, scores, strict=False)):
                results.append(
                    RerankResult(
                        index=i,
                        text=doc,
                        relevance_score=round(float(score), 4),
                    )
                )

            results.sort(key=lambda x: x.relevance_score, reverse=True)

            logger.info(
                "bge_rerank_completed",
                query_len=len(query),
                input_docs=len(documents),
                output_docs=min(top_n, len(results)),
                top_score=results[0].relevance_score if results else 0.0,
                model=self._model_name,
            )

            return results[:top_n]

        except ImportError:
            logger.error(
                "flag_embedding_not_installed",
                message="Install FlagEmbedding: pip install FlagEmbedding",
            )
            return self._fallback_rerank(documents, top_n)

        except Exception as e:
            logger.error("bge_rerank_failed", error=str(e))
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
        logger.warning("bge_rerank_fallback", message="Using original order")
        return [RerankResult(index=i, text=doc, relevance_score=0.5) for i, doc in enumerate(documents[:top_n])]
