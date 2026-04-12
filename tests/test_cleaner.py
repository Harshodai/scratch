"""
Tests for DocumentCleaner — SHARED text cleaning pipeline.

Verifies:
    - Unicode normalization (smart quotes, BOM, zero-width chars)
    - Whitespace normalization (collapse, strip)
    - Header/footer stripping (page numbers, artifacts)
    - PII redaction (SSN, email, credit card)
    - URL normalization
    - Audit trail (CleaningResult metadata)
    - Pipeline stage toggling via config
"""

from __future__ import annotations

from centrag.ingestion.cleaner import (
    DocumentCleaner,
    DocumentCleanerConfig,
)

# ── Unicode Normalization ───────────────────────────────────────────


class TestUnicodeNormalization:
    """Stage 1: Unicode normalization."""

    def test_smart_quotes_normalized(self):
        cleaner = DocumentCleaner()
        result = cleaner.clean("\u201cHello\u201d \u2018world\u2019")
        assert "\"Hello\" 'world'" in result.cleaned_text

    def test_em_dash_normalized(self):
        cleaner = DocumentCleaner()
        result = cleaner.clean("risk \u2014 very high")
        assert "risk - very high" in result.cleaned_text

    def test_ellipsis_normalized(self):
        cleaner = DocumentCleaner()
        result = cleaner.clean("loading\u2026")
        assert "loading..." in result.cleaned_text

    def test_non_breaking_space(self):
        cleaner = DocumentCleaner()
        result = cleaner.clean("hello\u00a0world")
        assert "hello world" in result.cleaned_text

    def test_zero_width_space_removed(self):
        cleaner = DocumentCleaner()
        result = cleaner.clean("he\u200bllo")
        assert "hello" in result.cleaned_text

    def test_bom_removed(self):
        cleaner = DocumentCleaner()
        result = cleaner.clean("\ufeffHello")
        assert result.cleaned_text.startswith("Hello")


# ── Whitespace Normalization ────────────────────────────────────────


class TestWhitespaceNormalization:
    """Stage 2: Whitespace normalization."""

    def test_collapse_multiple_spaces(self):
        cleaner = DocumentCleaner()
        result = cleaner.clean("hello    world")
        assert "hello world" in result.cleaned_text

    def test_collapse_excessive_newlines(self):
        cleaner = DocumentCleaner()
        result = cleaner.clean("para1\n\n\n\n\npara2")
        # Max 3 consecutive newlines → 2 empty lines between content
        assert "\n\n\n\n" not in result.cleaned_text
        assert "para1" in result.cleaned_text
        assert "para2" in result.cleaned_text

    def test_strip_trailing_whitespace(self):
        cleaner = DocumentCleaner()
        result = cleaner.clean("hello   \nworld   ")
        lines = result.cleaned_text.split("\n")
        for line in lines:
            assert line == line.rstrip()


# ── Header/Footer Stripping ────────────────────────────────────────


class TestHeaderFooterStripping:
    """Stage 3: Remove PDF artifacts."""

    def test_page_numbers_removed(self):
        cleaner = DocumentCleaner()
        text = "Introduction\nThis is content.\nPage 1 of 10\nMore content."
        result = cleaner.clean(text)
        assert "Page 1 of 10" not in result.cleaned_text
        assert "Introduction" in result.cleaned_text
        assert "More content" in result.cleaned_text

    def test_standalone_numbers_removed(self):
        cleaner = DocumentCleaner()
        text = "Some content here.\n42\nMore content."
        result = cleaner.clean(text)
        # Standalone "42" stripped (looks like a page number)
        lines = [l.strip() for l in result.cleaned_text.split("\n") if l.strip()]
        assert "42" not in lines

    def test_page_x_pattern_removed(self):
        cleaner = DocumentCleaner()
        text = "Content.\n  Page 5  \nMore."
        result = cleaner.clean(text)
        assert "Page 5" not in result.cleaned_text

    def test_real_content_preserved(self):
        cleaner = DocumentCleaner()
        text = "The revenue was $42 million.\nThis is important."
        result = cleaner.clean(text)
        assert "$42 million" in result.cleaned_text


# ── PII Redaction ───────────────────────────────────────────────────


