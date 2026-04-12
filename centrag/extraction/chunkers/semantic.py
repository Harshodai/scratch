"""
Semantic chunker — embedding-based boundary detection.

Splits documents at points where the topic shifts, detected by
measuring embedding similarity between adjacent sentences.

This is HIGHER QUALITY but SLOWER than recursive chunking because
it requires calling the embedding model for every sentence.

Design: STRATEGY PATTERN leaf — implements ChunkerProtocol.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable

from centrag.abstractions.chunker import (
    ChunkingConfig,
    ChunkingStrategy,
    ChunkResult,
)


def _split_into_sentences(text: str) -> list[str]:
    """Split text into sentences using regex."""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    return [s.strip() for s in sentences if s.strip()]


def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    if not vec_a or not vec_b:
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = sum(a * a for a in vec_a) ** 0.5
    norm_b = sum(b * b for b in vec_b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class SemanticChunker:
    """
    Split documents at semantic boundaries.

    Algorithm:
      1. Split text into sentences
      2. Embed each sentence
      3. For each adjacent pair, compute cosine similarity
      4. When similarity drops below threshold → insert boundary
      5. Group sentences between boundaries into chunks

    Requires an embedding function to be injected — this keeps the
    chunker decoupled from any specific embedding provider.
    """

    def __init__(
        self,
        embed_fn: Callable[[list[str]], Awaitable[list[list[float]]]],
    ) -> None:
        """
        Args:
            embed_fn: Async function that embeds a list of strings.
                      Injected from the EmbedderProtocol implementation.
                      Signature: async (texts: list[str]) -> list[list[float]]
        """
        self._embed_fn = embed_fn

    @property
    def strategy(self) -> ChunkingStrategy:
        return ChunkingStrategy.SEMANTIC

    def chunk(
        self,
        text: str,
        config: ChunkingConfig | None = None,
        document_title: str = "",
        section_headers: list[str] | None = None,
    ) -> list[ChunkResult]:
        """
        Synchronous interface — wraps the async implementation.

        WARNING: Only works when called OUTSIDE an async event loop.
        From async code (e.g., ExtractionPipeline.process()), call
        chunk_async() directly instead.
        """
        import asyncio

        try:
            asyncio.get_running_loop()
            # Already in async context — cannot use asyncio.run().
            # Run in a dedicated thread with its own event loop.
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(
                    asyncio.run,
                    self.chunk_async(text, config, document_title, section_headers),
                )
                return future.result()
        except RuntimeError:
            # No running loop — safe to use asyncio.run
            return asyncio.run(self.chunk_async(text, config, document_title, section_headers))

    async def chunk_async(
        self,
        text: str,
        config: ChunkingConfig | None = None,
        document_title: str = "",
        section_headers: list[str] | None = None,
    ) -> list[ChunkResult]:
        """Async semantic chunking — the real implementation."""
        cfg = config or ChunkingConfig(strategy=ChunkingStrategy.SEMANTIC)

        sentences = _split_into_sentences(text)
        if len(sentences) <= 1:
            return (
                [
                    ChunkResult(
                        content=text,
                        chunk_index=0,
                        start_char=0,
                        end_char=len(text),
                        token_count=int(len(text.split()) * 1.3),
                        metadata={"strategy": "semantic"},
                    )
                ]
                if text.strip()
                else []
            )

        # Embed all sentences
        embeddings = await self._embed_fn(sentences)

        # Find semantic boundaries
        boundaries: list[int] = [0]
        for i in range(len(embeddings) - 1):
            sim = _cosine_similarity(embeddings[i], embeddings[i + 1])
            if sim < cfg.similarity_threshold:
                boundaries.append(i + 1)
        boundaries.append(len(sentences))

        # Group sentences between boundaries
        results: list[ChunkResult] = []
        current_pos = 0

        for idx in range(len(boundaries) - 1):
            start_idx = boundaries[idx]
            end_idx = boundaries[idx + 1]
            chunk_sentences = sentences[start_idx:end_idx]
            chunk_text = " ".join(chunk_sentences)

            # Skip if too small
            if len(chunk_text.split()) < int(cfg.min_chunk_size * 0.75):
                continue

            # Truncate if too large
            words = chunk_text.split()
            max_words = int(cfg.max_chunk_size * 0.75)
            if len(words) > max_words:
                chunk_text = " ".join(words[:max_words])

            # Context enrichment
            prefix_parts: list[str] = []
            if cfg.prepend_title and document_title:
                prefix_parts.append(f"[Document: {document_title}]")
            if cfg.prepend_headers and section_headers:
                prefix_parts.append(f"[Section: {' > '.join(section_headers)}]")

            enriched = chunk_text
            if prefix_parts:
                enriched = " ".join(prefix_parts) + "\n" + chunk_text

            start_char = text.find(chunk_sentences[0], current_pos)
            if start_char < 0:
                start_char = current_pos
            end_char = start_char + len(chunk_text)

            results.append(
                ChunkResult(
                    content=enriched,
                    chunk_index=len(results),
                    start_char=start_char,
                    end_char=end_char,
                    token_count=int(len(chunk_text.split()) * 1.3),
                    metadata={
                        "strategy": "semantic",
                        "boundary_similarity": cfg.similarity_threshold,
                        "document_title": document_title,
                    },
                )
            )
            current_pos = end_char

        return results

    def chunk_boundaries(
        self,
        text: str,
        config: ChunkingConfig | None = None,
    ) -> list[tuple[int, int]]:
        results = self.chunk(text, config)
        return [r.boundary for r in results]
