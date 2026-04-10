"""
PDF Parser — Extracts text from PDF documents using unstructured.

Falls back to OCR for scanned PDFs (when unstructured has tesseract available).

Design: This is a LEAF in the Strategy Pattern — implements ExtractorProtocol
        and is registered in ParserRegistry for ContentType.PDF.
"""
from __future__ import annotations

from centrag.utils.logger import get_logger

from centrag.abstractions.extractor import (
    ContentType,
    ExtractedDocument,
    ExtractedElement,
    ExtractorProtocol,
)

logger = get_logger("extraction.parsers.pdf")


class PDFParser:
    """
    Extract text from PDF files using the `unstructured` library.

    Supports:
      - Native text PDFs (fast, high quality)
      - Scanned/image PDFs (requires tesseract — slower, lower quality)
      - Mixed PDFs (both text and scanned pages)
    """

    def supported_types(self) -> list[ContentType]:
        return [ContentType.PDF]

    async def extract(
        self,
        file_bytes: bytes,
        content_type: ContentType,
        filename: str = "",
    ) -> ExtractedDocument:
        """Extract text from a PDF file."""
        import tempfile
        import os

        # unstructured requires a file path, not bytes
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name

        try:
            from unstructured.partition.pdf import partition_pdf

            elements = partition_pdf(
                filename=tmp_path,
                strategy="auto",  # auto-detects text vs. OCR
                include_page_breaks=True,
            )

            extracted_elements = []
            tables_count = 0
            images_count = 0

            for el in elements:
                el_type = type(el).__name__.lower()
                metadata = {}

                if hasattr(el, "metadata"):
                    if hasattr(el.metadata, "page_number"):
                        metadata["page_number"] = el.metadata.page_number
                    if hasattr(el.metadata, "coordinates"):
                        metadata["has_coordinates"] = True

                if "table" in el_type:
                    tables_count += 1
                    element_type = "table"
                elif "image" in el_type:
                    images_count += 1
                    element_type = "image_caption"
                elif "title" in el_type or "header" in el_type:
                    element_type = "header"
                elif "listitem" in el_type:
                    element_type = "list_item"
                else:
                    element_type = "paragraph"

                extracted_elements.append(
                    ExtractedElement(
                        content=str(el),
                        element_type=element_type,
                        metadata=metadata,
                    )
                )

            full_text = "\n\n".join(str(el) for el in elements if str(el).strip())

            # Attempt to extract title from first header element
            title = filename
            for el in extracted_elements:
                if el.element_type == "header" and el.content.strip():
                    title = el.content.strip()
                    break

            # Estimate page count from page number metadata
            page_numbers = [
                el.metadata.get("page_number", 0)
                for el in extracted_elements
                if el.metadata.get("page_number")
            ]
            page_count = max(page_numbers) if page_numbers else 0

            logger.info(
                "pdf_extracted",
                filename=filename,
                elements=len(extracted_elements),
                pages=page_count,
                tables=tables_count,
                chars=len(full_text),
            )

            return ExtractedDocument(
                text=full_text,
                elements=extracted_elements,
                title=title,
                content_type=ContentType.PDF,
                page_count=page_count,
                table_count=tables_count,
                image_count=images_count,
                char_count=len(full_text),
                metadata={"filename": filename, "parser": "unstructured"},
            )

        finally:
            os.unlink(tmp_path)

    async def extract_batch(
        self,
        files: list[tuple[bytes, ContentType, str]],
    ) -> list[ExtractedDocument]:
        """Extract multiple PDFs sequentially."""
        results = []
        for file_bytes, ct, filename in files:
            doc = await self.extract(file_bytes, ct, filename)
            results.append(doc)
        return results
