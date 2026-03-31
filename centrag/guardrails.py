"""
Guardrails for the CentRAG Retrieval Layer
==========================================

These guardrails protect the RAG pipeline at the APPLICATION level.
They are separate from the MCP server guardrails (which protect data source access).

Inspired by: https://thenewstack.io/ai-demo-to-production/
"Production systems should never return raw LLM output directly to users."

Seven layers of protection:
1. Input Validation    — schema + content checks on incoming queries
2. Response Validation — structured output parsing, schema enforcement
3. Policy Checks       — namespace access, blocked topics, compliance rules
4. PII Redaction       — scrub sensitive data from LLM output (reuses MCP guardrails)
5. Cost Tracking       — per-team token budgets + alerts
6. Response Capping    — max response length, max sources
7. Audit Trail         — structured log of every retrieval with cost + latency
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Protocol

import structlog

logger = structlog.get_logger("guardrails.retrieval")


# =============================================================================
# 1. Input Validation — Reject bad queries before they hit the pipeline
# =============================================================================

class InputValidationError(Exception):
    """Raised when a query fails input validation."""
    pass


@dataclass(frozen=True)
class InputValidationConfig:
    """Policy-as-code: configurable validation rules."""
    max_query_length: int = 2000
    min_query_length: int = 3
    blocked_patterns: list[str] = field(default_factory=lambda: [
        r"ignore\s+(?:previous|all|above)\s+instructions",  # prompt injection
        r"system\s*prompt",                                   # prompt extraction
        r"you\s+are\s+now",                                   # role hijacking
        r"reveal\s+(?:your|the)\s+(?:system|initial)",        # prompt leak attempts
        r"<\s*script",                                        # XSS
    ])
    # Namespaces each team is ALLOWED to access (empty = all)
    allowed_namespaces: list[str] = field(default_factory=list)


def validate_query(
    query: str,
    team_id: str,
    namespace: str,
    config: InputValidationConfig | None = None,
) -> str:
    """
    Validate and sanitize a retrieval query.

    Checks:
    - Length bounds
    - Prompt injection patterns
    - Namespace access control (policy check)

    Returns cleaned query. Raises InputValidationError on violation.
    """
    config = config or InputValidationConfig()

    # Length checks
    stripped = query.strip()
    if len(stripped) < config.min_query_length:
        raise InputValidationError(
            f"Query too short (minimum {config.min_query_length} characters)."
        )
    if len(stripped) > config.max_query_length:
        raise InputValidationError(
            f"Query too long (maximum {config.max_query_length} characters). "
            f"Got {len(stripped)} characters."
        )

    # Prompt injection detection
    for pattern_str in config.blocked_patterns:
        pattern = re.compile(pattern_str, re.IGNORECASE)
        if pattern.search(stripped):
            logger.warning(
                "prompt_injection_blocked",
                team_id=team_id,
                pattern=pattern_str,
                query_preview=stripped[:50],
            )
            raise InputValidationError(
                "Query contains blocked content. This attempt has been logged."
            )

    # Namespace policy check
    if config.allowed_namespaces and namespace not in config.allowed_namespaces:
        raise InputValidationError(
            f"Namespace '{namespace}' is not in your allowed namespaces. "
            f"Contact your platform admin to request access."
        )

    return stripped


# =============================================================================
# 2. Response Validation — Never return raw LLM output
# =============================================================================

class ResponseValidationError(Exception):
    """Raised when LLM output fails validation."""
    pass


@dataclass(frozen=True)
class ResponseValidationConfig:
    """Policy-as-code for output validation."""
    max_response_length: int = 10_000      # characters
    max_sources: int = 20
    require_sources: bool = True           # must have ≥1 source citation
    min_confidence_threshold: float = 0.3  # below this = "I don't know"
    blocked_output_patterns: list[str] = field(default_factory=lambda: [
        r"as\s+an\s+ai\s+(?:language\s+)?model",  # LLM self-reference leak
        r"I\s+(?:cannot|can't)\s+access",           # capability confession
    ])


def validate_response(
    answer: str,
    sources: list[Any],
    avg_confidence: float,
    config: ResponseValidationConfig | None = None,
) -> str:
    """
    Validate LLM output against policy rules.

    Checks:
    - Response length
    - Source citation requirement
    - Confidence threshold → honest "I don't know"
    - Blocked output patterns (LLM leaks)

    Returns cleaned answer. Raises ResponseValidationError on critical failure.
    """
    config = config or ResponseValidationConfig()

    # Truncate overlong responses
    if len(answer) > config.max_response_length:
        answer = answer[:config.max_response_length] + "\n\n[Response truncated]"

    # Require source citations
    if config.require_sources and not sources:
        logger.warning("response_no_sources", answer_preview=answer[:100])
        answer = (
            "I could not find relevant sources to answer this question confidently. "
            "Try rephrasing your query or uploading additional documents."
        )

    # Confidence gate → honest uncertainty
    if avg_confidence < config.min_confidence_threshold:
        answer = (
            f"⚠️ Low confidence ({avg_confidence:.0%}): {answer}\n\n"
            "The retrieved documents may not be highly relevant to your question. "
            "Consider refining your query or checking a different namespace."
        )

    # Block LLM self-reference leaks
    for pattern_str in config.blocked_output_patterns:
        pattern = re.compile(pattern_str, re.IGNORECASE)
        answer = pattern.sub("[REDACTED]", answer)

    return answer


# =============================================================================
# 3. PII Redaction — Reuse patterns from MCP guardrails + extend
# =============================================================================

_PII_PATTERNS: dict[str, re.Pattern] = {
    "ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "credit_card": re.compile(r"\b(?:\d{4}[-\s]?){3}\d{4}\b"),
    "email": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"),
    "phone_us": re.compile(r"\b(?:\+1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"),
    "ip_address": re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    "aws_access_key": re.compile(r"\b(?:AKIA|ABIA|ACCA|ASIA)[A-Z0-9]{16}\b"),
    "aws_secret_key": re.compile(r"(?i)aws_secret_access_key\s*=\s*\S{40}"),
}


def redact_pii(text: str, enable: bool = True) -> str:
    """
    Redact PII from LLM output before returning to user.

    Extended from MCP guardrails with:
    - IP addresses
    - AWS access keys
    - AWS secret keys
    """
    if not enable:
        return text
    for pii_type, pattern in _PII_PATTERNS.items():
        text = pattern.sub(f"[REDACTED_{pii_type.upper()}]", text)
    return text


# =============================================================================
# 4. Cost Tracking & Budget Enforcement
# =============================================================================

@dataclass
class TokenUsage:
    """Tracks token usage for a single request."""
    embedding_tokens: int = 0
    generation_input_tokens: int = 0
    generation_output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.embedding_tokens + self.generation_input_tokens + self.generation_output_tokens

    @property
    def estimated_cost_usd(self) -> float:
        """
        Estimated cost using Bedrock pricing (approximate):
        - Titan Embed v2: $0.0001 / 1K tokens
        - Claude 3.5 Sonnet input: $0.003 / 1K tokens
        - Claude 3.5 Sonnet output: $0.015 / 1K tokens
        """
        embed_cost = (self.embedding_tokens / 1000) * 0.0001
        input_cost = (self.generation_input_tokens / 1000) * 0.003
        output_cost = (self.generation_output_tokens / 1000) * 0.015
        return embed_cost + input_cost + output_cost


class BudgetExceededError(Exception):
    """Raised when a team exceeds their token budget."""
    pass


class CostTrackerProtocol(Protocol):
    """
    Protocol for cost tracking backends.

    Implementations:
    - RedisBackedCostTracker (production)
    - InMemoryCostTracker (testing)
    """

    async def get_usage(self, team_id: str, period: str = "daily") -> TokenUsage:
        """Get current period usage for a team."""
        ...

    async def record_usage(self, team_id: str, usage: TokenUsage) -> None:
        """Record usage for a request."""
        ...

    async def check_budget(self, team_id: str, tier: str = "pro") -> bool:
        """Returns True if team is within budget, False if over."""
        ...


# Budget limits per tier (tokens per day)
BUDGET_LIMITS: dict[str, int] = {
    "free": 50_000,       # ~$0.15/day
    "pro": 500_000,       # ~$1.50/day
    "enterprise": 5_000_000,  # ~$15/day
}


# =============================================================================
# 5. Audit Trail — Structured logging for every retrieval
# =============================================================================

def audit_retrieval(
    team_id: str,
    request_id: str,
    query: str,
    namespace: str,
    cache_hit: bool,
    source_count: int,
    token_usage: TokenUsage | None = None,
    latency_ms: float = 0.0,
    success: bool = True,
    error: str | None = None,
) -> None:
    """
    Emit a structured audit log for every retrieval request.

    In production, these are shipped to:
    - CloudWatch Logs (real-time)
    - S3 (immutable archive)
    - Langfuse (LLM-specific traces)
    """
    log_data: dict[str, Any] = {
        "event": "retrieval_request",
        "team_id": team_id,
        "request_id": request_id,
        "query_preview": query[:100],
        "namespace": namespace,
        "cache_hit": cache_hit,
        "source_count": source_count,
        "latency_ms": round(latency_ms, 2),
        "success": success,
    }

    if token_usage:
        log_data["tokens_total"] = token_usage.total_tokens
        log_data["cost_usd"] = round(token_usage.estimated_cost_usd, 6)

    if error:
        log_data["error"] = error

    if success:
        logger.info("retrieval_complete", **log_data)
    else:
        logger.warning("retrieval_failed", **log_data)


# =============================================================================
# 6. Composite Guardrail — Wire everything together
# =============================================================================

@dataclass(frozen=True)
class GuardrailsConfig:
    """Complete guardrails configuration for the retrieval layer."""
    input: InputValidationConfig = field(default_factory=InputValidationConfig)
    output: ResponseValidationConfig = field(default_factory=ResponseValidationConfig)
    enable_pii_redaction: bool = True
    enable_cost_tracking: bool = True
    enable_audit: bool = True
"""
Description: Guardrails layer for CentRAG retrieval pipeline with input validation,
response validation, PII redaction, cost tracking, and audit trail.
"""
