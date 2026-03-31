"""
Guardrails Layer
================
Defence-in-depth middleware for the MCP server:

1. SQL Injection Prevention — block dangerous keywords, enforce parameterised queries
2. Rate Limiting           — token-bucket per caller + per tool
3. PII Redaction           — strip SSN, credit-card, email patterns from results
4. Result Size Capping     — truncate oversized responses
5. Audit Logging           — structured log every tool invocation with caller identity
6. Permission Enforcement  — read-only vs read-write checks at the tool boundary

Design: Each guardrail is a standalone function so they can be composed
in the tool implementations or layered as middleware.
"""

from __future__ import annotations

import re
import time
import functools
from collections import defaultdict
from typing import Any, Callable

import structlog

from mcp_enterprise_server.config import PermissionLevel

# ---------------------------------------------------------------------------
# Logger
# ---------------------------------------------------------------------------
logger = structlog.get_logger("guardrails")


# ---------------------------------------------------------------------------
# 1. SQL Injection / Dangerous-Keyword Guard
# ---------------------------------------------------------------------------
_DANGEROUS_PATTERNS: list[re.Pattern] = [
    re.compile(r"--"),                              # SQL line comment
    re.compile(r"/\*"),                              # SQL block comment start
    re.compile(r";\s*\w"),                           # chained statements
    re.compile(r"'\s*OR\s+'", re.IGNORECASE),        # classic tautology
    re.compile(r"UNION\s+SELECT", re.IGNORECASE),    # union injection
    re.compile(r"xp_\w+", re.IGNORECASE),            # MSSQL extended stored procs
]


class QueryValidationError(Exception):
    """Raised when a query violates guardrail policies."""
    pass


def validate_sql_query(
    query: str,
    blocked_keywords: list[str],
    permission_level: PermissionLevel,
) -> str:
    """
    Validate an SQL query against guardrail rules.

    Returns the cleaned query string on success.
    Raises QueryValidationError on violation.

    Defence layers:
      - Blocked-keyword check (configurable per-service)
      - Dangerous-pattern regex scan
      - Permission-level enforcement (read-only blocks any mutation)
    """
    upper_query = query.upper().strip()

    # Block dangerous keywords when not in admin mode
    if permission_level != PermissionLevel.ADMIN:
        for keyword in blocked_keywords:
            pattern = re.compile(rf"\b{keyword}\b", re.IGNORECASE)
            if pattern.search(upper_query):
                raise QueryValidationError(
                    f"Blocked keyword '{keyword}' detected. "
                    f"Your permission level ({permission_level.value}) does not allow this operation."
                )

    # Read-only mode: only SELECT and WITH (CTEs) are permitted
    if permission_level == PermissionLevel.READ_ONLY:
        first_keyword = upper_query.lstrip("( ").split()[0] if upper_query.strip() else ""
        if first_keyword not in ("SELECT", "WITH", "EXPLAIN", "DESCRIBE", "SHOW"):
            raise QueryValidationError(
                f"Read-only mode only allows SELECT/WITH/EXPLAIN queries. "
                f"Got: {first_keyword}"
            )

    # Regex-based injection detection
    for pattern in _DANGEROUS_PATTERNS:
        if pattern.search(query):
            raise QueryValidationError(
                f"Potentially dangerous SQL pattern detected: {pattern.pattern}"
            )

    return query.strip()


def validate_schema_access(schema: str, allowed_schemas: list[str]) -> None:
    """Ensure the target schema is in the whitelist."""
    if allowed_schemas and schema.upper() not in [s.upper() for s in allowed_schemas]:
        raise QueryValidationError(
            f"Schema '{schema}' is not in the allowed list: {allowed_schemas}"
        )


def validate_table_access(table: str, allowed_tables: list[str]) -> None:
    """Ensure the target DynamoDB table is in the whitelist."""
    if allowed_tables and table not in allowed_tables:
        raise QueryValidationError(
            f"Table '{table}' is not in the allowed list: {allowed_tables}"
        )


# ---------------------------------------------------------------------------
# 2. Rate Limiting (in-process token bucket)
# ---------------------------------------------------------------------------
class TokenBucketRateLimiter:
    """
    Simple in-process token-bucket rate limiter.

    For production at scale, swap to Redis-backed limits (python-limits + redis)
    or API Gateway throttling.
    """

    def __init__(self, max_tokens: int, refill_rate_per_second: float):
        self._max_tokens = max_tokens
        self._refill_rate = refill_rate_per_second
        self._buckets: dict[str, tuple[float, float]] = {}  # key -> (tokens, last_refill)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        tokens, last_refill = self._buckets.get(key, (float(self._max_tokens), now))

        # Refill tokens
        elapsed = now - last_refill
        tokens = min(self._max_tokens, tokens + elapsed * self._refill_rate)

        if tokens >= 1.0:
            self._buckets[key] = (tokens - 1.0, now)
            return True
        else:
            self._buckets[key] = (tokens, now)
            return False


class RateLimitExceeded(Exception):
    """Raised when a caller exceeds their rate limit."""
    pass


# Global rate limiter instances
_global_limiter = TokenBucketRateLimiter(max_tokens=60, refill_rate_per_second=1.0)
_tool_limiters: dict[str, TokenBucketRateLimiter] = defaultdict(
    lambda: TokenBucketRateLimiter(max_tokens=20, refill_rate_per_second=0.33)
)

# Guardrails config reference (set via init_guardrails)
_guardrails_config = None


