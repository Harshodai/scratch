"""
Single Source of Truth for PII detection patterns.

SHARED between:
  - centrag/guardrails/ (RAG pipeline PII redaction)
  - mcp_enterprise_server/guardrails.py (MCP tool output PII redaction)

DO NOT duplicate these patterns. Import from here.

Design: SINGLE SOURCE OF TRUTH — eliminates drift between RAG and MCP PII handling.
"""
from __future__ import annotations

import re
from typing import ClassVar


# All PII patterns — used by both RAG and MCP guardrails
PII_PATTERNS: dict[str, re.Pattern] = {
    # ── Identity ────────────────────────────────────────────────────
    "ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "email": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"),
    "phone_us": re.compile(r"\b(?:\+1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"),

    # Phase 2: Passport numbers (US: 9 digits, UK: 9 alphanum, EU: 2-letter + 7 digits)
    "passport": re.compile(r"\b(?:[A-Z]{1,2}\d{6,9}|\d{9})\b"),

    # Phase 2: Date of birth (MM/DD/YYYY, DD/MM/YYYY, YYYY-MM-DD)
    "date_of_birth": re.compile(
        r"\b(?:DOB|Date of Birth|Born)[:\s]+\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}\b",
        re.IGNORECASE,
    ),

    # Phase 2: Driver's license (US state: 1 letter + 6-14 digits, varies by state)
    "drivers_license": re.compile(
        r"\b(?:DL|Driver'?s?\s*(?:License|Licence))[:\s#]+[A-Z]?\d{6,14}\b",
        re.IGNORECASE,
    ),

    # Phase 2: Medical Record Number (MRN: typically 6-10 digits with prefix)
    "medical_record": re.compile(
        r"\b(?:MRN|Medical Record)[:\s#]+\d{6,10}\b",
        re.IGNORECASE,
    ),

    # ── Financial ───────────────────────────────────────────────────
    "credit_card": re.compile(r"\b(?:\d{4}[-\s]?){3}\d{4}\b"),

    # Phase 2: IBAN (2-letter country + 2 check digits + up to 30 alphanum)
    "iban": re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{4}\d{7}(?:[A-Z0-9]?){0,16}\b"),

    # ── Network / Infrastructure ────────────────────────────────────
    "ip_address": re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),

    # ── Cloud credentials (dangerous if leaked in LLM output) ──────
    "aws_access_key": re.compile(r"\b(?:AKIA|ABIA|ACCA|ASIA)[A-Z0-9]{16}\b"),
    "aws_secret_key": re.compile(r"(?i)aws_secret_access_key\s*=\s*\S{40}"),

    # Phase 2: AWS ARN (can leak account IDs and resource paths)
    "aws_arn": re.compile(r"\barn:aws:[a-z0-9\-]+:[a-z0-9\-]*:\d{12}:[^\s]+\b"),

    # ── Generic API keys ───────────────────────────────────────────
    "api_key_generic": re.compile(r"\b(?:api[_-]?key|token|secret)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{32,}['\"]?", re.IGNORECASE),
}


def redact_pii(text: str, patterns: dict[str, re.Pattern] | None = None) -> str:
    """
    Redact PII from text using the shared pattern set.

    Args:
        text:     Text to redact.
        patterns: Override patterns (default: PII_PATTERNS).

    Returns:
        Text with PII replaced by [REDACTED_{TYPE}] tokens.
    """
    active_patterns = patterns or PII_PATTERNS
    for pii_type, pattern in active_patterns.items():
        text = pattern.sub(f"[REDACTED_{pii_type.upper()}]", text)
    return text


def detect_pii(text: str, patterns: dict[str, re.Pattern] | None = None) -> list[str]:
    """
    Detect PII types present in text WITHOUT redacting.

    Used by input rails to FLAG PII in queries (warn, not block).

    Returns:
        List of PII type names found (e.g., ["email", "ssn"]).
    """
    active_patterns = patterns or PII_PATTERNS
    found: list[str] = []
    for pii_type, pattern in active_patterns.items():
        if pattern.search(text):
            found.append(pii_type)
    return found
