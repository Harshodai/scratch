"""
GOS DB MCP Connection
=====================
MCP tools for querying JPMC's internal GOS DB (Oracle-compatible database).

Architecture:
  ┌─────────────┐    ┌────────────┐    ┌──────────────┐    ┌──────────┐
  │ MCP Client  │───▶│ MCP Server │───▶│  Guardrails  │───▶│  GOS DB  │
  │ (AI Agent)  │    │ (FastMCP)  │    │  (validate)  │    │ (Oracle) │
  └─────────────┘    └────────────┘    └──────────────┘    └──────────┘

Security layers:
  1. SQL Keyword Blocking — DROP, TRUNCATE, ALTER etc. are rejected
  2. Schema Whitelisting  — Only approved schemas (APP_DATA, ANALYTICS, etc.)
  3. Row Limit Enforcement — Hard cap on returned rows
  4. Query Timeout         — Kills long-running queries
  5. PII Redaction         — Scrubs SSN/CC/email from results
  6. Rate Limiting         — Per-caller throttling

Connection:
  Uses python-oracledb in thin mode (no Oracle Client install required).
  For mTLS, configure the wallet_location in GOSDBConfig.
"""

from __future__ import annotations

import json
import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Optional

import oracledb
import structlog

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession

from mcp_enterprise_server.config import GOSDBConfig, PermissionLevel
from mcp_enterprise_server.guardrails import (
    QueryValidationError,
    validate_sql_query,
    validate_schema_access,
    check_rate_limit,
    redact_pii,
    cap_result_size,
    audit_log,
)

logger = structlog.get_logger("gosdb_mcp")


