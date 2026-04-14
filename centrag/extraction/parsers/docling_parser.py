"""
Docling Parser — Layout-aware document extraction using IBM's Docling.

Critical for:
- Preserving table structures (Markdown/HTML conversion).
- Identifying structural headers for "Situated Context" generation.
- Handling complex PDF layouts (multi-column, images).

Design Pattern: STRATEGY PATTERN
- Implements BaseParser to be a drop-in replacement for naive PDF/Docx parsers.
"""

from __future__ import annotations
from typing import TYPE_CHECKING, Any
from pathlib import Path
import tempfile
import os

from centrag.extraction.parsers.base import BaseParser, ExtractionResult, ExtractedDocument
from centrag.abstractions.extractor import ContentType
from centrag.utils.logger import get_logger

if TYPE_CHECKING:
    from centrag.config import Settings

logger = get_logger("extraction.parsers.docling")

class DoclingParser(BaseParser):
    """
    Advanced parser using Docling for structural extraction.
    
    Transforms PDFs, Docx, and images into high-fidelity Markdown 
    with preserved tables and hierarchical headers.
    """

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        # Deferred import to avoid overhead if not used
        try:
            from docling.datamodel.base_models import InputFormat
            from docling.document_converter import DocumentConverter
            self._converter = DocumentConverter()
            self._InputFormat = InputFormat
            logger.info("docling_converter_initialized")
        except ImportError:
            logger.error("docling_not_installed", message="Please run 'pip install docling'")
            self._converter = None

    async def parse(
        self,
        file_bytes: bytes,
        content_type: ContentType,
        filename: str,
    ) -> ExtractionResult:
        """Parse document using Docling structural analysis."""
        if not self._converter:
            raise RuntimeError("Docling is not installed or failed to initialize.")

        logger.info("docling_parsing_started", filename=filename, size=len(file_bytes))

        # Docling usually works better with files
        suffix = f".{filename.split('.')[-1]}" if "." in filename else ".tmp"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name

        try:
            # 1. Convert to Docling internal format
            result = self._converter.convert(tmp_path)
            
            # 2. Export to Markdown (best for LLM reasoning and chunking)
            markdown_content = result.document.export_to_markdown()
            
            # 3. Extract structural metadata
            metadata = {
                "docling_status": "success",
                "page_count": getattr(result.document, "num_pages", 1),
                "table_count": len([e for e in result.document.elements if e.label == "Table"]),
                "header_count": len([e for e in result.document.elements if e.label == "Heading"]),
            }

            doc = ExtractedDocument(
                text=markdown_content,
                metadata=metadata,
                content_type=content_type,
            )

            return ExtractionResult(document=doc)

        except Exception as e:
            logger.error("docling_parsing_failed", filename=filename, error=str(e))
            raise
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def can_handle(self, content_type: ContentType) -> bool:
        """Docling supports PDF, DOCX, PPTX, XLSX, and Images."""
        supported = {
            ContentType.PDF,
            ContentType.DOCX,
            ContentType.HTML,
        }
        return content_type in supported
