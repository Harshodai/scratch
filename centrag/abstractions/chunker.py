"""
Chunker abstraction — splits extracted text into retrieval-sized chunks.

SOLID: Single Responsibility — chunking is SEPARATE from extraction and embedding.
       Extract → Chunk → Embed is a three-step pipeline with clear boundaries.

SOLID: Open/Closed — add new chunking strategies without modifying existing code.
       Just implement ChunkerProtocol and register via config.

Design Pattern: STRATEGY PATTERN
    - FixedChunker, RecursiveChunker, SemanticChunker, StructureAwareChunker
    - Selected at runtime based on ChunkingStrategy enum

IMPORTANT: Late Chunking is NOT a chunking strategy — it's an EMBEDDING strategy.
    Late Chunking embeds the full document first, then pools per chunk boundary.
    The existing EmbedderProtocol.embed_with_late_chunking() handles this.
    The chunker provides chunk_boundaries to the embedder.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable


class ChunkingStrategy(str, Enum):
    """Available chunking strategies."""

    FIXED = "fixed"  # Fixed-size with overlap (baseline)
    RECURSIVE = "recursive"  # Recursive text splitting (LangChain-style)
    SEMANTIC = "semantic"  # Embedding-based semantic boundary detection
    STRUCTURE_AWARE = "structure_aware"  # Header/section-aware splitting
    PROPOSITION = "proposition"  # Atomic fact extraction (RAG Made Simple Ch 4)


@dataclass(frozen=True)
class ChunkingConfig:
    """
    Configuration for chunking behavior.

    Policy-as-code: these settings control chunk size, overlap,
    and strategy selection per document or globally.
    """

    strategy: ChunkingStrategy = ChunkingStrategy.RECURSIVE
    chunk_size: int = 512  # Target tokens per chunk
    chunk_overlap: int = 64  # Token overlap between adjacent chunks
    min_chunk_size: int = 50  # Skip chunks smaller than this
    max_chunk_size: int = 1024  # Hard cap — never exceed this
    # Semantic chunking specific
    similarity_threshold: float = 0.5  # Split when adjacent similarity drops below
    # Context enrichment
    prepend_title: bool = True  # Prepend document title to each chunk
    prepend_headers: bool = True  # Prepend section headers to each chunk
    # Anthropic Contextual Retrieval (2024)
    enable_contextual_retrieval: bool = False  # Prepend LLM-generated context summary


@dataclass(frozen=True)
class ChunkResult:
    """
    Immutable chunk with FULL PROVENANCE for downstream embedding + retrieval.

    Each chunk carries complete citation metadata. Without this,
    retrieval citations are unreliable and Knowledge Graph anchors
    have no reference points.

    Required by spec:
        {chunk_id, doc_id, source_type, section_title, page_number,
         char_offset, token_count, s3_url}
    """

    # Core content
    content: str  # The chunk text
    chunk_index: int  # Position in document
    start_char: int  # Character offset in source
    end_char: int  # Character offset in source
    token_count: int  # Estimated token count

    # Provenance fields (required for reliable citations)
    doc_id: str = ""  # Parent document UUID
    source_type: str = ""  # "pdf", "csv", "markdown", etc.
    section_title: str = ""  # Heading this chunk lives under
    page_number: int | None = None  # PDF page number (None for non-PDF)
    s3_url: str = ""  # Source URL if from cloud storage

    # Parent-child indexing (Phase 4)
    parent_chunk_id: str | None = None  # For child chunks → parent reference
    chunk_id: str = ""  # Unique chunk identifier

    # Extensible metadata
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def char_offset(self) -> int:
        """Alias for start_char — matches spec field name."""
        return self.start_char

    @property
    def boundary(self) -> tuple[int, int]:
        """Character boundary for late chunking integration with EmbedderProtocol."""
        return (self.start_char, self.end_char)

    def to_dict(self) -> dict[str, Any]:
        """Serialize for JSON storage / cache."""
        return {
            "chunk_id": self.chunk_id,
            "chunk_index": self.chunk_index,
            "doc_id": self.doc_id,
            "source_type": self.source_type,
            "section_title": self.section_title,
            "page_number": self.page_number,
            "char_offset": self.start_char,
            "token_count": self.token_count,
            "s3_url": self.s3_url,
            "parent_chunk_id": self.parent_chunk_id,
            "content_preview": self.content[:100],
            **self.metadata,
        }


@runtime_checkable
class ChunkerProtocol(Protocol):
    """Contract for all chunking implementations."""

    @property
    def strategy(self) -> ChunkingStrategy:
        """Which strategy this chunker implements."""
        ...

    def chunk(
        self,
        text: str,
        config: ChunkingConfig | None = None,
        document_title: str = "",
        section_headers: list[str] | None = None,
    ) -> list[ChunkResult]:
        """
        Split text into chunks according to the strategy.

        Args:
            text:             Full document text to chunk.
            config:           Override default config for this call.
            document_title:   Prepended to each chunk if config.prepend_title.
            section_headers:  Section headers for context enrichment.

        Returns:
            Ordered list of ChunkResult, each with content and metadata.

        Design: This is a synchronous operation — chunking is CPU-bound,
                not I/O-bound. No async needed.
        """
        ...

    def chunk_boundaries(
        self,
        text: str,
        config: ChunkingConfig | None = None,
    ) -> list[tuple[int, int]]:
        """
        Return chunk boundaries WITHOUT extracting text.

        Used by EmbedderProtocol.embed_with_late_chunking() to know
        where to pool token embeddings.

        Returns:
            List of (start_char, end_char) tuples.
        """
        ...
