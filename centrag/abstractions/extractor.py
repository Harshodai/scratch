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
from enum import Enum
from typing import Any, Protocol, runtime_checkable


class ContentType(str, Enum):
    """Supported document content types."""
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
    """A single extracted element (paragraph, table, header, etc.)."""
    content: str
    element_type: str  # "paragraph" | "table" | "header" | "list_item" | "image_caption"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExtractedDocument:
    """
    Immutable result of document extraction.

    Contains the full extracted text, individual structural elements,
    and document-level metadata (title, author, page count, etc.).
    """
    text: str                                        # Full cleaned text
    elements: list[ExtractedElement] = field(default_factory=list)
    title: str = ""
    content_type: ContentType = ContentType.PLAIN_TEXT
    page_count: int = 0
    table_count: int = 0
    image_count: int = 0
    char_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)  # author, date, etc.

    def __post_init__(self):
        # frozen=True means we can't assign, but we validate
        if not self.text and not self.elements:
            raise ValueError("ExtractedDocument must have text or elements.")


@runtime_checkable
class ExtractorProtocol(Protocol):
    """Contract for all document parsers/extractors."""

    def supported_types(self) -> list[ContentType]:
        """List of content types this extractor can handle."""
        ...

    async def extract(
        self,
        file_bytes: bytes,
        content_type: ContentType,
        filename: str = "",
    ) -> ExtractedDocument:
        """
        Extract structured text from a raw file.

        Args:
            file_bytes:   Raw file content.
            content_type: MIME type of the file.
            filename:     Original filename (used for metadata).

        Returns:
            ExtractedDocument with full text, elements, and metadata.
        """
        ...

    async def extract_batch(
        self,
        files: list[tuple[bytes, ContentType, str]],
    ) -> list[ExtractedDocument]:
        """
        Extract multiple files. Default: sequential. Override for parallelism.

        Args:
            files: List of (file_bytes, content_type, filename) tuples.
        """
        ...
