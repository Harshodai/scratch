"""
Text / Markdown / HTML / DOCX parsers — lightweight extractors.

These handle non-PDF document types using unstructured or built-in parsing.
Each class implements ExtractorProtocol and registers for its content types.
"""
from __future__ import annotations

import structlog

from centrag.abstractions.extractor import (
    ContentType,
    ExtractedDocument,
    ExtractedElement,
    ExtractorProtocol,
)

logger = structlog.get_logger("extraction.parsers.text")


class PlainTextParser:
    """Passthrough parser for plain text files."""

    def supported_types(self) -> list[ContentType]:
        return [ContentType.PLAIN_TEXT, ContentType.MARKDOWN]

    async def extract(
        self,
        file_bytes: bytes,
        content_type: ContentType,
        filename: str = "",
    ) -> ExtractedDocument:
        text = file_bytes.decode("utf-8", errors="replace")

        # For markdown, extract headers as elements
        elements: list[ExtractedElement] = []
        if content_type == ContentType.MARKDOWN:
            for line in text.split("\n"):
                stripped = line.strip()
                if stripped.startswith("#"):
                    elements.append(
                        ExtractedElement(content=stripped.lstrip("# "), element_type="header")
                    )
                elif stripped:
                    elements.append(
                        ExtractedElement(content=stripped, element_type="paragraph")
                    )
        else:
            for para in text.split("\n\n"):
                if para.strip():
                    elements.append(
                        ExtractedElement(content=para.strip(), element_type="paragraph")
                    )

        return ExtractedDocument(
            text=text,
            elements=elements,
            title=filename,
            content_type=content_type,
            char_count=len(text),
            metadata={"filename": filename, "parser": "plaintext"},
        )

    async def extract_batch(
        self,
        files: list[tuple[bytes, ContentType, str]],
    ) -> list[ExtractedDocument]:
        return [await self.extract(fb, ct, fn) for fb, ct, fn in files]


class HTMLParser:
    """Extract text from HTML documents using unstructured."""

    def supported_types(self) -> list[ContentType]:
        return [ContentType.HTML]

    async def extract(
        self,
        file_bytes: bytes,
        content_type: ContentType,
        filename: str = "",
    ) -> ExtractedDocument:
        import tempfile
        import os

        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name

        try:
            from unstructured.partition.html import partition_html

            elements = partition_html(filename=tmp_path)

            extracted_elements = [
                ExtractedElement(
                    content=str(el),
                    element_type="header" if "title" in type(el).__name__.lower() else "paragraph",
                )
                for el in elements
                if str(el).strip()
            ]

            full_text = "\n\n".join(str(el) for el in elements if str(el).strip())

            return ExtractedDocument(
                text=full_text,
                elements=extracted_elements,
                title=filename,
                content_type=ContentType.HTML,
                char_count=len(full_text),
                metadata={"filename": filename, "parser": "unstructured_html"},
            )
        finally:
            os.unlink(tmp_path)

    async def extract_batch(
        self,
        files: list[tuple[bytes, ContentType, str]],
    ) -> list[ExtractedDocument]:
        return [await self.extract(fb, ct, fn) for fb, ct, fn in files]


class DOCXParser:
    """Extract text from DOCX documents using unstructured."""

    def supported_types(self) -> list[ContentType]:
        return [ContentType.DOCX, ContentType.DOC]

    async def extract(
        self,
        file_bytes: bytes,
        content_type: ContentType,
        filename: str = "",
    ) -> ExtractedDocument:
        import tempfile
        import os

        suffix = ".docx" if content_type == ContentType.DOCX else ".doc"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name

        try:
            from unstructured.partition.docx import partition_docx

            elements = partition_docx(filename=tmp_path)

            extracted_elements = []
            tables_count = 0

            for el in elements:
                el_type = type(el).__name__.lower()
                if "table" in el_type:
                    tables_count += 1
                    element_type = "table"
                elif "title" in el_type or "header" in el_type:
                    element_type = "header"
                else:
                    element_type = "paragraph"

                extracted_elements.append(
                    ExtractedElement(content=str(el), element_type=element_type)
                )

            full_text = "\n\n".join(str(el) for el in elements if str(el).strip())

            return ExtractedDocument(
                text=full_text,
                elements=extracted_elements,
                title=filename,
                content_type=content_type,
                table_count=tables_count,
                char_count=len(full_text),
                metadata={"filename": filename, "parser": "unstructured_docx"},
            )
        finally:
            os.unlink(tmp_path)

    async def extract_batch(
        self,
        files: list[tuple[bytes, ContentType, str]],
    ) -> list[ExtractedDocument]:
        return [await self.extract(fb, ct, fn) for fb, ct, fn in files]


class CSVExcelParser:
    """Extract tabular data from CSV/Excel files."""

    def supported_types(self) -> list[ContentType]:
        return [ContentType.CSV, ContentType.XLSX]

    async def extract(
        self,
        file_bytes: bytes,
        content_type: ContentType,
        filename: str = "",
    ) -> ExtractedDocument:
        import tempfile
        import os

        suffix = ".csv" if content_type == ContentType.CSV else ".xlsx"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name

        try:
            if content_type == ContentType.CSV:
                from unstructured.partition.csv import partition_csv
                elements = partition_csv(filename=tmp_path)
            else:
                from unstructured.partition.xlsx import partition_xlsx
                elements = partition_xlsx(filename=tmp_path)

            extracted_elements = [
                ExtractedElement(content=str(el), element_type="table")
                for el in elements
                if str(el).strip()
            ]

            full_text = "\n\n".join(str(el) for el in elements if str(el).strip())

            return ExtractedDocument(
                text=full_text,
                elements=extracted_elements,
                title=filename,
                content_type=content_type,
                table_count=len(extracted_elements),
                char_count=len(full_text),
                metadata={"filename": filename, "parser": "unstructured_tabular"},
            )
        finally:
            os.unlink(tmp_path)

    async def extract_batch(
        self,
        files: list[tuple[bytes, ContentType, str]],
    ) -> list[ExtractedDocument]:
        return [await self.extract(fb, ct, fn) for fb, ct, fn in files]
