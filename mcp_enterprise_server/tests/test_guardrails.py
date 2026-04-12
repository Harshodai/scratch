"""
Unit Tests for Guardrails
==========================
Tests the SQL validation, rate limiting, PII redaction, and audit logging.
"""

from __future__ import annotations

import pytest

from mcp_enterprise_server.config import PermissionLevel
from mcp_enterprise_server.guardrails import (
    QueryValidationError,
    TokenBucketRateLimiter,
    cap_result_size,
    redact_pii,
    validate_schema_access,
    validate_sql_query,
    validate_table_access,
)


# ===========================================================================
# SQL Validation Tests
# ===========================================================================
class TestSQLValidation:
    BLOCKED_KEYWORDS = ["DROP", "TRUNCATE", "ALTER", "CREATE", "DELETE"]

    def test_valid_select_passes(self):
        result = validate_sql_query(
            "SELECT * FROM orders WHERE id = :id",
            self.BLOCKED_KEYWORDS,
            PermissionLevel.READ_ONLY,
        )
        assert "SELECT" in result.upper()

    def test_valid_with_cte_passes(self):
        result = validate_sql_query(
            "WITH cte AS (SELECT id FROM users) SELECT * FROM cte",
            self.BLOCKED_KEYWORDS,
            PermissionLevel.READ_ONLY,
        )
        assert "WITH" in result.upper()

    def test_drop_blocked(self):
        with pytest.raises(QueryValidationError, match="DROP"):
            validate_sql_query(
                "DROP TABLE users",
                self.BLOCKED_KEYWORDS,
                PermissionLevel.READ_ONLY,
            )

    def test_truncate_blocked(self):
        with pytest.raises(QueryValidationError, match="TRUNCATE"):
            validate_sql_query(
                "TRUNCATE TABLE orders",
                self.BLOCKED_KEYWORDS,
                PermissionLevel.READ_ONLY,
            )

    def test_delete_blocked(self):
        with pytest.raises(QueryValidationError, match="DELETE"):
            validate_sql_query(
                "DELETE FROM orders WHERE id = 1",
                self.BLOCKED_KEYWORDS,
                PermissionLevel.READ_ONLY,
            )

    def test_insert_blocked_in_readonly(self):
        with pytest.raises(QueryValidationError, match="Read-only"):
            validate_sql_query(
                "INSERT INTO orders VALUES (1, 'test')",
                self.BLOCKED_KEYWORDS,
                PermissionLevel.READ_ONLY,
            )

    def test_update_blocked_in_readonly(self):
        with pytest.raises(QueryValidationError, match="Read-only"):
            validate_sql_query(
                "UPDATE orders SET status = 'done'",
                self.BLOCKED_KEYWORDS,
                PermissionLevel.READ_ONLY,
            )

    def test_union_injection_blocked(self):
        with pytest.raises(QueryValidationError, match="dangerous"):
            validate_sql_query(
                "SELECT * FROM users UNION SELECT * FROM passwords",
                self.BLOCKED_KEYWORDS,
                PermissionLevel.READ_ONLY,
            )

    def test_comment_injection_blocked(self):
        with pytest.raises(QueryValidationError, match="dangerous"):
            validate_sql_query(
                "SELECT * FROM users -- WHERE admin = true",
                self.BLOCKED_KEYWORDS,
                PermissionLevel.READ_ONLY,
            )

    def test_chained_statements_blocked(self):
        with pytest.raises(QueryValidationError, match="dangerous"):
            validate_sql_query(
                "SELECT 1; DROP TABLE users",
                self.BLOCKED_KEYWORDS,
                PermissionLevel.READ_ONLY,
            )

    def test_admin_bypasses_keyword_block(self):
        # Admin mode allows blocked keywords (but still blocks injection patterns)
        result = validate_sql_query(
            "CREATE TABLE test (id INT)",
            self.BLOCKED_KEYWORDS,
            PermissionLevel.ADMIN,
        )
        assert "CREATE" in result.upper()

    def test_explain_passes(self):
        result = validate_sql_query(
            "EXPLAIN SELECT * FROM orders",
            self.BLOCKED_KEYWORDS,
            PermissionLevel.READ_ONLY,
        )
        assert "EXPLAIN" in result.upper()


# ===========================================================================
# Schema / Table Access Tests
# ===========================================================================
class TestAccessValidation:
    def test_valid_schema_passes(self):
        validate_schema_access("APP_DATA", ["APP_DATA", "ANALYTICS"])

    def test_invalid_schema_blocked(self):
        with pytest.raises(QueryValidationError, match="not in the allowed"):
            validate_schema_access("SECRET_SCHEMA", ["APP_DATA", "ANALYTICS"])

    def test_empty_whitelist_allows_all(self):
        validate_schema_access("ANYTHING", [])

    def test_valid_table_passes(self):
        validate_table_access("users", ["users", "orders"])

    def test_invalid_table_blocked(self):
        with pytest.raises(QueryValidationError, match="not in the allowed"):
            validate_table_access("passwords", ["users", "orders"])


# ===========================================================================
# Rate Limiting Tests
# ===========================================================================
class TestRateLimiting:
    def test_burst_allowed(self):
        limiter = TokenBucketRateLimiter(max_tokens=5, refill_rate_per_second=1.0)
        for _ in range(5):
            assert limiter.allow("test_key")

    def test_exceeds_limit(self):
        limiter = TokenBucketRateLimiter(max_tokens=2, refill_rate_per_second=0.1)
        assert limiter.allow("key")
        assert limiter.allow("key")
        assert not limiter.allow("key")  # Exceeded

    def test_different_keys_independent(self):
        limiter = TokenBucketRateLimiter(max_tokens=1, refill_rate_per_second=0.1)
        assert limiter.allow("key_a")
        assert limiter.allow("key_b")  # Different key, independent bucket
        assert not limiter.allow("key_a")  # key_a exhausted


# ===========================================================================
# PII Redaction Tests
# ===========================================================================
class TestPIIRedaction:
    def test_ssn_redacted(self):
        result = redact_pii("SSN: 123-45-6789")
        assert "[REDACTED_SSN]" in result
        assert "123-45-6789" not in result

    def test_credit_card_redacted(self):
        result = redact_pii("Card: 4111-1111-1111-1111")
        assert "[REDACTED_CREDIT_CARD]" in result

    def test_email_redacted(self):
        result = redact_pii("Contact: john@example.com")
        assert "[REDACTED_EMAIL]" in result
        assert "john@example.com" not in result

    def test_disabled_returns_original(self):
        original = "SSN: 123-45-6789"
        result = redact_pii(original, enable=False)
        assert result == original

    def test_no_pii_unchanged(self):
        original = "This is a normal log message with 42 items."
        result = redact_pii(original)
        assert result == original


# ===========================================================================
# Result Size Capping Tests
# ===========================================================================
class TestResultCapping:
    def test_small_result_unchanged(self):
        data = "small data"
        result = cap_result_size(data, max_bytes=1000)
        assert result == data

    def test_large_result_truncated(self):
        data = "x" * 10000
        result = cap_result_size(data, max_bytes=100)
        assert len(result) < 10000
        assert "TRUNCATED" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