def init_guardrails(config) -> None:
    """
    Initialize guardrails with values from GuardrailsConfig.
    Call this at server startup to wire config into the global limiters.
    """
    global _global_limiter, _guardrails_config
    _guardrails_config = config

    # Parse rate limit string like "60/minute" into tokens + refill rate
    try:
        count_str, period = config.global_rate_limit.split("/")
        count = int(count_str)
        period_seconds = {"second": 1, "minute": 60, "hour": 3600}.get(period, 60)
        _global_limiter = TokenBucketRateLimiter(
            max_tokens=count,
            refill_rate_per_second=count / period_seconds,
        )
    except (ValueError, AttributeError):
        pass  # Keep default limiter if parsing fails


def check_rate_limit(caller_id: str, tool_name: str) -> None:
    """
    Check both global and per-tool rate limits.
    Raises RateLimitExceeded if the caller is throttled.
    """
    if not _global_limiter.allow(f"global:{caller_id}"):
        raise RateLimitExceeded(
            f"Global rate limit exceeded for caller '{caller_id}'. "
            "Please wait before making more requests."
        )
    if not _tool_limiters[tool_name].allow(f"tool:{tool_name}:{caller_id}"):
        raise RateLimitExceeded(
            f"Per-tool rate limit exceeded for tool '{tool_name}' by caller '{caller_id}'."
        )


# ---------------------------------------------------------------------------
# 3. PII Redaction
# ---------------------------------------------------------------------------
_PII_PATTERNS: dict[str, re.Pattern] = {
    "ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "credit_card": re.compile(r"\b(?:\d{4}[-\s]?){3}\d{4}\b"),
    "email": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"),
    "phone_us": re.compile(r"\b(?:\+1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"),
}


def redact_pii(text: str, enable: bool = True) -> str:
    """
    Redact common PII patterns from text.
    Returns the redacted text.

    In enterprise settings, consider using a dedicated PII detection
    service (e.g., AWS Comprehend, Presidio) for higher accuracy.
    """
    if not enable:
        return text

    for pii_type, pattern in _PII_PATTERNS.items():
        text = pattern.sub(f"[REDACTED_{pii_type.upper()}]", text)
    return text


# ---------------------------------------------------------------------------
# 4. Result Size Capping
# ---------------------------------------------------------------------------
def cap_result_size(data: str, max_bytes: int = 5 * 1024 * 1024) -> str:
    """Truncate results that exceed the maximum size."""
    encoded = data.encode("utf-8")
    if len(encoded) > max_bytes:
        truncated = encoded[:max_bytes].decode("utf-8", errors="ignore")
        return truncated + f"\n\n[TRUNCATED: Result exceeded {max_bytes} bytes]"
    return data


# ---------------------------------------------------------------------------
# 5. Audit Logging
# ---------------------------------------------------------------------------
def audit_log(
    tool_name: str,
    caller_id: str,
    parameters: dict[str, Any],
    result_summary: str,
    success: bool,
    duration_ms: float,
    error: str | None = None,
) -> None:
    """
    Emit a structured audit log entry for every tool invocation.
    In production, send these to CloudWatch, Splunk, or your SIEM.
    """
    log_data = {
        "event": "mcp_tool_invocation",
        "tool": tool_name,
        "caller_id": caller_id,
        "parameters": _sanitize_params(parameters),
        "success": success,
        "duration_ms": round(duration_ms, 2),
        "result_summary": result_summary[:200],  # Cap summary length
    }
    if error:
        log_data["error"] = error

    if success:
        logger.info("tool_invocation", **log_data)
    else:
        logger.warning("tool_invocation_failed", **log_data)


def _sanitize_params(params: dict[str, Any]) -> dict[str, Any]:
    """Remove sensitive parameter values from audit logs."""
    sensitive_keys = {"password", "secret", "token", "credential", "api_key"}
    return {
        k: "[REDACTED]" if k.lower() in sensitive_keys else v
        for k, v in params.items()
    }


# ---------------------------------------------------------------------------
# 6. Guardrailed Tool Decorator
# ---------------------------------------------------------------------------
def guardrailed(
    tool_name: str,
    caller_id: str = "system",
    enable_pii_redaction: bool = True,
    max_result_bytes: int = 5 * 1024 * 1024,
):
    """
    Decorator that wraps an MCP tool function with full guardrails:
    - Rate limiting
    - Audit logging
    - PII redaction
    - Result size capping

    Usage:
        @guardrailed(tool_name="query_gosdb")
        def my_tool_impl(query: str) -> str:
            ...
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs) -> Any:
            start = time.monotonic()
            try:
                check_rate_limit(caller_id, tool_name)
                result = await func(*args, **kwargs)
                result_str = str(result) if not isinstance(result, str) else result
                result_str = redact_pii(result_str, enable=enable_pii_redaction)
                result_str = cap_result_size(result_str, max_bytes=max_result_bytes)
                duration = (time.monotonic() - start) * 1000
                audit_log(tool_name, caller_id, kwargs, result_str[:100], True, duration)
                return result_str
            except Exception as e:
                duration = (time.monotonic() - start) * 1000
                audit_log(tool_name, caller_id, kwargs, "", False, duration, error=str(e))
                raise

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs) -> Any:
            start = time.monotonic()
            try:
                check_rate_limit(caller_id, tool_name)
                result = func(*args, **kwargs)
                result_str = str(result) if not isinstance(result, str) else result
                result_str = redact_pii(result_str, enable=enable_pii_redaction)
                result_str = cap_result_size(result_str, max_bytes=max_result_bytes)
                duration = (time.monotonic() - start) * 1000
                audit_log(tool_name, caller_id, kwargs, result_str[:100], True, duration)
                return result_str
            except Exception as e:
                duration = (time.monotonic() - start) * 1000
                audit_log(tool_name, caller_id, kwargs, "", False, duration, error=str(e))
                raise

        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator
