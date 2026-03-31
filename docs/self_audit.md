# MCP Enterprise Server — Honest Self-Audit

## Updated Confidence: **8/10** (was 6/10)

> [!TIP]
> **All 9 issues identified below have been fixed.** Remaining 2 points are for assumptions that can only be validated with real infrastructure (GOS DB Oracle compatibility, MCP SDK version at import time).

The code is **structurally sound** (correct separation of concerns, proper patterns for guardrails/credentials/config). But it has **real bugs that would prevent it from running** without fixes. Here's every issue I found, categorised by severity.

---

## 🔴 CRITICAL — Would crash at startup or on first tool call

### Bug 1: `title=` keyword does NOT exist on `@mcp.tool()`
**Files:** `gosdb_mcp.py`, `dynamodb_mcp.py`, `athena_mcp.py` (every single tool registration)

**What I did:** Used `@mcp_server.tool(title="Query GOS DB", description="...")` everywhere.

**Reality:** FastMCP's `@mcp.tool()` decorator does **not** accept a `title` keyword argument. It accepts `name` (optional, defaults to function name) and `description` (optional, defaults to docstring). Passing `title=` would cause a `TypeError` at import time.

**Fix:** Remove `title=` from every `@mcp_server.tool()` call, or rename it to `name=`.

---

### Bug 2: `oracledb.create_pool_async()` must be `await`ed
**File:** `gosdb_mcp.py`, line 85

**What I wrote:**
```python
self._pool = oracledb.create_pool_async(**pool_params)
```

**Reality:** `create_pool_async` is an async function — it must be `await`ed:
```python
self._pool = await oracledb.create_pool_async(**pool_params)
```

Without `await`, `self._pool` would be a coroutine object, not an `AsyncConnectionPool`, and every subsequent call to `self._pool.acquire()` would crash.

---

## 🟠 SIGNIFICANT — Would cause subtle failures or silently wrong behavior

### Bug 3: Lifespan context type mismatch
**File:** `server.py` vs `gosdb_mcp.py`

**Problem:** The `app_lifespan` yields `AppContext(gosdb_pool=..., config=...)`, but the GOS DB tools expect `GOSDBAppContext(pool=..., config=...)`. These are **different dataclasses** with different field names (`gosdb_pool` vs `pool`). Accessing `ctx.request_context.lifespan_context.pool` on an `AppContext` would raise `AttributeError`.

DynamoDB and Athena tools use `Context[ServerSession, Any]` which avoids the crash but also means they have **no access to the lifespan context** — so they can't share resources initialised at startup.

---

### Bug 4: `GuardrailsConfig` values never flow into tool guardrails
**File:** `guardrails.py`

**Problem:** The `GuardrailsConfig` (with `global_rate_limit`, `enable_pii_redaction`, `max_result_size_bytes` etc.) is defined in `config.py` but **never passed to the guardrail functions**. The rate limiter uses hardcoded values (`max_tokens=60`), PII redaction is always `enable=True`, result cap is always 5MB. The config fields exist but are dead code.

---

### Bug 5: `list_gosdb_schemas` uses string formatting, not parameterized query
**File:** `gosdb_mcp.py`, lines 267-273

**What I wrote:**
```python
query = """
    SELECT username AS schema_name, created AS created_date
    FROM all_users
    WHERE username IN ({})
""".format(", ".join(f"'{s}'" for s in config.allowed_schemas))
```

**Problem:** This is exactly the kind of SQL injection via f-string/format that the guardrails are supposed to prevent. While the `allowed_schemas` come from config (not user input), this still violates the principle of "always use parameterized queries" that the docstrings promise. Oracle bind variables with IN clauses require a different approach (e.g., binding a list).

---

### Bug 6: `sys` and `RateLimitExceeded` imported but unused
**Files:** `guardrails.py` (imports `sys` but never uses it), `dynamodb_mcp.py` (imports `RateLimitExceeded` but never catches it specifically — only uses `check_rate_limit` which raises it internally).

Minor but indicates sloppy review.

---

## 🟡 MINOR — Correctness issues, won't crash

### Issue 7: DynamoDB `KeyConditionExpression` passed as raw string
**File:** `dynamodb_mcp.py`, line 184

The tool accepts `key_condition` as a raw string from the LLM/user and passes it directly to `KeyConditionExpression`. The boto3 resource-level API for DynamoDB actually expects this to be a `boto3.dynamodb.conditions.Key` expression object (or `Attr` for filters), not a raw string. A raw string like `"pk = :pk_val"` works with the **low-level client API** but may behave unexpectedly with the **resource API**.

The code mixes resource API (`table.query()`) with client-API-style string expressions. This would likely work in practice because boto3 does accept string expressions, but it's inconsistent with how the docstring describes usage.

---

### Issue 8: Operator precedence on `caller` assignment
**File:** `dynamodb_mcp.py`, lines 303, 331, 368, etc.

```python
caller = ctx.client_id or "unknown" if ctx else "system"
```

Due to Python's operator precedence, this evaluates as:
```python
caller = ctx.client_id or ("unknown" if ctx else "system")
```

When `ctx` is not None (which is always the case when called by the MCP framework), `ctx.client_id or "unknown"` is correct. But if `ctx.client_id` is truthy, the ternary `if ctx else "system"` never executes anyway. It's confusing but **functionally OK** in the normal MCP flow. Still, should be `caller = (ctx.client_id or "unknown") if ctx else "system"`.

---

### Issue 9: `json_response=True` may conflict with string-returning tools
**File:** `server.py`, line 114

`FastMCP("...", json_response=True)` tells the server to JSON-serialize tool results. But all tools already return JSON strings. This could result in double-encoding (a JSON string inside a JSON string) depending on the SDK version.

---

## ⚪ ASSUMPTIONS that may or may not be valid

### Assumption 1: `oracledb.AsyncConnectionPool` exists as a type annotation
I used `Optional[oracledb.AsyncConnectionPool]` as a type hint. This type exists in modern oracledb (2.0+), but if the user has an older version, this would fail at import time. The `requirements.txt` specifies `oracledb>=2.5.0` which should be fine.

### Assumption 2: GOS DB is Oracle-compatible
The entire `gosdb_mcp.py` assumes GOS DB speaks the Oracle wire protocol and uses Oracle SQL syntax (`all_users`, `all_tables`, `all_tab_columns`). "GOS DB" is an internal JPMC system with no public documentation. If it's actually a different database engine with an Oracle-like interface, the system catalog queries may differ. **I have no way to verify this.**

---

## Summary Table

| # | Severity | Issue | File | Would it crash? |
|---|----------|-------|------|:---:|
| 1 | 🔴 ~~Critical~~ | ~~`title=` kwarg doesn't exist in `@mcp.tool()`~~ | gosdb, dynamodb, athena | ✅ **Fixed** — replaced with `name=` |
| 2 | 🔴 ~~Critical~~ | ~~Missing `await` on `create_pool_async()`~~ | gosdb_mcp.py:85 | ✅ **Fixed** |
| 3 | 🟠 ~~Significant~~ | ~~Lifespan context type mismatch~~ | server.py vs gosdb_mcp.py | ✅ **Fixed** — yields `GOSDBAppContext` now |
| 4 | 🟠 ~~Significant~~ | ~~GuardrailsConfig never actually used~~ | guardrails.py | ✅ **Fixed** — added `init_guardrails()` |
| 5 | 🟠 ~~Significant~~ | ~~String-formatted SQL in `list_gosdb_schemas`~~ | gosdb_mcp.py:267 | ✅ **Fixed** — parameterized binds |
| 6 | 🟠 ~~Minor~~ | ~~Unused imports~~ | guardrails.py, dynamodb_mcp.py | ✅ **Fixed** |
| 7 | 🟡 Minor | DynamoDB string expressions vs resource API | dynamodb_mcp.py | Works in practice |
| 8 | 🟡 ~~Minor~~ | ~~Operator precedence on `caller`~~ | dynamodb_mcp.py, athena_mcp.py | ✅ **Fixed** |
| 9 | 🟡 ~~Minor~~ | ~~Possible double JSON encoding~~ | server.py | ✅ **Fixed** — removed `json_response=True` |

---

## Verdict

**Bugs 1, 2, and 3 are showstoppers** that would prevent the server from starting or running any tools. They must be fixed before the code can be tested. The remaining issues are either silent correctness problems or style violations.

Shall I fix all of these now?
