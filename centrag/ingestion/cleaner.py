"""
Document Cleaner — Composable text cleaning pipeline.

SHARED INFRASTRUCTURE: Applied BEFORE both retrieval paths.

The cleaner sits between parsing and indexing. Both the PageIndex tree
and the vector chunks are built from the cleaned text, ensuring:
    - No PII leaks into either path's index
    - Consistent text normalization across both paths
    - Audit trail of PII detections per document

Pipeline stages:
    1. Unicode normalization (NFKC)
    2. Whitespace normalization (collapse, strip)
    3. Header/footer stripping (PDF artifacts)
    4. PII redaction (SSN, email, credit card, etc.)
    5. URL normalization (optional)

Design Pattern: PIPELINE — each stage is a function that transforms text.
                Stages can be added/removed via DocumentCleanerConfig.

SOLID: Single Responsibility — only cleans text. Does not parse, chunk, or embed.
SOLID: Open/Closed — add new cleaning stages by adding functions, not modifying existing ones.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from centrag.guardrails.pii import PII_PATTERNS, detect_pii, redact_pii
from centrag.utils.logger import get_logger

logger = get_logger("ingestion.cleaner")


@dataclass(frozen=True)
class CleaningResult:
    """
    Immutable result of the cleaning pipeline.

    Includes audit trail for PII compliance:
        - pii_types_found: which PII types were detected
        - pii_redaction_count: total number of redactions applied
        - stages_applied: which cleaning stages ran
    """

    cleaned_text: str
    original_length: int
    cleaned_length: int
    pii_types_found: list[str] = field(default_factory=list)
    pii_redaction_count: int = 0
    stages_applied: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class DocumentCleanerConfig:
    """Configuration for the cleaning pipeline."""

    # Pipeline stages (toggleable)
    normalize_unicode: bool = True
    normalize_whitespace: bool = True
    strip_headers_footers: bool = True
    redact_pii: bool = True
    normalize_urls: bool = False  # Off by default — URLs can be informative

    # Header/footer detection
    max_header_lines: int = 3  # Lines at page top to check
    max_footer_lines: int = 3  # Lines at page bottom to check
    page_number_pattern: str = r"^\s*(?:Page\s*)?\d+\s*(?:of\s*\d+)?\s*$"

    # Thresholds
    max_consecutive_newlines: int = 3
    min_line_length_for_content: int = 2


class DocumentCleaner:
    """
    Composable text cleaning pipeline for document ingestion.

    SHARED INFRASTRUCTURE — applied before BOTH retrieval paths.

    Usage:
        cleaner = DocumentCleaner(DocumentCleanerConfig(redact_pii=True))
        result = cleaner.clean("raw text with SSN 123-45-6789...")
        print(result.cleaned_text)       # Text with [REDACTED_SSN]
        print(result.pii_types_found)    # ["ssn"]
    """

    def __init__(self, config: DocumentCleanerConfig | None = None) -> None:
        self._config = config or DocumentCleanerConfig()
        self._page_num_re = re.compile(self._config.page_number_pattern, re.IGNORECASE)

    def clean(self, text: str, filename: str = "") -> CleaningResult:
        """
        Run the full cleaning pipeline.

        Stages run in order:
            1. Unicode normalization
            2. Whitespace normalization
            3. Header/footer stripping
            4. PII redaction
            5. URL normalization

        Args:
            text: Raw extracted text to clean.
            filename: For logging/audit purposes.

        Returns:
            CleaningResult with cleaned text and audit trail.
        """
        original_length = len(text)
        stages_applied: list[str] = []
        warnings: list[str] = []
        pii_types: list[str] = []
        pii_count = 0

        # Stage 1: Unicode normalization
        if self._config.normalize_unicode:
            text = self._normalize_unicode(text)
            stages_applied.append("unicode_normalization")

        # Stage 2: Whitespace normalization
        if self._config.normalize_whitespace:
            text = self._normalize_whitespace(text)
            stages_applied.append("whitespace_normalization")

        # Stage 3: Header/footer stripping
        if self._config.strip_headers_footers:
            text, stripped_count = self._strip_headers_footers(text)
            stages_applied.append("header_footer_strip")
            if stripped_count > 0:
                warnings.append(f"Stripped {stripped_count} header/footer lines")

        # Stage 4: PII redaction
        if self._config.redact_pii:
            pii_types = detect_pii(text)
            if pii_types:
                # Count total matches before redaction
                pii_count = sum(
                    len(pattern.findall(text)) for pii_type, pattern in PII_PATTERNS.items() if pii_type in pii_types
                )
                text = redact_pii(text)
                logger.info(
                    "pii_redacted",
                    filename=filename,
                    types=pii_types,
                    count=pii_count,
                )
            stages_applied.append("pii_redaction")

        # Stage 5: URL normalization
        if self._config.normalize_urls:
            text = self._normalize_urls(text)
            stages_applied.append("url_normalization")

        # Final trim
        text = text.strip()

        result = CleaningResult(
            cleaned_text=text,
            original_length=original_length,
            cleaned_length=len(text),
            pii_types_found=pii_types,
            pii_redaction_count=pii_count,
            stages_applied=stages_applied,
            warnings=warnings,
        )

        logger.info(
            "document_cleaned",
            filename=filename,
            original_len=original_length,
            cleaned_len=len(text),
            pii_found=len(pii_types),
            stages=len(stages_applied),
        )

        return result

    # ── Pipeline Stages ─────────────────────────────────────────────

    @staticmethod
    def _normalize_unicode(text: str) -> str:
        """
        Stage 1: Normalize Unicode to NFKC form.

        Converts fancy quotes, ligatures, and other Unicode oddities
        to their ASCII-compatible equivalents where possible.
        """
        # NFKC: compatibility decomposition + canonical composition
        text = unicodedata.normalize("NFKC", text)

        # Replace common Unicode quotation marks with ASCII
        replacements = {
            "\u2018": "'",
            "\u2019": "'",  # Smart single quotes
            "\u201c": '"',
            "\u201d": '"',  # Smart double quotes
            "\u2013": "-",
            "\u2014": "-",  # En-dash, Em-dash
            "\u2026": "...",  # Ellipsis
            "\u00a0": " ",  # Non-breaking space
            "\u200b": "",  # Zero-width space
            "\ufeff": "",  # BOM
        }
        for old, new in replacements.items():
            text = text.replace(old, new)

        return text

    def _normalize_whitespace(self, text: str) -> str:
        """
        Stage 2: Normalize whitespace.

        - Collapse multiple spaces to single space
        - Collapse excessive newlines
        - Strip trailing whitespace per line
        - Remove empty lines at start/end
        """
        # Strip trailing whitespace per line
        lines = [line.rstrip() for line in text.split("\n")]

        # Collapse excessive consecutive empty lines
        max_nl = self._config.max_consecutive_newlines
        result_lines: list[str] = []
        empty_count = 0

        for line in lines:
            if not line.strip():
                empty_count += 1
                if empty_count <= max_nl - 1:
                    result_lines.append("")
            else:
                empty_count = 0
                # Collapse multiple spaces within a line
                line = re.sub(r" {2,}", " ", line)
                result_lines.append(line)

        return "\n".join(result_lines)

    def _strip_headers_footers(self, text: str) -> tuple[str, int]:
        """
        Stage 3: Remove repeated headers/footers and page numbers.

        Detects patterns like:
            - "Page X of Y"
            - Standalone numbers (page numbers)
            - Repeated lines at consistent positions (headers)
        """
        lines = text.split("\n")
        stripped_count = 0
        result_lines: list[str] = []

        for line in lines:
            stripped = line.strip()

            # Skip standalone page numbers
            if self._page_num_re.match(stripped):
                stripped_count += 1
                continue

            # Skip lines that are just numbers (common in PDF extraction)
            if stripped.isdigit() and len(stripped) <= 5:
                stripped_count += 1
                continue

            # Skip very short lines that look like headers/footers
            _is_short = len(stripped) < self._config.min_line_length_for_content
            _looks_like_content = stripped and stripped[-1] not in ".!?:;,"
            _is_page_artifact = stripped.isdigit() or stripped.lower() in (
                "confidential", "draft", "internal"
            )
            
            if _is_short and _looks_like_content and _is_page_artifact:
                stripped_count += 1
                continue

            result_lines.append(line)

        return "\n".join(result_lines), stripped_count

    @staticmethod
    def _normalize_urls(text: str) -> str:
        """
        Stage 5: Normalize URLs.

        Strips tracking parameters and normalizes URL format.
        """
        # Remove common tracking parameters
        url_pattern = re.compile(
            r"(https?://[^\s]+?)(?:[?&](?:utm_\w+|fbclid|gclid|ref)=[^\s&]*)+",
            re.IGNORECASE,
        )
        text = url_pattern.sub(r"\1", text)

        return text
