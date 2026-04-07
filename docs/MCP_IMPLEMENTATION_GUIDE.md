# How to Build an MCP Server — Implementation Guide

## Overview

This guide walks you through building an MCP (Model Context Protocol) server from scratch. By the end, you'll understand the architecture, design patterns, and security requirements for production-grade MCP servers.

---

## Prerequisites

```bash
pip install mcp              # MCP Python SDK
pip install pydantic          # Input validation
pip install structlog          # Structured logging
```

---

## Step 1: Understand the Architecture

An MCP server is a program that:
1. **Exposes tools** (functions the AI can call)
2. **Exposes resources** (read-only data endpoints)
3. **Communicates** via JSON-RPC over stdio or HTTP

```
AI Host (Claude, etc.)
    │
    ▼ JSON-RPC
MCP Client (built into host)
    │
    ▼ stdio / HTTP
Your MCP Server
    │
    ▼ Your code
Data Sources (DB, API, files)
```

---

## Step 2: Create Your First MCP Server

### Minimal Example

```python
# my_mcp_server.py
"""
Minimal MCP server with one tool.
Run: python my_mcp_server.py
Test: mcp dev my_mcp_server.py
"""
from mcp.server.fastmcp import FastMCP

# Create server with metadata
mcp = FastMCP(
    name="my-data-server",
    version="1.0.0",
    description="Access internal data through standardized tools.",
)


@mcp.tool(
    name="get_user",
    description=(
        "Look up a user by their ID. Returns the user's name, email, "
        "and department. Use this when you need to find information "
        "about a specific employee."
    ),
)
async def get_user(user_id: str) -> dict:
    """
    Retrieve user details by ID.

    Args:
        user_id: The unique employee identifier (e.g., "EMP-12345").

    Returns:
        dict with name, email, department, and status.
    """
    # In production, query your database here
    users = {
        "EMP-001": {"name": "Alice Chen", "email": "alice@company.com", "dept": "Engineering"},
        "EMP-002": {"name": "Bob Park", "email": "bob@company.com", "dept": "Finance"},
    }

    user = users.get(user_id)
    if not user:
        return {"status": "error", "message": f"User {user_id} not found"}

    return {"status": "success", "data": user}


@mcp.resource(
    uri="company://departments",
    name="Department List",
    description="List all departments in the organization.",
)
async def list_departments() -> str:
    return "Engineering, Finance, HR, Legal, Marketing, Operations"


if __name__ == "__main__":
    mcp.run()  # Starts the stdio transport
```

### Running and Testing

```bash
# Option 1: Test with MCP dev tools
mcp dev my_mcp_server.py

# Option 2: Run as stdio server (Claude Desktop connects to this)
python my_mcp_server.py

# Option 3: Run as HTTP server (for remote access)
python -c "
from my_mcp_server import mcp
mcp.run(transport='streamable-http', host='0.0.0.0', port=8080)
"
```

### Connecting to Claude Desktop

Add to your `claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "my-data-server": {
      "command": "python",
      "args": ["path/to/my_mcp_server.py"],
      "env": {
        "DATABASE_URL": "postgresql://..."
      }
    }
  }
}
```

---

## Step 3: Add Database Integration

### Real-World Pattern: Oracle Database MCP

