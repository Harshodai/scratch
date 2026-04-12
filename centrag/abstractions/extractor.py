"""
Extractor abstraction — converts raw files to structured text.

SOLID: Interface Segregation — extraction is SEPARATE from chunking.
       The pipeline first extracts, then chunks. Different concerns.

SOLID: Dependency Inversion — the extraction pipeline depends on this
       protocol, not on any specific parser (unstructured, docling, etc.).

Design Pattern: STRATEGY PATTERN
    - PDFExtractor, DOCXExtractor, HTMLExtractor all implement this
    - Selected at runtime based on content_type

Design Pattern: TEMPLATE METHOD
    - ExtractionPipeline.run() defines the flow:
      Parse → Clean → Enrich Metadata → Return
    - Each parser provides the "parse" step; cleaning/enrichment is shared
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Protocol, runtime_checkable


class ContentType(StrEnum):
    """Supported document content types in the CentRAG ingestion pipeline.

    The WHY:
        Strict MIME type mapping ensures that the ExtractionPipeline
        routes files to the correct specialized parser (e.g., PyMuPDF
        for PDFs vs. Pandas for CSVs), preventing parsing errors
        and data corruption.

    Usage:
        >>> if content_type == ContentType.PDF:
        >>>     # invoke PDF strategy
    """

    PDF = "application/pdf"
    DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    DOC = "application/msword"
    HTML = "text/html"
    MARKDOWN = "text/markdown"
    PLAIN_TEXT = "text/plain"
    CSV = "text/csv"
    XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    JSON = "application/json"


@dataclass(frozen=True)
class ExtractedElement:
    """A single structural element extracted from a document.

    The WHY:
        Standard RAG often treats documents as monolithic text blocks.
        By breaking documents into typed "Elements" (Header, Table,
        Paragraph), we enable structure-aware chunking and
        high-fidelity retrieval (e.g., retrieving a specific
        table rather than surrounding text).

    Attributes:
        content: The raw text or data string of the element.
        element_type: Category (e.g., "table", "header", "list_item").
        metadata: Block-specific data (e.g., table row count, header level).
    """

    content: str
    element_type: str  # "paragraph" | "table" | "header" | "list_item" | "image_caption"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExtractedDocument:
    """Immutable result of the document extraction process.

    The WHY:
        Acts as the unified "Information Carrier" between the raw
        parser and the downstream chunking/embedding stages.

        ARCHITECTURE NOTE: frozen=True prevents field reassignment,
        but does not automatically freeze mutable contents (lists/dicts).
        To ensure production-grade immutability, __post_init__ converts
        collections to immutable types (tuple/MappingProxyType).

    Attributes:
        text: The full, cleaned, and concatenated text of the document.
        elements: Optional tuple of structured blocks (tables, lists).
        title: Descriptive title extracted from document properties.
        content_type: The validated MIME type of the original source.
        page_count: Number of physical pages (if applicable).
        metadata: Global attributes like author, creation_date, or source_url.
    """

    text: str  # Full cleaned text
    elements: list[ExtractedElement] | tuple[ExtractedElement, ...] = field(default_factory=list)
    title: str = ""
    content_type: ContentType = ContentType.PLAIN_TEXT
    page_count: int = 0
    table_count: int = 0
    image_count: int = 0
    char_count: int = 0
    metadata: dict[str, Any] | MappingProxyType[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        # Enforce technical immutability for mutable collections
        # Since frozen=True is used, we must use object.__setattr__
        if not isinstance(self.elements, tuple):
            object.__setattr__(self, "elements", tuple(self.elements))
        if not isinstance(self.metadata, MappingProxyType):
            object.__setattr__(self, "metadata", MappingProxyType(self.metadata))

        if not self.text and not self.elements:
            raise ValueError("ExtractedDocument must have text or elements.")


@runtime_checkable
class ExtractorProtocol(Protocol):
    """Contract for all document parsers and extractors.

    The WHY:
        This protocol implements the STRATEGY PATTERN for ingestion.
        It allows CentRAG to support 10+ file formats while keeping the
        ExtractionPipeline logic simple and agnostic to the underlying
        parsing library (e.g., Unstructured.io vs. Docling).

    Design Goal:
        Standardize the conversion from raw binary blobs to
        richly-structured `ExtractedDocument` objects.
    """

    def supported_types(self) -> list[ContentType]:
        """List of content types this specific extractor is qualified to handle.

        Returns:
            list[ContentType]: A list of compatible MIME types.
        """
        ...

    async def extract(
        self,
        file_bytes: bytes,
        content_type: ContentType,
        filename: str = "",
    ) -> ExtractedDocument:
        """Extract structured text and metadata from a raw file.

        Args:
            file_bytes: The raw binary content of the file.
            content_type: Validated MIME type of the file.
            filename: Original name (used for title guessing and logging).

        Returns:
            ExtractedDocument: The resulting structured data object.

        Raises:
            ParsingError: If the file is corrupted or format is unsupported.
        """
        ...

    async def extract_batch(
        self,
        files: list[tuple[bytes, ContentType, str]],
    ) -> list[ExtractedDocument]:
        """Extract multiple files in a single operation.

        Optimization:
            Implementations should override this to use parallel
            processing (e.g., ThreadPoolExecutor) for large batches.

        Args:
            files: List of (bytes, content_type, filename) triples.

        Returns:
            list[ExtractedDocument]: A list of results in the same order as input.
        """
        ...