# ---------------------------------------------------------------------------
# Connection Pool Manager
# ---------------------------------------------------------------------------
class GOSDBPool:
    """
    Manages an oracledb connection pool for GOS DB.

    Uses thin mode by default — no Oracle Client installation needed.
    For production with mTLS wallets, set wallet_location in config.
    """

    def __init__(self, config: GOSDBConfig):
        self._config = config
        self._pool: Optional[oracledb.AsyncConnectionPool] = None

    async def initialize(self) -> None:
        """Create the async connection pool."""
        pool_params: dict[str, Any] = {
            "user": self._config.username,
            "password": self._config.password.get_secret_value(),
            "dsn": self._config.dsn,
            "min": self._config.pool_min,
            "max": self._config.pool_max,
            "increment": self._config.pool_increment,
        }

        # If wallet is configured, use mTLS
        if self._config.wallet_location:
            pool_params["wallet_location"] = self._config.wallet_location
            pool_params["wallet_password"] = self._config.password.get_secret_value()

        self._pool = await oracledb.create_pool_async(**pool_params)
        logger.info(
            "gosdb_pool_created",
            dsn=self._config.dsn,
            min_pool=self._config.pool_min,
            max_pool=self._config.pool_max,
        )

    async def close(self) -> None:
        """Close the connection pool."""
        if self._pool:
            await self._pool.close(force=True)
            logger.info("gosdb_pool_closed")

    @asynccontextmanager
    async def get_connection(self) -> AsyncIterator[oracledb.AsyncConnection]:
        """Acquire a connection from the pool with timeout enforcement."""
        if not self._pool:
            raise RuntimeError("GOS DB pool not initialized. Call initialize() first.")

        conn = await self._pool.acquire()
        try:
            # Set query timeout at the session level (synchronous property)
            conn.call_timeout = self._config.query_timeout_seconds * 1000  # ms
            yield conn
        finally:
            await self._pool.release(conn)

    async def execute_query(
        self,
        query: str,
        params: Optional[dict[str, Any]] = None,
        max_rows: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        """
        Execute a SELECT query and return results as list of dicts.

        Uses parameterized queries to prevent SQL injection at the driver level.
        """
        effective_max_rows = max_rows or self._config.max_rows_per_query

        async with self.get_connection() as conn:
            async with conn.cursor() as cursor:
                if params:
                    await cursor.execute(query, params)
                else:
                    await cursor.execute(query)

                columns = [col[0] for col in cursor.description] if cursor.description else []
                rows = await cursor.fetchmany(effective_max_rows)

                results = [dict(zip(columns, row)) for row in rows]

                # Check if there are more rows
                extra = await cursor.fetchone()
                if extra:
                    logger.warning(
                        "query_result_truncated",
                        max_rows=effective_max_rows,
                        query_preview=query[:100],
                    )

                return results


# ---------------------------------------------------------------------------
# MCP Server Context for GOS DB
# ---------------------------------------------------------------------------
@dataclass
class GOSDBAppContext:
    """Typed application context carrying the GOS DB pool."""
    pool: GOSDBPool
    config: GOSDBConfig


# ---------------------------------------------------------------------------
# Tool Functions (to be registered on the MCP server)
# ---------------------------------------------------------------------------
async def query_gosdb(
    query: str,
    schema: str = "APP_DATA",
    max_rows: int = 1000,
    params: Optional[dict[str, Any]] = None,
    *,  # Force keyword args below
    pool: GOSDBPool,
    config: GOSDBConfig,
    caller_id: str = "system",
) -> str:
    """
    Execute a read-only SQL query against GOS DB.

    Args:
        query:    SQL SELECT query (parameterized placeholders use :name syntax)
        schema:   Target schema name (must be in allowed list)
        max_rows: Maximum rows to return (capped by server config)
        params:   Optional bind parameters for the query (e.g., {"id": 123})

    Returns:
        JSON string of query results.

    Example:
        query_gosdb(
            query="SELECT * FROM APP_DATA.transactions WHERE amount > :min_amount",
            schema="APP_DATA",
            params={"min_amount": 1000},
            max_rows=100
        )
    """
    import time
    start = time.monotonic()

    try:
        # 1. Rate limit check
        check_rate_limit(caller_id, "query_gosdb")

        # 2. Validate schema access
        validate_schema_access(schema, config.allowed_schemas)

        # 3. Validate SQL query
        validated_query = validate_sql_query(
            query, config.blocked_keywords, config.permission_level
        )

        # 4. Enforce max_rows cap
        effective_max = min(max_rows, config.max_rows_per_query)

        # 5. Execute
        results = await pool.execute_query(
            validated_query,
            params=params or {},
            max_rows=effective_max,
        )

        # 6. Format response
        response = {
            "status": "success",
            "schema": schema,
            "row_count": len(results),
            "max_rows_applied": effective_max,
            "data": results,
        }
        response_str = json.dumps(response, default=str, indent=2)

        # 7. PII redaction
        response_str = redact_pii(response_str, enable=True)

        # 8. Size cap
        response_str = cap_result_size(response_str)

        # 9. Audit
        duration = (time.monotonic() - start) * 1000
        audit_log(
            "query_gosdb", caller_id,
            {"query": query[:200], "schema": schema, "max_rows": effective_max},
            f"{len(results)} rows returned", True, duration,
        )

        return response_str

    except (QueryValidationError, Exception) as e:
        duration = (time.monotonic() - start) * 1000
        audit_log(
            "query_gosdb", caller_id,
            {"query": query[:200], "schema": schema},
            "", False, duration, error=str(e),
        )
        raise


async def list_gosdb_schemas(
    *,
    pool: GOSDBPool,
    config: GOSDBConfig,
    caller_id: str = "system",
) -> str:
    """
    List available schemas in GOS DB that the MCP server has access to.

    Returns only schemas in the allowed_schemas whitelist.
    """
    check_rate_limit(caller_id, "list_gosdb_schemas")

    # Build parameterized IN clause with numbered bind variables
    # e.g., WHERE username IN (:s0, :s1, :s2)
    binds = {f"s{i}": s.upper() for i, s in enumerate(config.allowed_schemas)}
    placeholders = ", ".join(f":s{i}" for i in range(len(config.allowed_schemas)))
    query = f"""
        SELECT username AS schema_name,
               created AS created_date
        FROM all_users
        WHERE username IN ({placeholders})
        ORDER BY username
    """

    results = await pool.execute_query(query, params=binds, max_rows=100)

    response = {
        "status": "success",
        "allowed_schemas": config.allowed_schemas,
        "schemas": results,
    }
    return json.dumps(response, default=str, indent=2)


async def list_gosdb_tables(
    schema: str = "APP_DATA",
    *,
    pool: GOSDBPool,
    config: GOSDBConfig,
    caller_id: str = "system",
) -> str:
    """
    List tables in a specific GOS DB schema.

    Args:
        schema: Schema name (must be in allowed list)
    """
    check_rate_limit(caller_id, "list_gosdb_tables")
    validate_schema_access(schema, config.allowed_schemas)

    query = """
        SELECT table_name, num_rows, last_analyzed
        FROM all_tables
        WHERE owner = :schema_name
        ORDER BY table_name
    """
    results = await pool.execute_query(query, params={"schema_name": schema.upper()})

    response = {
        "status": "success",
        "schema": schema,
        "table_count": len(results),
        "tables": results,
    }
    return json.dumps(response, default=str, indent=2)


async def describe_gosdb_table(
    table_name: str,
    schema: str = "APP_DATA",
    *,
    pool: GOSDBPool,
    config: GOSDBConfig,
    caller_id: str = "system",
) -> str:
    """
    Get column metadata for a specific table in GOS DB.

    Args:
        table_name: Name of the table
        schema:     Schema name (must be in allowed list)
    """
    check_rate_limit(caller_id, "describe_gosdb_table")
    validate_schema_access(schema, config.allowed_schemas)

    query = """
        SELECT column_name, data_type, data_length, nullable, data_default
        FROM all_tab_columns
        WHERE owner = :schema_name AND table_name = :table_name
        ORDER BY column_id
    """
    results = await pool.execute_query(
        query,
        params={"schema_name": schema.upper(), "table_name": table_name.upper()},
    )

    response = {
        "status": "success",
        "schema": schema,
        "table": table_name,
        "column_count": len(results),
        "columns": results,
    }
    return json.dumps(response, default=str, indent=2)


# ---------------------------------------------------------------------------
# Register tools on a FastMCP server
# ---------------------------------------------------------------------------
def register_gosdb_tools(mcp_server: FastMCP, config: GOSDBConfig) -> None:
    """
    Register all GOS DB MCP tools on the given FastMCP server instance.

    This is called during server startup after the connection pool is ready.
    The pool is injected via the server's lifespan context.
    """

    @mcp_server.tool(
        name="query_gosdb",
        description=(
            "Execute a read-only SQL query against JPMC GOS DB (Oracle). "
            "Use :name syntax for bind parameters. "
            "Only SELECT/WITH/EXPLAIN allowed. "
            f"Allowed schemas: {config.allowed_schemas}. "
            f"Max {config.max_rows_per_query} rows per query."
        ),
    )
    async def tool_query_gosdb(
        query: str,
        schema: str = "APP_DATA",
        max_rows: int = 1000,
        ctx: Context[ServerSession, GOSDBAppContext] = None,
    ) -> str:
        """Execute SQL query against GOS DB with full guardrails."""
        app_ctx = ctx.request_context.lifespan_context
        caller = ctx.client_id or "unknown"
        return await query_gosdb(
            query=query,
            schema=schema,
            max_rows=max_rows,
            pool=app_ctx.pool,
            config=app_ctx.config,
            caller_id=caller,
        )

    @mcp_server.tool(
        name="list_gosdb_schemas",
        description="List available schemas in GOS DB that are accessible via MCP.",
    )
    async def tool_list_schemas(
        ctx: Context[ServerSession, GOSDBAppContext] = None,
    ) -> str:
        """List accessible GOS DB schemas."""
        app_ctx = ctx.request_context.lifespan_context
        caller = ctx.client_id or "unknown"
        return await list_gosdb_schemas(
            pool=app_ctx.pool,
            config=app_ctx.config,
            caller_id=caller,
        )

    @mcp_server.tool(
        name="list_gosdb_tables",
        description="List tables in a GOS DB schema.",
    )
    async def tool_list_tables(
        schema: str = "APP_DATA",
        ctx: Context[ServerSession, GOSDBAppContext] = None,
    ) -> str:
        """List tables in GOS DB schema."""
        app_ctx = ctx.request_context.lifespan_context
        caller = ctx.client_id or "unknown"
        return await list_gosdb_tables(
            schema=schema,
            pool=app_ctx.pool,
            config=app_ctx.config,
            caller_id=caller,
        )

    @mcp_server.tool(
        name="describe_gosdb_table",
        description="Get column metadata for a GOS DB table.",
    )
    async def tool_describe_table(
        table_name: str,
        schema: str = "APP_DATA",
        ctx: Context[ServerSession, GOSDBAppContext] = None,
    ) -> str:
        """Describe columns of a GOS DB table."""
        app_ctx = ctx.request_context.lifespan_context
        caller = ctx.client_id or "unknown"
        return await describe_gosdb_table(
            table_name=table_name,
            schema=schema,
            pool=app_ctx.pool,
            config=app_ctx.config,
            caller_id=caller,
        )

    logger.info("gosdb_tools_registered", tool_count=4)