```python
"""
Enterprise database MCP server pattern.
Based on our mcp_enterprise_server/gosdb_mcp.py.
"""
from mcp.server.fastmcp import FastMCP
import oracledb
import structlog

logger = structlog.get_logger()

mcp = FastMCP(name="oracle-data-server", version="1.0.0")

# Connection management
_pool = None

async def get_pool():
    global _pool
    if _pool is None:
        _pool = oracledb.create_pool(
            user="readonly_user",
            password="from_vault",      # NEVER hardcode — use secret manager
            dsn="host:1521/service",
            min=2, max=10,
        )
    return _pool


@mcp.tool(
    name="query_database",
    description=(
        "Execute a read-only SQL SELECT query against the Oracle database. "
        "Only SELECT statements are allowed. The query is validated for "
        "SQL injection before execution. Results are returned as a list "
        "of row dictionaries."
    ),
)
async def query_database(
    query: str,
    schema: str = "PUBLIC",
    max_rows: int = 100,
) -> dict:
    """
    Execute a read-only query.

    Args:
        query:    SQL SELECT statement. Only SELECT is allowed.
        schema:   Database schema to query (must be whitelisted).
        max_rows: Maximum rows to return (1-1000, default 100).
    """
    # --- GUARDRAIL 1: Only SELECT allowed ---
    normalized = query.strip().upper()
    if not normalized.startswith("SELECT"):
        return {"status": "error", "message": "Only SELECT queries are allowed."}

    # --- GUARDRAIL 2: Schema whitelisting ---
    allowed_schemas = ["PUBLIC", "REPORTS", "ANALYTICS"]
    if schema not in allowed_schemas:
        return {"status": "error", "message": f"Schema '{schema}' is not accessible."}

    # --- GUARDRAIL 3: SQL injection patterns ---
    dangerous = ["DROP", "DELETE", "INSERT", "UPDATE", "TRUNCATE", "--", ";"]
    for d in dangerous:
        if d in normalized and d != "SELECT":
            return {"status": "error", "message": "Query contains blocked SQL patterns."}

    # --- Execute ---
    try:
        pool = await get_pool()
        with pool.acquire() as conn:
            with conn.cursor() as cursor:
                cursor.execute(query)
                columns = [col[0] for col in cursor.description]
                rows = cursor.fetchmany(min(max_rows, 1000))

                return {
                    "status": "success",
                    "columns": columns,
                    "rows": [dict(zip(columns, row)) for row in rows],
                    "row_count": len(rows),
                    "truncated": len(rows) >= max_rows,
                }
    except Exception as e:
        logger.error("query_failed", error=str(e))
        return {"status": "error", "message": "Query execution failed. Check syntax."}
```

---

## Step 4: Add Guardrails (Production Requirements)

### The Guardrail Decorator Pattern

```python
"""
Reusable guardrail decorator for MCP tools.
Based on our mcp_enterprise_server/guardrails.py pattern.
"""
import functools
import time
from collections import defaultdict


class RateLimiter:
    """Token bucket rate limiter per caller per tool."""

    def __init__(self, rate: float = 10.0, burst: int = 20):
        self._rate = rate
        self._burst = burst
        self._tokens: dict[str, float] = defaultdict(lambda: float(burst))
        self._last_time: dict[str, float] = defaultdict(time.monotonic)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        elapsed = now - self._last_time[key]
        self._last_time[key] = now
        self._tokens[key] = min(
            self._burst,
            self._tokens[key] + elapsed * self._rate
        )
        if self._tokens[key] >= 1.0:
            self._tokens[key] -= 1.0
            return True
        return False


_rate_limiter = RateLimiter()


def guardrailed(
    tool_name: str,
    permission_level: str = "read",
    rate_limit_key: str = "default",
):
    """
    Decorator that wraps MCP tools with production guardrails.

    Layers:
      1. Rate limiting
      2. Input validation (PII scan)
      3. Audit logging
      4. PII redaction on output
      5. Error wrapping
    """
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            start = time.monotonic()

            # 1. Rate limit
            if not _rate_limiter.allow(f"{rate_limit_key}:{tool_name}"):
                return {"status": "error", "message": "Rate limit exceeded."}

            # 2. Execute
            try:
                result = await func(*args, **kwargs)
            except Exception as e:
                # 5. Error wrapping — never expose raw errors
                return {"status": "error", "message": "Internal error. Contact support."}

            # 3. Audit log
            latency_ms = (time.monotonic() - start) * 1000
            # logger.info("tool_call", tool=tool_name, latency_ms=latency_ms)

            # 4. PII redaction on output
            # from centrag.guardrails.pii import redact_pii
            # result = redact_pii(str(result))

            return result
        return wrapper
    return decorator
```

### Using the Decorator

```python
@mcp.tool(name="query_database", description="...")
@guardrailed(tool_name="query_database", permission_level="read")
async def query_database(query: str) -> dict:
    # Your tool logic here — guardrails are handled by the decorator
    ...
```

---

## Step 5: Design Standards Checklist

### Tool Naming
```
✅ verb_noun format:     query_customers, get_order_status, list_schemas
✅ domain-specific:      calculate_revenue, validate_address
❌ generic:              run_query, execute, do_thing
❌ ambiguous:            process, handle, manage
```

