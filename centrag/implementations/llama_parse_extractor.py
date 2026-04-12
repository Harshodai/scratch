"""
LlamaParse Extractor — High-fidelity hierarchical document parsing.

Recommended in the technical documentation for oversized technical documents
where standard parsers (e.g., PyMuPDF) fail to capture nested structures,
tables, and diagrams.
"""

from __future__ import annotations

import asyncio
import os

from centrag.abstractions.extractor import (
    ContentType,
    ExtractedDocument,
    ExtractedElement,
)
from centrag.utils.logger import get_logger

logger = get_logger("implementations.llamaparse")


class LlamaParseExtractor:
    """Enterprise Document Parser powered by Llama Cloud.

    The WHY:
        Standard PDF parsers (like PyMuPDF) extract text but often
        fail to preserve structural relationships. They "break"
        complex tables, lose nested lists, and ignore diagrams.
        LlamaParse uses computer vision and LLM-based reasoning
        to parse documents into clean Markdown, ensuring that
        spatial relationships (like table headers) are preserved
        as semantic ones.

    Design Pattern:
        ADAPTER — Translates the Llama Cloud API and its specific
        `Document` objects into our platform's standard
        `ExtractedDocument` schema.

    Usage:
        extractor = LlamaParseExtractor(api_key="llx-...")
        # Best for: Complex Financial Reports, Tax Forms, Tech Specs
        doc = await extractor.extract(pdf_bytes, ContentType.PDF)
    """

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or os.environ.get("LLAMA_CLOUD_API_KEY")
        self._parser = None

    def _get_parser(self):
        """Lazy load LlamaParse SDK."""
        if self._parser is None:
            if not self._api_key:
                raise ValueError("LLAMA_CLOUD_API_KEY is not set.")

            from llama_parse import LlamaParse

            # As per doc: Use 'markdown' result type for best hierarchical preservation
            self._parser = LlamaParse(
                api_key=self._api_key,
                result_type="markdown",
                verbose=True,
                language="en",
                # Technical docs parameters
                premium=True,
                num_workers=4,
            )
        return self._parser

    def supported_types(self) -> list[ContentType]:
        return [
            ContentType.PDF,
            ContentType.DOCX,
            ContentType.HTML,
            ContentType.MARKDOWN,
        ]

    async def extract(
        self,
        file_bytes: bytes,
        content_type: ContentType,
        filename: str = "",
    ) -> ExtractedDocument:
        """
        Send document to LlamaParse cloud and return structured Markdown.
        """
        if content_type not in self.supported_types():
            raise ValueError(f"Content type {content_type} not supported by LlamaParse.")

        logger.info("llamaparse_extraction_started", filename=filename, size=len(file_bytes))

        parser = self._get_parser()

        # LlamaParse.aload_data is async
        # We need to save to a temp file or use bytes directly if supported
        # For now, we use a temp file for compatibility
        import os
        import tempfile

        with tempfile.NamedTemporaryFile(delete=False, suffix=f"_{filename}") as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name

        try:
            # aload_data returns a list of Document objects
            documents = await parser.aload_data(tmp_path)

            if not documents:
                raise RuntimeError("LlamaParse returned no data.")

            # Combine all documents (usually one per file unless split)
            full_text = "\n\n".join([doc.text for doc in documents])

            # Parse into ExtractedElements (simplified for now: treat as a single markdown element)
            elements = [ExtractedElement(content=full_text, element_type="markdown", metadata={"source": "llamaparse"})]

            return ExtractedDocument(
                text=full_text,
                elements=elements,
                content_type=content_type,
                page_count=len(documents),
                metadata={"filename": filename, "parser": "llamaparse"},
            )

        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    async def extract_batch(
        self,
        files: list[tuple[bytes, ContentType, str]],
    ) -> list[ExtractedDocument]:
        """Parallel extraction using LlamaParse workers."""
        tasks = [self.extract(file_bytes, content_type, filename) for file_bytes, content_type, filename in files]
        return await asyncio.gather(*tasks)
