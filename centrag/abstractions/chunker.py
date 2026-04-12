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
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable


class ChunkingStrategy(StrEnum):
    """Available chunking strategies in the CentRAG pipeline.

    The WHY:
        One size does NOT fit all in RAG. Fixed-size chunking is safe
        but often breaks sentences. Semantic chunking is precise
        but slow. Structure-aware chunking is ideal for manuals
        with headers. This enum allows selecting the right "Lens"
        for each document type.
    """

    FIXED = "fixed"  # Fixed-size with overlap (baseline)
    RECURSIVE = "recursive"  # Recursive text splitting (LangChain-style)
    SEMANTIC = "semantic"  # Embedding-based semantic boundary detection
    STRUCTURE_AWARE = "structure_aware"  # Header/section-aware splitting
    PROPOSITION = "proposition"  # Atomic fact extraction (RAG Made Simple Ch 4)


@dataclass(frozen=True)
class ChunkingConfig:
    """Configuration for document segmentation behavior.

    The WHY:
        RAG performance is highly sensitive to "Chunk Size" and
        "Overlap." Too small, and the LLM lacks context; too large,
        and irrelevant noise dilutes the retrieved signal. This config
        acts as the "Control Panel" for retrieval precision.

    Attributes:
        strategy: The logic used to detect split points.
        chunk_size: Target token count for each segment.
        chunk_overlap: Shared tokens between adjacent chunks (prevents edge-cutting).
        enable_contextual_retrieval: 2024 Anthropic pattern to prepend summaries.
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
    """Immutable chunk with FULL PROVENANCE for downstream indexing.

    The WHY:
        Reliable citation is the #1 requirement for enterprise RAG.
        Without capturing the `page_number`, `section_title`, and
        `char_offset` during chunking, the system cannot generate
        trustworthy links back to the source document.

    Attributes:
        content: The text segment designated for retrieval.
        chunk_index: Chronological position in the parent document.
        start_char: Absolute character offset (used for highlighting).
        token_count: Computed or estimated token length for LLM budget.
        doc_id: UUID of the source document for relational linking.
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
        """Alias for start_char — matches specification naming conventions."""
        return self.start_char

    @property
    def boundary(self) -> tuple[int, int]:
        """Character boundary for late chunking integration.

        Usage:
            >>> boundaries = [c.boundary for c in doc_chunks]
            >>> await embedder.embed_with_late_chunking(full_text, boundaries)
        """
        return (self.start_char, self.end_char)

    def to_dict(self) -> dict[str, Any]:
        """Serialize for JSON storage, cache, or API transport."""
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
    """Contract for text segmentation implementations.

    The WHY:
        Separates text splitting from the ingestion pipeline.
        Implementations can range from simple character splitters to
        advanced LLM-based proposition splitters, all using the
        same interface.

    Design Goal:
        Provide high-precision boundaries for BOTH standard
        retrieval and context-aware Late Chunking.
    """

    @property
    def strategy(self) -> ChunkingStrategy:
        """Which strategy this specific chunker provides."""
        ...

    def chunk(
        self,
        text: str,
        config: ChunkingConfig | None = None,
        document_title: str = "",
        section_headers: list[str] | None = None,
    ) -> list[ChunkResult]:
        """Split document text into contextually-rich chunks.

        Args:
            text: Raw document text extracted by an Extractor.
            config: Parameter overrides for this specific document.
            document_title: Global title for context enrichment.
            section_headers: List of parent headings for hierarchy awareness.

        Returns:
            list[ChunkResult]: A list of metadata-rich chunks ready for embedding.
        """
        ...

    def chunk_boundaries(
        self,
        text: str,
        config: ChunkingConfig | None = None,
    ) -> list[tuple[int, int]]:
        """Identify splitting points WITHOUT performing text extraction.

        The WHY:
            Crucial for Late Chunking. To preserve full-document context,
            the embedder needs the boundaries first to pool tokens correctly
            across the entire model attention window.

        Returns:
            list[tuple[int, int]]: A list of (start_char, end_char) boundaries.
        """
        ...