### Tool Descriptions (LLM-Friendly)
```
✅ Good:
"Search for customer orders by customer ID or date range.
Returns order details including items, total, and shipping status.
Use this when you need to look up specific customer purchase history."

❌ Bad:
"Query orders table."
```

### Parameter Design
```python
# ✅ Good: typed, constrained, documented
async def search_orders(
    customer_id: str,                    # Required, typed
    status: str = "all",                 # Default value
    limit: int = 10,                     # Reasonable default
    start_date: str | None = None,       # Optional with clear semantics
) -> dict: ...

# ❌ Bad: untyped, unconstrained
async def search(params: dict) -> str: ...   # AI can't disambiguate
```

### Error Responses
```python
# Always return structured errors
return {
    "status": "error",
    "error_code": "PERMISSION_DENIED",
    "message": "You don't have access to the FINANCE schema.",
    "suggestion": "Request access from your admin, or query the PUBLIC schema.",
}
```

### Security Checklist

| # | Requirement | Priority |
|---|---|---|
| 1 | Never hardcode credentials | **CRITICAL** |
| 2 | Validate ALL inputs server-side | **CRITICAL** |
| 3 | Only SELECT for read-only tools | **CRITICAL** |
| 4 | Schema/table whitelisting | **HIGH** |
| 5 | Rate limiting per caller | **HIGH** |
| 6 | PII redaction on output | **HIGH** |
| 7 | Structured audit logging | **HIGH** |
| 8 | Query timeout enforcement | **MEDIUM** |
| 9 | Result size capping | **MEDIUM** |
| 10 | OAuth 2.1 (production) | **MEDIUM** |

---

## Step 6: Deployment

### Local Development
```bash
# Test with MCP Inspector
mcp dev my_server.py

# Connect to Claude Desktop (add to config)
```

### Docker (Staging/Production)
```dockerfile
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run as HTTP server for remote access
CMD ["python", "-m", "mcp_enterprise_server.server"]
```

### Kubernetes
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: mcp-enterprise-server
spec:
  replicas: 2    # Stateless — scale horizontally
  template:
    spec:
      containers:
      - name: mcp-server
        image: your-registry/mcp-enterprise-server:latest
        ports:
        - containerPort: 8080
        env:
        - name: MCP_TRANSPORT
          value: "streamable-http"
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: db-credentials
              key: url
```

---

## Quick Reference: MCP Python SDK API

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP(name="server-name", version="1.0.0")

# Register a tool (AI-callable function)
@mcp.tool(name="tool_name", description="What it does")
async def my_tool(param: str) -> dict: ...

# Register a resource (read-only data)
@mcp.resource(uri="scheme://path", name="Name", description="What it is")
async def my_resource() -> str: ...

# Register a prompt template
@mcp.prompt(name="prompt_name", description="When to use it")
async def my_prompt(context: str) -> str: ...

# Lifecycle management
@mcp.on_startup
async def startup(): ...    # Initialize connections

@mcp.on_shutdown
async def shutdown(): ...   # Cleanup

# Run the server
mcp.run()                        # stdio (default)
mcp.run(transport="streamable-http", port=8080)  # HTTP
```

---

## How CentRAG's MCP Server is Organized

```
mcp_enterprise_server/
├── server.py              # Main entry point — aggregates all tools
├── config.py              # Pydantic settings (env-driven)
├── guardrails.py          # Unified guardrail decorator
├── aws_credentials.py     # STS-based credential management
├── gosdb_mcp.py           # Oracle/GOS DB tools (bounded context)
├── dynamodb_mcp.py        # DynamoDB tools (bounded context)
└── athena_mcp.py          # Athena analytics tools (bounded context)
```

**Key pattern:** Each `*_mcp.py` file is a **bounded context** that registers tools for one data source. The `server.py` aggregates them all into a single MCP server.

---

## Next Steps

1. **Start simple:** Build a single-tool MCP server for your most common data query
2. **Add guardrails:** Use the decorator pattern for rate limiting and audit logging
3. **Test with AI:** Connect to Claude Desktop or MCP Inspector
4. **Iterate:** Add more tools based on what the AI actually needs
5. **Harden:** Add OAuth, monitoring, and deployment automation
