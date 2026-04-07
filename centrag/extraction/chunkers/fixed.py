"""
Fixed-size chunker — baseline chunking strategy.

Splits text into chunks of `chunk_size` tokens with `chunk_overlap` overlap.
Simple, fast, predictable. Good baseline before evaluating smarter strategies.

Design: STRATEGY PATTERN leaf — implements ChunkerProtocol.
"""
from __future__ import annotations

from centrag.abstractions.chunker import (
    ChunkingConfig,
    ChunkingStrategy,
    ChunkResult,
    ChunkerProtocol,
)


class FixedChunker:
    """
    Fixed-size chunker with configurable overlap.

    Splits text by word count (approximating tokens at ~1.3x words).
    Overlap ensures context is preserved across chunk boundaries.
    """

    @property
    def strategy(self) -> ChunkingStrategy:
        return ChunkingStrategy.FIXED

    def chunk(
        self,
        text: str,
        config: ChunkingConfig | None = None,
        document_title: str = "",
        section_headers: list[str] | None = None,
    ) -> list[ChunkResult]:
        cfg = config or ChunkingConfig(strategy=ChunkingStrategy.FIXED)
        words = text.split()

        if not words:
            return []

        # Approximate: 1 token ≈ 0.75 words (conservative)
        words_per_chunk = int(cfg.chunk_size * 0.75)
        overlap_words = int(cfg.chunk_overlap * 0.75)
        min_words = int(cfg.min_chunk_size * 0.75)

        chunks: list[ChunkResult] = []
        start = 0
        chunk_index = 0

        while start < len(words):
            end = min(start + words_per_chunk, len(words))
            chunk_words = words[start:end]

            if len(chunk_words) < min_words and chunks:
                # Too small — merge with previous chunk
                break

            chunk_text = " ".join(chunk_words)

            # Context enrichment: prepend document title and section headers
            prefix_parts: list[str] = []
            if cfg.prepend_title and document_title:
                prefix_parts.append(f"[Document: {document_title}]")
            if cfg.prepend_headers and section_headers:
                prefix_parts.append(f"[Section: {' > '.join(section_headers)}]")

            if prefix_parts:
                chunk_text = " ".join(prefix_parts) + "\n" + chunk_text

            # Calculate character offsets in original text
            start_char = len(" ".join(words[:start])) + (1 if start > 0 else 0)
            end_char = start_char + len(" ".join(chunk_words))

            chunks.append(
                ChunkResult(
                    content=chunk_text,
                    chunk_index=chunk_index,
                    start_char=start_char,
                    end_char=end_char,
                    token_count=int(len(chunk_words) * 1.3),
                    metadata={
                        "strategy": "fixed",
                        "document_title": document_title,
                    },
                )
            )

            chunk_index += 1
            start = end - overlap_words if end < len(words) else end

        return chunks

    def chunk_boundaries(
        self,
        text: str,
        config: ChunkingConfig | None = None,
    ) -> list[tuple[int, int]]:
        """Return (start_char, end_char) boundaries without extracting text."""
        results = self.chunk(text, config)
        return [r.boundary for r in results]
