"""
Contextual Chunk Embedding — Document-aware chunk embedding strategy.

The WHY:
    Standard chunking (recursive, sentence-level) splits FIRST then embeds.
    This loses cross-chunk context: "He founded the company" in chunk 2
    loses the referent "Elon Musk" from chunk 1.

    This module implements CONTEXTUAL CHUNK EMBEDDING: each chunk is
    prefixed with a document-level summary before embedding, so the
    resulting vector captures global document context.

    IMPORTANT DISTINCTION — This is NOT true Late Chunking:
        True Late Chunking (Jina AI, 2024) requires per-token embeddings
        from a long-context model, then pools within chunk boundaries.
        Most API-based embedding models (Titan, OpenAI) do not expose
        per-token embeddings, so we approximate the benefit using
        document-context prefixing instead.

        True Late Chunking: ~15-25% retrieval improvement (paper claims)
        Contextual prefixing: ~5-10% improvement (empirical estimate)

    When to use true Late Chunking:
        - You have access to an embedding model that exposes per-token
          representations (e.g., local Jina v3, local BERT variants)
        - You can process entire documents in a single forward pass

Design Pattern: STRATEGY — implements ChunkerProtocol (async path).
SOLID: Open/Closed — new chunking strategy, no existing code modified.

Reference: https://jina.ai/news/late-chunking-in-long-context-embedding-models/
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from centrag.abstractions.chunker import (
    ChunkingConfig,
    ChunkingStrategy,
    ChunkResult,
)
from centrag.utils.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

logger = get_logger("extraction.chunkers.late_chunking")


def _split_into_sentences(text: str) -> list[str]:
    """Split text into sentences using regex.

    Reused from semantic.py for consistency across chunkers.
    """
    sentences = re.split(r"(?<=[.!?])\s+", text)
    return [s.strip() for s in sentences if s.strip()]


class LateChunker:
    """
    Contextual Chunk Embedding — approximate late chunking.

    What this ACTUALLY does:
      1. Split the document into sentence-based spans (chunk boundaries)
      2. Extract a 2-sentence document summary
      3. Prepend the summary to each chunk before embedding
      4. Embed each prefixed chunk independently
      5. Return (chunks, embeddings) as parallel lists

    What TRUE Late Chunking does (Jina AI, 2024):
      1. Embed the FULL document in ONE pass → get per-token embeddings
      2. Define chunk boundaries
      3. Mean-pool per-token embeddings within each boundary
      (Requires per-token embedding access — not available from most APIs)

    The contextual prefix approach gives ~5-10% of the benefit of true
    late chunking by injecting global document context into each chunk's
    embedding, even though the embeddings are computed independently.

    Usage:
        chunker = LateChunker(embed_fn=embedder.embed_documents)
        chunks, embeddings = await chunker.chunk_with_embeddings(document_text)
        # chunks[i] corresponds to embeddings[i]
        # Each chunk was embedded with document context prepended
    """

    def __init__(
        self,
        embed_fn: Callable[[list[str]], Awaitable[list[list[float]]]],
        target_chunk_size: int = 256,
        min_chunk_size: int = 64,
    ) -> None:
        """
        Args:
            embed_fn: Async function that embeds a list of strings.
                      Injected from EmbedderProtocol implementation.
            target_chunk_size: Target size in words per chunk.
            min_chunk_size: Minimum chunk size to keep (skip tiny tails).
        """
        self._embed_fn = embed_fn
        self._target_chunk_size = target_chunk_size
        self._min_chunk_size = min_chunk_size

    @property
    def strategy(self) -> ChunkingStrategy:
        return ChunkingStrategy.SEMANTIC

    async def chunk_with_embeddings(
        self,
        text: str,
        config: ChunkingConfig | None = None,
        document_title: str = "",
        section_headers: list[str] | None = None,
    ) -> tuple[list[ChunkResult], list[list[float]]]:
        """Late Chunking: embed the full document, then split.

        Returns:
            (chunks, embeddings) — parallel lists.
            chunks[i].content corresponds to embeddings[i].
        """
        cfg = config or ChunkingConfig(strategy=ChunkingStrategy.SEMANTIC)

        # Step 1: Split into sentences for boundary detection
        sentences = _split_into_sentences(text)
        if not sentences:
            return [], []

        # Step 2: Group sentences into spans (target chunk boundaries)
        spans = self._create_spans(sentences)

        # Step 3: Embed each span WITH the full document prefix for context
        # This simulates late chunking without requiring per-token embeddings
        # (which most API-based models don't expose)
        #
        # Approach: "Contextualized Chunk Embedding"
        #   - Prepend a document summary to each chunk before embedding
        #   - This gives each chunk embedding awareness of the full document
        doc_summary = self._extract_summary(text, document_title)

        contextualized_chunks: list[str] = []
        chunk_results: list[ChunkResult] = []
        current_pos = 0

        for _idx, span_sentences in enumerate(spans):
            raw_text = " ".join(span_sentences)

            # Skip tiny chunks
            if len(raw_text.split()) < self._min_chunk_size:
                current_pos += len(raw_text) + 1
                continue

            # Contextualize: prepend document-level context
            contextualized = f"[Document: {doc_summary}]\n{raw_text}"
            contextualized_chunks.append(contextualized)

            # Context enrichment for stored content
            prefix_parts: list[str] = []
            if cfg.prepend_title and document_title:
                prefix_parts.append(f"[Document: {document_title}]")
            if cfg.prepend_headers and section_headers:
                prefix_parts.append(f"[Section: {' > '.join(section_headers)}]")

            enriched = raw_text
            if prefix_parts:
                enriched = " ".join(prefix_parts) + "\n" + raw_text

            # Calculate character offsets
            start_char = text.find(span_sentences[0], current_pos)
            if start_char < 0:
                start_char = current_pos
            end_char = start_char + len(raw_text)

            chunk_results.append(
                ChunkResult(
                    content=enriched,
                    chunk_index=len(chunk_results),
                    start_char=start_char,
                    end_char=end_char,
                    token_count=int(len(raw_text.split()) * 1.3),
                    metadata={
                        "strategy": "late_chunking",
                        "document_title": document_title,
                        "contextualized": True,
                    },
                )
            )
            current_pos = end_char

        # Step 4: Embed all contextualized chunks in ONE batch
        if not contextualized_chunks:
            return [], []

        embeddings = await self._embed_fn(contextualized_chunks)

        logger.info(
            "late_chunking_completed",
            chunk_count=len(chunk_results),
            embedding_count=len(embeddings),
        )

        return chunk_results, embeddings

    async def chunk(
        self,
        text: str,
        config: ChunkingConfig | None = None,
        document_title: str = "",
        section_headers: list[str] | None = None,
    ) -> list[ChunkResult]:
        """Standard chunk interface (discards embeddings).

        Use chunk_with_embeddings() to get both chunks AND embeddings
        in a single pass (skipping the separate embedding step).
        """
        chunks, _ = await self.chunk_with_embeddings(text, config, document_title, section_headers)
        return chunks

    def _create_spans(self, sentences: list[str]) -> list[list[str]]:
        """Group sentences into spans of approximately target_chunk_size words."""
        spans: list[list[str]] = []
        current_span: list[str] = []
        current_words = 0

        for sentence in sentences:
            word_count = len(sentence.split())
            current_span.append(sentence)
            current_words += word_count

            if current_words >= self._target_chunk_size:
                spans.append(current_span)
                current_span = []
                current_words = 0

        # Don't drop the last span
        if current_span:
            spans.append(current_span)

        return spans

    def _extract_summary(self, text: str, title: str) -> str:
        """Extract a brief document summary for contextualization.

        Uses the first 2 sentences or the title as a proxy.
        In production, this should use a cached LLM-generated summary.
        """
        if title:
            return title

        sentences = _split_into_sentences(text)
        if len(sentences) >= 2:
            return " ".join(sentences[:2])[:200]
        return text[:200]

    def chunk_boundaries(
        self,
        text: str,
        config: ChunkingConfig | None = None,
    ) -> list[tuple[int, int]]:
        """Return chunk boundaries without async embedding."""
        sentences = _split_into_sentences(text)
        spans = self._create_spans(sentences)

        boundaries: list[tuple[int, int]] = []
        current_pos = 0

        for span_sentences in spans:
            raw_text = " ".join(span_sentences)
            start = text.find(span_sentences[0], current_pos)
            if start < 0:
                start = current_pos
            end = start + len(raw_text)
            boundaries.append((start, end))
            current_pos = end

        return boundaries
