"""
Recursive text chunker — LangChain-style recursive splitting.

Splits on natural text boundaries (paragraphs → sentences → words)
attempting to keep semantically related content together.

This is the DEFAULT chunking strategy — balances quality vs. speed.

Design: STRATEGY PATTERN leaf — implements ChunkerProtocol.
"""
from __future__ import annotations

import re

from centrag.abstractions.chunker import (
    ChunkingConfig,
    ChunkingStrategy,
    ChunkResult,
    ChunkerProtocol,
)


# Separators ordered by preference (most to least natural)
DEFAULT_SEPARATORS = [
    "\n\n\n",     # Triple newline (section breaks)
    "\n\n",       # Double newline (paragraphs)
    "\n",         # Single newline
    ". ",         # Sentence boundary
    "? ",         # Question boundary
    "! ",         # Exclamation boundary
    "; ",         # Semicolon
    ", ",         # Comma
    " ",          # Word boundary (last resort)
]


class RecursiveChunker:
    """
    Recursively split text on progressively finer separators.

    Algorithm:
      1. Try splitting on "\n\n" (paragraphs)
      2. If chunks are too large, recurse with "\n" (lines)
      3. If still too large, recurse with ". " (sentences)
      4. Continue until chunks fit within chunk_size

    This preserves semantic coherence better than fixed-size because
    it splits at natural language boundaries.
    """

    @property
    def strategy(self) -> ChunkingStrategy:
        return ChunkingStrategy.RECURSIVE

    def chunk(
        self,
        text: str,
        config: ChunkingConfig | None = None,
        document_title: str = "",
        section_headers: list[str] | None = None,
    ) -> list[ChunkResult]:
        cfg = config or ChunkingConfig(strategy=ChunkingStrategy.RECURSIVE)

        raw_chunks = self._recursive_split(
            text=text,
            separators=DEFAULT_SEPARATORS,
            chunk_size=int(cfg.chunk_size * 0.75),  # words approximation
            chunk_overlap=int(cfg.chunk_overlap * 0.75),
            min_size=int(cfg.min_chunk_size * 0.75),
        )

        results: list[ChunkResult] = []
        current_pos = 0

        for idx, chunk_text in enumerate(raw_chunks):
            # Find the actual position in the original text
            pos = text.find(chunk_text[:50], current_pos)
            start_char = pos if pos >= 0 else current_pos
            end_char = start_char + len(chunk_text)

            # Context enrichment
            prefix_parts: list[str] = []
            if cfg.prepend_title and document_title:
                prefix_parts.append(f"[Document: {document_title}]")
            if cfg.prepend_headers and section_headers:
                prefix_parts.append(f"[Section: {' > '.join(section_headers)}]")

            enriched = chunk_text
            if prefix_parts:
                enriched = " ".join(prefix_parts) + "\n" + chunk_text

            results.append(
                ChunkResult(
                    content=enriched,
                    chunk_index=idx,
                    start_char=start_char,
                    end_char=end_char,
                    token_count=int(len(chunk_text.split()) * 1.3),
                    metadata={
                        "strategy": "recursive",
                        "document_title": document_title,
                    },
                )
            )
            current_pos = start_char + len(chunk_text) // 2  # Advance past overlap

        return results

    def _recursive_split(
        self,
        text: str,
        separators: list[str],
        chunk_size: int,
        chunk_overlap: int,
        min_size: int,
    ) -> list[str]:
        """Core recursive splitting algorithm."""

        if not text.strip():
            return []

        # Find the best separator (first one that actually splits the text)
        chosen_sep = ""
        for sep in separators:
            if sep in text:
                chosen_sep = sep
                break

        # Split on the chosen separator
        if chosen_sep:
            splits = text.split(chosen_sep)
        else:
            # No separator found — text is a single block, force word-level split
            words = text.split()
            if len(words) <= chunk_size:
                return [text] if len(words) >= min_size else []
            # Word-level chunking as fallback
            chunks = []
            for i in range(0, len(words), chunk_size - chunk_overlap):
                chunk = " ".join(words[i : i + chunk_size])
                if len(chunk.split()) >= min_size:
                    chunks.append(chunk)
            return chunks

        # Merge small splits into chunks
        chunks: list[str] = []
        current_chunk: list[str] = []
        current_size = 0

        for split in splits:
            split_size = len(split.split())

            if split_size > chunk_size:
                # This split is too large — recurse with next separator
                if current_chunk:
                    chunks.append(chosen_sep.join(current_chunk))
                    current_chunk = []
                    current_size = 0

                remaining_seps = separators[separators.index(chosen_sep) + 1:]
                if remaining_seps:
                    sub_chunks = self._recursive_split(
                        split, remaining_seps, chunk_size, chunk_overlap, min_size
                    )
                    chunks.extend(sub_chunks)
                else:
                    chunks.append(split)
                continue

            if current_size + split_size > chunk_size and current_chunk:
                chunks.append(chosen_sep.join(current_chunk))
                # Keep overlap by retaining last portion
                overlap_words = 0
                overlap_parts: list[str] = []
                for part in reversed(current_chunk):
                    overlap_words += len(part.split())
                    if overlap_words >= chunk_overlap:
                        break
                    overlap_parts.insert(0, part)
                current_chunk = overlap_parts
                current_size = sum(len(p.split()) for p in current_chunk)

            current_chunk.append(split)
            current_size += split_size

        if current_chunk and current_size >= min_size:
            chunks.append(chosen_sep.join(current_chunk))

        return chunks

    def chunk_boundaries(
        self,
        text: str,
        config: ChunkingConfig | None = None,
    ) -> list[tuple[int, int]]:
        results = self.chunk(text, config)
        return [r.boundary for r in results]
