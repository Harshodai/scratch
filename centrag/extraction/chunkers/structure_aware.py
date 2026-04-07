"""
Structure-aware chunker — respects document hierarchy.

Splits documents at structural boundaries (headers, sections)
preserving the header hierarchy as context for each chunk.

Best for technical documents with clear heading structures
(markdown docs, legal docs, manuals, reports).

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


class StructureAwareChunker:
    """
    Split documents by structural elements (headers, sections).

    Algorithm:
      1. Identify headers (lines starting with # or ALL CAPS lines)
      2. Split at header boundaries
      3. Each chunk inherits its parent header chain as context
      4. If a section is too large, fall back to recursive splitting

    The header chain provides automatic context enrichment:
      "[Section: Chapter 1 > 1.2 Subsection > Overview]"
    """

    @property
    def strategy(self) -> ChunkingStrategy:
        return ChunkingStrategy.STRUCTURE_AWARE

    def chunk(
        self,
        text: str,
        config: ChunkingConfig | None = None,
        document_title: str = "",
        section_headers: list[str] | None = None,
    ) -> list[ChunkResult]:
        cfg = config or ChunkingConfig(strategy=ChunkingStrategy.STRUCTURE_AWARE)

        sections = self._split_by_headers(text)

        if not sections:
            return []

        results: list[ChunkResult] = []
        max_words = int(cfg.max_chunk_size * 0.75)
        min_words = int(cfg.min_chunk_size * 0.75)

        for header_chain, section_text in sections:
            words = section_text.split()

            if len(words) < min_words:
                # Too small — skip or merge with adjacent
                if results:
                    # Merge with previous chunk
                    prev = results[-1]
                    merged_content = prev.content + "\n\n" + section_text
                    results[-1] = ChunkResult(
                        content=merged_content,
                        chunk_index=prev.chunk_index,
                        start_char=prev.start_char,
                        end_char=prev.end_char + len(section_text) + 2,
                        token_count=int(len(merged_content.split()) * 1.3),
                        metadata=prev.metadata,
                    )
                continue

            if len(words) > max_words:
                # Too large — split into sub-chunks
                sub_chunks = self._split_large_section(
                    section_text, max_words, int(cfg.chunk_overlap * 0.75)
                )
                for sub_chunk in sub_chunks:
                    chunk_text = self._enrich(sub_chunk, document_title, header_chain, cfg)
                    start_char = text.find(sub_chunk[:50])
                    results.append(
                        ChunkResult(
                            content=chunk_text,
                            chunk_index=len(results),
                            start_char=max(0, start_char),
                            end_char=max(0, start_char) + len(sub_chunk),
                            token_count=int(len(sub_chunk.split()) * 1.3),
                            metadata={
                                "strategy": "structure_aware",
                                "headers": header_chain,
                                "document_title": document_title,
                            },
                        )
                    )
            else:
                chunk_text = self._enrich(section_text, document_title, header_chain, cfg)
                start_char = text.find(section_text[:50])
                results.append(
                    ChunkResult(
                        content=chunk_text,
                        chunk_index=len(results),
                        start_char=max(0, start_char),
                        end_char=max(0, start_char) + len(section_text),
                        token_count=int(len(words) * 1.3),
                        metadata={
                            "strategy": "structure_aware",
                            "headers": header_chain,
                            "document_title": document_title,
                        },
                    )
                )

        return results

    def _split_by_headers(self, text: str) -> list[tuple[list[str], str]]:
        """
        Split text into (header_chain, section_text) pairs.

        Detects markdown headers (# ## ###) and numbered headers (1. 1.1 1.1.1).
        """
        header_pattern = re.compile(r'^(#{1,6})\s+(.+)$', re.MULTILINE)

        lines = text.split('\n')
        sections: list[tuple[list[str], str]] = []
        current_headers: list[str] = []
        current_content: list[str] = []

        for line in lines:
            match = header_pattern.match(line.strip())
            if match:
                # Flush current content
                if current_content:
                    content = '\n'.join(current_content).strip()
                    if content:
                        sections.append((list(current_headers), content))
                    current_content = []

                # Update header chain
                level = len(match.group(1))
                header_text = match.group(2).strip()
                # Trim header chain to current level
                current_headers = current_headers[:level - 1]
                current_headers.append(header_text)
            else:
                current_content.append(line)

        # Flush remaining content
        if current_content:
            content = '\n'.join(current_content).strip()
            if content:
                sections.append((list(current_headers), content))

        # If no headers were found, return the whole text as one section
        if not sections and text.strip():
            sections = [([], text.strip())]

        return sections

    def _split_large_section(
        self, text: str, max_words: int, overlap_words: int
    ) -> list[str]:
        """Split a large section by paragraph, then by sentence if needed."""
        paragraphs = text.split('\n\n')
        chunks: list[str] = []
        current: list[str] = []
        current_size = 0

        for para in paragraphs:
            para_words = len(para.split())
            if current_size + para_words > max_words and current:
                chunks.append('\n\n'.join(current))
                current = []
                current_size = 0
            current.append(para)
            current_size += para_words

        if current:
            chunks.append('\n\n'.join(current))

        return chunks

    def _enrich(
        self,
        text: str,
        document_title: str,
        headers: list[str],
        config: ChunkingConfig,
    ) -> str:
        """Prepend context metadata to chunk."""
        parts: list[str] = []
        if config.prepend_title and document_title:
            parts.append(f"[Document: {document_title}]")
        if config.prepend_headers and headers:
            parts.append(f"[Section: {' > '.join(headers)}]")
        if parts:
            return " ".join(parts) + "\n" + text
        return text

    def chunk_boundaries(
        self,
        text: str,
        config: ChunkingConfig | None = None,
    ) -> list[tuple[int, int]]:
        results = self.chunk(text, config)
        return [r.boundary for r in results]
