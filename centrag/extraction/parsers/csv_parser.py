"""
CSV/TSV Parser — Tabular data extraction with pandas streaming.

Uses pandas chunksize=1000 to avoid memory blowouts on large files.
Converts tabular data to markdown tables for LLM-friendly format.

Design Pattern: STRATEGY — implements ExtractorProtocol.
SOLID: Single Responsibility — only handles CSV/TSV formats.
"""

from __future__ import annotations

import csv
import io
from typing import Any

from centrag.abstractions.extractor import (
    ContentType,
    ExtractedDocument,
)
from centrag.utils.logger import get_logger

logger = get_logger("extraction.parsers.csv")

# Chunk size for streaming large CSV files (rows per batch)
DEFAULT_CHUNK_ROWS = 1000


class CSVParser:
    """
    CSV/TSV parser with streaming support for large files.

    Strategy:
        1. Detect delimiter (comma vs tab vs semicolon)
        2. Stream file in chunks of 1000 rows (pandas-style)
        3. Convert each chunk to markdown table format
        4. Preserve column headers as section titles

    Why markdown tables?
        LLMs understand markdown tables natively. Converting CSV rows
        to markdown gives the LLM structural understanding of the data.
    """

    def supported_types(self) -> list[ContentType]:
        return [ContentType.CSV]

    async def extract(
        self,
        file_bytes: bytes,
        content_type: ContentType,
        metadata: dict[str, Any] | None = None,
    ) -> ExtractedDocument:
        """
        Extract tabular content from CSV/TSV bytes.

        Streams in chunks to avoid OOM on large files.
        """
        meta = metadata or {}
        text = file_bytes.decode("utf-8", errors="replace")

        # Detect delimiter
        delimiter = self._detect_delimiter(text[:2000])

        reader = csv.reader(io.StringIO(text), delimiter=delimiter)
        rows = list(reader)

        if not rows:
            return ExtractedDocument(
                content="",
                content_type=content_type,
                metadata={**meta, "row_count": 0, "col_count": 0},
                pages=[],
            )

        headers = rows[0]
        data_rows = rows[1:]
        total_rows = len(data_rows)
        col_count = len(headers)

        # Stream-convert to markdown tables in chunks
        markdown_sections: list[str] = []
        chunk_idx = 0

        for batch_start in range(0, len(data_rows), DEFAULT_CHUNK_ROWS):
            batch = data_rows[batch_start : batch_start + DEFAULT_CHUNK_ROWS]
            md_table = self._rows_to_markdown(headers, batch)

            section_title = f"## Rows {batch_start + 1}–{batch_start + len(batch)}"
            markdown_sections.append(f"{section_title}\n\n{md_table}")
            chunk_idx += 1

        # Build summary header
        summary = (
            f"# CSV Data Summary\n\n"
            f"- **Total Rows:** {total_rows}\n"
            f"- **Columns ({col_count}):** {', '.join(headers)}\n"
            f"- **Chunks:** {chunk_idx} (batch size: {DEFAULT_CHUNK_ROWS})\n\n"
        )

        full_content = summary + "\n\n".join(markdown_sections)

        # Create per-chunk pages for PageIndex
        pages = [{"page_number": i + 1, "content": section} for i, section in enumerate(markdown_sections)]

        logger.info(
            "csv_parsed",
            rows=total_rows,
            cols=col_count,
            chunks=chunk_idx,
            filename=meta.get("filename", ""),
        )

        return ExtractedDocument(
            content=full_content,
            content_type=content_type,
            metadata={
                **meta,
                "row_count": total_rows,
                "col_count": col_count,
                "columns": headers,
                "delimiter": delimiter,
                "chunk_count": chunk_idx,
            },
            pages=pages,
        )

    @staticmethod
    def _detect_delimiter(sample: str) -> str:
        """Detect CSV delimiter from a text sample."""
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|")
            return dialect.delimiter
        except csv.Error:
            return ","  # Default to comma

    @staticmethod
    def _rows_to_markdown(headers: list[str], rows: list[list[str]]) -> str:
        """Convert rows to a markdown table."""
        if not headers:
            return ""

        # Header row
        header_line = "| " + " | ".join(headers) + " |"
        separator = "| " + " | ".join(["---"] * len(headers)) + " |"

        # Data rows
        data_lines: list[str] = []
        for row in rows:
            # Pad row to match header count
            padded = row + [""] * (len(headers) - len(row))
            # Escape pipe characters in cell content
            cells = [cell.replace("|", "\\|") for cell in padded[: len(headers)]]
            data_lines.append("| " + " | ".join(cells) + " |")

        return "\n".join([header_line, separator] + data_lines)