class TestPIIRedaction:
    """Stage 4: PII detection and redaction."""

    def test_ssn_redacted(self):
        cleaner = DocumentCleaner()
        result = cleaner.clean("Employee SSN: 123-45-6789")
        assert "123-45-6789" not in result.cleaned_text
        assert "[REDACTED_SSN]" in result.cleaned_text

    def test_email_redacted(self):
        cleaner = DocumentCleaner()
        result = cleaner.clean("Contact: john.doe@company.com")
        assert "john.doe@company.com" not in result.cleaned_text
        assert "[REDACTED_EMAIL]" in result.cleaned_text

    def test_credit_card_redacted(self):
        cleaner = DocumentCleaner()
        result = cleaner.clean("Card: 4111-1111-1111-1111")
        assert "4111-1111-1111-1111" not in result.cleaned_text
        assert "[REDACTED_CREDIT_CARD]" in result.cleaned_text

    def test_multiple_pii_types(self):
        cleaner = DocumentCleaner()
        text = "SSN: 123-45-6789, Email: test@test.com"
        result = cleaner.clean(text)
        assert "ssn" in result.pii_types_found
        assert "email" in result.pii_types_found
        assert result.pii_redaction_count >= 2

    def test_no_pii_unchanged(self):
        cleaner = DocumentCleaner()
        result = cleaner.clean("This is clean text with no sensitive data.")
        assert result.pii_types_found == []
        assert result.pii_redaction_count == 0

    def test_pii_disabled(self):
        config = DocumentCleanerConfig(redact_pii=False)
        cleaner = DocumentCleaner(config)
        result = cleaner.clean("SSN: 123-45-6789")
        assert "123-45-6789" in result.cleaned_text
        assert "pii_redaction" not in result.stages_applied


# ── Audit Trail ─────────────────────────────────────────────────────


class TestAuditTrail:
    """CleaningResult records what happened during cleaning."""

    def test_stages_recorded(self):
        cleaner = DocumentCleaner()
        result = cleaner.clean("Some text")
        assert "unicode_normalization" in result.stages_applied
        assert "whitespace_normalization" in result.stages_applied
        assert "header_footer_strip" in result.stages_applied
        assert "pii_redaction" in result.stages_applied

    def test_original_and_cleaned_length(self):
        cleaner = DocumentCleaner()
        text = "Hello   world   " + "  \n" * 10
        result = cleaner.clean(text)
        assert result.original_length == len(text)
        assert result.cleaned_length <= result.original_length

    def test_all_stages_disabled(self):
        config = DocumentCleanerConfig(
            normalize_unicode=False,
            normalize_whitespace=False,
            strip_headers_footers=False,
            redact_pii=False,
            normalize_urls=False,
        )
        cleaner = DocumentCleaner(config)
        result = cleaner.clean("hello")
        assert result.stages_applied == []


# ── Config Toggles ──────────────────────────────────────────────────


class TestConfigToggles:
    """DocumentCleanerConfig stage toggles."""

    def test_url_normalization_enabled(self):
        config = DocumentCleanerConfig(normalize_urls=True)
        cleaner = DocumentCleaner(config)
        result = cleaner.clean("Visit https://example.com?utm_source=test&ref=123")
        assert "url_normalization" in result.stages_applied

    def test_custom_max_newlines(self):
        config = DocumentCleanerConfig(max_consecutive_newlines=2)
        cleaner = DocumentCleaner(config)
        result = cleaner.clean("A\n\n\nB")
        # With max=2, should have at most 1 empty line (2 newlines, but inner collapse)
        assert "\n\n\n" not in result.cleaned_text


# ── Integration: Full Pipeline ──────────────────────────────────────


class TestFullPipeline:
    """End-to-end cleaning with mixed content."""

    def test_mixed_content(self):
        text = (
            "\ufeff"  # BOM
            "\u201cAnnual Report\u201d\n"  # Smart quotes
            "Page 1 of 50\n"  # Page number
            "\n\n\n\n\n"  # Excessive newlines
            "Employee SSN: 123-45-6789\n"  # PII
            "Revenue was $42M in Q4.\n"
            "Contact: cfo@company.com\n"  # PII
            "\n42\n"  # Standalone number
            "End of report."
        )

        cleaner = DocumentCleaner()
        result = cleaner.clean(text, filename="annual_report.pdf")

        # BOM removed
        assert "\ufeff" not in result.cleaned_text
        # Smart quotes normalized
        assert '"Annual Report"' in result.cleaned_text
        # Page number stripped
        assert "Page 1 of 50" not in result.cleaned_text
        # SSN redacted
        assert "123-45-6789" not in result.cleaned_text
        assert "[REDACTED_SSN]" in result.cleaned_text
        # Email redacted
        assert "cfo@company.com" not in result.cleaned_text
        # Real content preserved
        assert "$42M" in result.cleaned_text
        assert "End of report" in result.cleaned_text
        # Audit trail
        assert "ssn" in result.pii_types_found
        assert "email" in result.pii_types_found
        assert result.pii_redaction_count >= 2
        assert len(result.stages_applied) >= 4
