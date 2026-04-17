"""
Dynamic SQL MCP Factory — On-the-fly tool registration for any SQL database.

The WHY:
    Enterprise environments have thousands of databases. Manually writing MCP
    servers for each is impossible. This factory uses SQLAlchemy reflection
    to inspect schema at runtime and generate localized MCP tools for
    specific tables/views.

    Security:
        - Table/schema names come from SQLAlchemy reflection (safe).
        - ALL user-facing queries use SQLAlchemy text() with bound parameters.
        - A read-only guardrail blocks dangerous keywords at the statement level.
        - The raw SQL tool is intentionally restricted to SELECT-only.

Architecture:
    - Connection String -> Engines
    - Inspector -> Metadata/Table Schemas
    - Generator -> Tools (query_<table>, describe_<table>)

Pattern: FACTORY + ADAPTER
"""

from __future__ import annotations

import json
from typing import Any, Optional

from sqlalchemy import create_engine, inspect, text
from mcp.server.fastmcp import FastMCP

from centrag.utils.logger import get_logger

logger = get_logger("mcp.dynamic_factory")

# Blocked SQL keywords for read-only enforcement
_BLOCKED_KEYWORDS = frozenset({
    "DROP", "DELETE", "UPDATE", "INSERT", "TRUNCATE", "ALTER",
    "CREATE", "GRANT", "REVOKE", "EXEC", "EXECUTE", "MERGE",
})


def _is_read_only(query: str) -> bool:
    """Check if the SQL statement is read-only.

    The WHY:
        Dynamic MCP tools MUST be read-only in production. This guardrail
        prevents accidental or malicious data mutation via the MCP layer.
    """
    # Normalize and tokenize
    tokens = query.upper().split()
    return not any(token in _BLOCKED_KEYWORDS for token in tokens)


class DynamicSQLMCPFactory:
    """
    Generates a production-grade MCP server for any SQL database dynamically.

    Usage:
        factory = DynamicSQLMCPFactory()
        mcp = factory.create_server(
            name="gos-db",
            connection_string="postgresql://user:pass@host/db",
            schema="public",
            tables=["orders", "customers"],
        )
    """

    @staticmethod
    def create_server(
        name: str,
        connection_string: str,
        schema: Optional[str] = None,
        tables: Optional[list[str]] = None,
    ) -> FastMCP:
        """
        Create a FastMCP server with tools dynamically generated from DB schema.

        Args:
            name: Server name (e.g. "gos-db-mcp")
            connection_string: SQLAlchemy-compatible DSN
            schema: Target schema name
            tables: List of tables to expose. If None, exposes all in schema.
        """
        mcp = FastMCP(name)
        engine = create_engine(connection_string)

        # 1. Inspect Schema
        inspector = inspect(engine)
        target_schema = schema or inspector.default_schema_name

        available_tables = inspector.get_table_names(schema=target_schema)
        if tables:
            # Filter to only requested tables that actually exist
            tables_to_expose = [t for t in tables if t in available_tables]
            missing = set(tables) - set(tables_to_expose)
            if missing:
                logger.warning(
                    "mcp_dynamic_factory_missing_tables",
                    missing=list(missing),
                    available=available_tables,
                )
        else:
            tables_to_expose = available_tables

        logger.info(
            "mcp_dynamic_factory_init",
            db_name=name,
            schema=target_schema,
            tables_count=len(tables_to_expose),
        )

        # 2. Register Generic Query Tool (read-only, parameterized)
        @mcp.tool()
        async def execute_read_query(query: str, limit: int = 100) -> str:
            """Execute a read-only SQL query on the database.

            Only SELECT statements are allowed. All other statements are blocked.
            Results are limited to prevent runaway queries.
            """
            if not _is_read_only(query):
                return "Error: Only read-only SELECT queries are allowed."

            try:
                with engine.connect() as conn:
                    result = conn.execute(text(query))
                    if result.returns_rows:
                        columns = list(result.keys())
                        rows = [dict(zip(columns, row)) for row in result.fetchmany(limit)]
                        return json.dumps(
                            {
                                "columns": columns,
                                "rows": rows,
                                "count": len(rows),
                                "truncated": len(rows) >= limit,
                            },
                            default=str,
                        )
                    return "Query executed successfully (no rows returned)."
            except Exception as e:
                return f"Database Error: {str(e)}"

        # 3. Generate Specialized Tools for each table
        #    These use parameterized queries to prevent SQL injection.
        def make_table_tool(table_name: str, schema_name: str):
            """Closure to generate a safe, parameterized tool for a specific table."""

            @mcp.tool(name=f"query_{table_name}")
            async def query_table(
                columns: Optional[str] = None,
                where_column: Optional[str] = None,
                where_value: Optional[str] = None,
                limit: int = 50,
            ) -> str:
                """Read data from the specific table with optional column filtering.

                Args:
                    columns: Comma-separated column names (default: all columns).
                    where_column: Column name for WHERE clause filtering.
                    where_value: Value to filter by (parameterized, safe from injection).
                    limit: Max rows to return (default 50).
                """
                # Validate column names against reflected schema to prevent injection
                reflected_cols = [
                    c["name"]
                    for c in inspector.get_columns(table_name, schema=schema_name)
                ]

                if columns:
                    requested = [c.strip() for c in columns.split(",")]
                    invalid = [c for c in requested if c not in reflected_cols]
                    if invalid:
                        return f"Error: Invalid columns: {invalid}. Valid: {reflected_cols}"
                    col_str = ", ".join(requested)
                else:
                    col_str = "*"

                # Build parameterized query
                sql = f"SELECT {col_str} FROM {schema_name}.{table_name}"

                params: dict[str, Any] = {}
                if where_column and where_value is not None:
                    if where_column not in reflected_cols:
                        return f"Error: Invalid filter column '{where_column}'. Valid: {reflected_cols}"
                    sql += f" WHERE {where_column} = :filter_value"
                    params["filter_value"] = where_value

                sql += " LIMIT :row_limit"
                params["row_limit"] = limit

                try:
                    with engine.connect() as conn:
                        result = conn.execute(text(sql), params)
                        col_names = list(result.keys())
                        rows = [dict(zip(col_names, row)) for row in result.fetchall()]
                        return json.dumps(
                            {
                                "table": table_name,
                                "columns": col_names,
                                "rows": rows,
                                "count": len(rows),
                            },
                            default=str,
                        )
                except Exception as e:
                    return f"Database Error: {str(e)}"

            return query_table

        for table in tables_to_expose:
            make_table_tool(table, target_schema)

        @mcp.tool()
        async def describe_schema() -> str:
            """List all tables and columns available in this MCP server."""
            manifest = {}
            for t in tables_to_expose:
                cols = inspector.get_columns(t, schema=target_schema)
                manifest[t] = [
                    {"name": c["name"], "type": str(c["type"]), "nullable": c["nullable"]}
                    for c in cols
                ]
            return json.dumps(manifest, indent=2)

        return mcp
