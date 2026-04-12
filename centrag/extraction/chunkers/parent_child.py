"""
Parent-Child Chunker — Small chunks for search, parent chunks for LLM context.

Implements the recommended production pattern:
    1. Create PARENT chunks (~512 tokens) — fed to the LLM as context
    2. Create CHILD chunks (~128 tokens) — stored in vector DB for search
    3. Each child stores parent_chunk_id so retrieval can "zoom out"

Why this pattern?
    Small chunks match queries with higher precision (better recall).
    But the LLM needs broader context to generate a coherent answer.
    Parent-child bridging gives you BOTH benefits.

Design Pattern: STRATEGY — implements ChunkerProtocol.
SOLID: Open/Closed — new chunking strategy, no existing code modified.
"""

from __future__ import annotations

import hashlib

from centrag.abstractions.chunker import (
    ChunkingConfig,
    ChunkingStrategy,
    ChunkResult,
)

# Parent: ~512 tokens (~384 words), Child: ~128 tokens (~96 words)
DEFAULT_PARENT_SIZE = 384  # words (approximation for tokens)
DEFAULT_CHILD_SIZE = 96  # words
DEFAULT_CHILD_OVERLAP = 16  # words overlap between child chunks


class ParentChildChunker:
    """
    Create parent chunks (LLM context) and child chunks (vector search).

    Hierarchy:
        Document
         └── Parent Chunk (512 tokens, ~3 paragraphs)
              ├── Child Chunk 1 (128 tokens)
              ├── Child Chunk 2 (128 tokens)
              ├── Child Chunk 3 (128 tokens)
              └── Child Chunk 4 (128 tokens)

    During retrieval:
        1. Search vector DB → finds Child Chunk 2 (best match)
        2. Look up child.parent_chunk_id → Parent Chunk
        3. Feed Parent Chunk to LLM (broader context)

    Usage:
        chunker = ParentChildChunker()
        parents, children = chunker.chunk_with_parents(text, doc_id="abc")
        # Store children in vector DB
        # Store parents in document store for LLM context
    """

    def __init__(
        self,
        parent_size: int = DEFAULT_PARENT_SIZE,
        child_size: int = DEFAULT_CHILD_SIZE,
        child_overlap: int = DEFAULT_CHILD_OVERLAP,
    ) -> None:
        self._parent_size = parent_size
        self._child_size = child_size
        self._child_overlap = child_overlap

    @property
    def strategy(self) -> ChunkingStrategy:
        return ChunkingStrategy.RECURSIVE  # Uses recursive as base

    def chunk(
        self,
        text: str,
        config: ChunkingConfig | None = None,
        document_title: str = "",
        section_headers: list[str] | None = None,
    ) -> list[ChunkResult]:
        """
        Returns CHILD chunks only (for vector DB storage).

        Use chunk_with_parents() to get both parent and child chunks.
        """
        _, children = self.chunk_with_parents(
            text,
            doc_id="",
            document_title=document_title,
            section_headers=section_headers,
        )
        return children

    def chunk_with_parents(
        self,
        text: str,
        doc_id: str = "",
        source_type: str = "",
        document_title: str = "",
        section_headers: list[str] | None = None,
    ) -> tuple[list[ChunkResult], list[ChunkResult]]:
        """
        Create parent and child chunks.

        Returns:
            (parent_chunks, child_chunks) — both lists of ChunkResult.
            Each child has parent_chunk_id linking to its parent.
        """
        words = text.split()
        if not words:
            return [], []

        parents: list[ChunkResult] = []
        children: list[ChunkResult] = []

        # Step 1: Create parent chunks
        parent_idx = 0
        pos = 0  # word position

        while pos < len(words):
            parent_words = words[pos : pos + self._parent_size]
            parent_text = " ".join(parent_words)

            # Compute stable chunk ID from content hash
            parent_id = self._make_chunk_id(doc_id, parent_idx, parent_text)

            # Character offsets
            start_char = text.find(parent_text[:50], 0 if not parents else parents[-1].end_char)
            if start_char < 0:
                start_char = 0
            end_char = start_char + len(parent_text)

            parent = ChunkResult(
                content=parent_text,
                chunk_index=parent_idx,
                start_char=start_char,
                end_char=end_char,
                token_count=int(len(parent_words) * 1.3),
                doc_id=doc_id,
                source_type=source_type,
                section_title=document_title,
                chunk_id=parent_id,
                parent_chunk_id=None,  # Parents have no parent
                metadata={
                    "chunk_type": "parent",
                    "child_count": 0,  # Updated below
                },
            )
            parents.append(parent)

            # Step 2: Create child chunks from this parent
            child_idx_in_parent = 0
            child_pos = 0  # word position within parent

            while child_pos < len(parent_words):
                child_words = parent_words[child_pos : child_pos + self._child_size]
                child_text = " ".join(child_words)

                if len(child_words) < 10:  # Skip tiny tail chunks
                    break

                child_id = self._make_chunk_id(doc_id, parent_idx * 100 + child_idx_in_parent, child_text)

                # Context enrichment
                prefix_parts: list[str] = []
                if document_title:
                    prefix_parts.append(f"[Document: {document_title}]")
                if section_headers:
                    prefix_parts.append(f"[Section: {' > '.join(section_headers)}]")

                enriched = child_text
                if prefix_parts:
                    enriched = " ".join(prefix_parts) + "\n" + child_text

                c_start = text.find(child_text[:40], start_char)
                if c_start < 0:
                    c_start = start_char

                child = ChunkResult(
                    content=enriched,
                    chunk_index=len(children),
                    start_char=c_start,
                    end_char=c_start + len(child_text),
                    token_count=int(len(child_words) * 1.3),
                    doc_id=doc_id,
                    source_type=source_type,
                    section_title=document_title,
                    chunk_id=child_id,
                    parent_chunk_id=parent_id,  # Link to parent!
                    metadata={
                        "chunk_type": "child",
                        "parent_index": parent_idx,
                    },
                )
                children.append(child)
                child_idx_in_parent += 1

                child_pos += self._child_size - self._child_overlap

            # Update parent metadata with actual child count
            parents[-1] = ChunkResult(
                content=parent.content,
                chunk_index=parent.chunk_index,
                start_char=parent.start_char,
                end_char=parent.end_char,
                token_count=parent.token_count,
                doc_id=parent.doc_id,
                source_type=parent.source_type,
                section_title=parent.section_title,
                chunk_id=parent.chunk_id,
                parent_chunk_id=None,
                metadata={
                    "chunk_type": "parent",
                    "child_count": child_idx_in_parent,
                },
            )

            parent_idx += 1
            pos += self._parent_size

        return parents, children

    def chunk_boundaries(
        self,
        text: str,
        config: ChunkingConfig | None = None,
    ) -> list[tuple[int, int]]:
        """Return child chunk boundaries."""
        children = self.chunk(text, config)
        return [c.boundary for c in children]

    @staticmethod
    def _make_chunk_id(doc_id: str, index: int, content: str) -> str:
        """Create a stable, deterministic chunk ID."""
        seed = f"{doc_id}:{index}:{content[:100]}"
        return hashlib.sha256(seed.encode()).hexdigest()[:16]
