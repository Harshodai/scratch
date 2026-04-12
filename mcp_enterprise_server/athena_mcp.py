"""
AWS Athena MCP Connection
==========================
MCP tools for executing SQL queries on Amazon Athena (serverless analytics).

Architecture:
  ┌─────────────┐    ┌────────────┐    ┌──────────────┐    ┌──────────┐
  │ MCP Client  │───▶│ MCP Server │───▶│  Guardrails  │───▶│  Athena  │
  │ (AI Agent)  │    │ (FastMCP)  │    │ (validate)   │    │  (SQL)   │
  └─────────────┘    └────────────┘    └──────────────┘    └──────────┘
                                                               │
                                                          ┌────▼────┐
                                                          │ S3 /    │
                                                          │ Glue    │
                                                          │ Catalog │
                                                          └─────────┘

Security layers:
  1. IAM Role-Based Access    — STS AssumeRole with temp credentials
  2. SQL Validation           — Block DROP/ALTER/CREATE/DELETE
  3. Database Whitelisting    — Only approved Glue databases
  4. Cost Control             — Max bytes scanned per query
  5. Query Timeout            — Cancel long-running queries
  6. PII Redaction            — Strip PII from query results
  7. Rate Limiting + Audit    — Per-caller throttling

Design:
  - Athena queries are asynchronous — we start execution, poll for completion,
    then fetch results.
  - S3 results are auto-cleaned via lifecycle policies (configure on your bucket).
  - Uses the workgroup-level cost controls as an additional safety net.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import TYPE_CHECKING, Any

import structlog

from mcp_enterprise_server.aws_credentials import AWSCredentialManager
from mcp_enterprise_server.guardrails import (
    QueryValidationError,
    audit_log,
    cap_result_size,
    check_rate_limit,
    redact_pii,
    validate_sql_query,
)

if TYPE_CHECKING:
    from mcp.server.fastmcp import Context, FastMCP
    from mcp.server.session import ServerSession

    from mcp_enterprise_server.config import AthenaConfig

logger = structlog.get_logger("athena_mcp")


# ---------------------------------------------------------------------------
# Athena Client Wrapper
# ---------------------------------------------------------------------------
class AthenaClient:
    """
    Managed Athena client with credential rotation, query lifecycle
    management, and guardrails enforcement.
    """

    def __init__(self, config: AthenaConfig):
        self._config = config
        self._cred_manager = AWSCredentialManager(
            region=config.region.value,
            role_arn=config.role_arn,
            session_name="MCP_Athena_Session",
            session_duration=config.session_duration_seconds,
        )

    def _get_client(self):
        return self._cred_manager.get_client("athena")

    # -- Start Query --
    async def start_query(
        self,
        query: str,
        database: str | None = None,
    ) -> str:
        """
        Start an Athena query execution and return the QueryExecutionId.

        The query is pre-validated by guardrails before submission.
        """
        effective_db = database or self._config.database

        # Validate database access
        if self._config.allowed_databases and effective_db not in self._config.allowed_databases:
            raise QueryValidationError(
                f"Database '{effective_db}' is not in the allowed list: {self._config.allowed_databases}"
            )

        # Validate SQL
        validate_sql_query(query, self._config.blocked_keywords, self._config.permission_level)

        def _start():
            client = self._get_client()
            response = client.start_query_execution(
                QueryString=query,
                QueryExecutionContext={
                    "Database": effective_db,
                    "Catalog": self._config.catalog,
                },
                ResultConfiguration={
                    "OutputLocation": self._config.output_bucket,
                },
                WorkGroup=self._config.workgroup,
            )
            return response["QueryExecutionId"]

        return await asyncio.to_thread(_start)

    # -- Poll Query Status --
    async def wait_for_query(
        self,
        query_execution_id: str,
        poll_interval: float = 1.0,
    ) -> dict[str, Any]:
        """
        Poll Athena until the query completes (SUCCEEDED, FAILED, CANCELLED).
        Enforces the configured timeout.
        """
        start_time = time.monotonic()
        timeout = self._config.query_timeout_seconds

        while True:
            elapsed = time.monotonic() - start_time
            if elapsed > timeout:
                # Cancel the query if timeout exceeded
                await self._cancel_query(query_execution_id)
                raise TimeoutError(
                    f"Athena query {query_execution_id} timed out after {timeout}s. Query was cancelled."
                )

            status = await self._get_query_status(query_execution_id)
            state = status["QueryExecution"]["Status"]["State"]

            if state == "SUCCEEDED":
                # Check data scanned for cost control
                stats = status["QueryExecution"].get("Statistics", {})
                bytes_scanned = stats.get("DataScannedInBytes", 0)
                if bytes_scanned > self._config.max_scan_bytes:
                    logger.warning(
                        "athena_high_data_scan",
                        query_id=query_execution_id,
                        bytes_scanned=bytes_scanned,
                        max_allowed=self._config.max_scan_bytes,
                    )

                return {
                    "state": state,
                    "query_execution_id": query_execution_id,
                    "bytes_scanned": bytes_scanned,
                    "execution_time_ms": stats.get("EngineExecutionTimeInMillis", 0),
                    "data_manifest_location": stats.get("DataManifestLocation"),
                }

            elif state in ("FAILED", "CANCELLED"):
                reason = status["QueryExecution"]["Status"].get("StateChangeReason", "Unknown")
                raise RuntimeError(f"Athena query {state}: {reason} (QueryExecutionId: {query_execution_id})")

            await asyncio.sleep(poll_interval)

    # -- Fetch Results --
    async def get_query_results(
        self,
        query_execution_id: str,
        max_rows: int = 1000,
    ) -> dict[str, Any]:
        """Fetch results of a completed Athena query."""

        def _fetch():
            client = self._get_client()
            paginator = client.get_paginator("get_query_results")

            all_rows = []
            columns = []
            first_page = True

            for page in paginator.paginate(
                QueryExecutionId=query_execution_id,
                PaginationConfig={"MaxItems": max_rows + 1},  # +1 for header
            ):
                result_set = page["ResultSet"]

                # Extract column metadata from first page
                if first_page and "ResultSetMetadata" in result_set:
                    columns = [
                        {
                            "name": col["Name"],
                            "type": col.get("Type", "unknown"),
                        }
                        for col in result_set["ResultSetMetadata"]["ColumnInfo"]
                    ]
                    first_page = False

                for row in result_set.get("Rows", []):
                    values = [datum.get("VarCharValue", None) for datum in row.get("Data", [])]
                    all_rows.append(values)

            # First row is typically the header in Athena results
            header = all_rows[0] if all_rows else []
            data_rows = all_rows[1 : max_rows + 1] if len(all_rows) > 1 else []

            # Convert to list of dicts
            col_names = [c["name"] for c in columns] if columns else header
            records = [dict(zip(col_names, row, strict=False)) for row in data_rows]

            return {
                "columns": columns,
                "row_count": len(records),
                "data": records,
            }

        return await asyncio.to_thread(_fetch)

    # -- Execute and Wait (convenience) --
    async def execute_query(
        self,
        query: str,
        database: str | None = None,
        max_rows: int = 1000,
    ) -> dict[str, Any]:
        """
        Execute an Athena query synchronously: start → poll → fetch results.
        """
        query_id = await self.start_query(query, database)
        status = await self.wait_for_query(query_id)
        results = await self.get_query_results(query_id, max_rows=max_rows)

        return {
            **status,
            **results,
        }

    # -- List Databases (Glue Catalogs) --
    async def list_databases(self) -> list[dict[str, str]]:
        """List available Glue databases, filtered by whitelist."""

        def _list():
            client = self._get_client()
            paginator = client.get_paginator("list_databases")
            databases = []
            for page in paginator.paginate(CatalogName=self._config.catalog):
                for db in page.get("DatabaseList", []):
                    db_name = db["Name"]
                    if not self._config.allowed_databases or db_name in self._config.allowed_databases:
                        databases.append(
                            {
                                "name": db_name,
                                "description": db.get("Description", ""),
                            }
                        )
            return databases

        return await asyncio.to_thread(_list)

    # -- List Tables in Database --
    async def list_tables_in_database(self, database: str | None = None) -> list[dict[str, str]]:
        """List tables in an Athena/Glue database."""
        effective_db = database or self._config.database

        if self._config.allowed_databases and effective_db not in self._config.allowed_databases:
            raise QueryValidationError(f"Database '{effective_db}' is not in the allowed list.")

        def _list():
            client = self._get_client()
            paginator = client.get_paginator("list_table_metadata")
            tables = []
            for page in paginator.paginate(
                CatalogName=self._config.catalog,
                DatabaseName=effective_db,
            ):
                for tbl in page.get("TableMetadataList", []):
                    tables.append(
                        {
                            "name": tbl["Name"],
                            "type": tbl.get("TableType", ""),
                            "columns": [{"name": c["Name"], "type": c.get("Type", "")} for c in tbl.get("Columns", [])],
                        }
                    )
            return tables

        return await asyncio.to_thread(_list)

    # -- Private helpers --
    async def _get_query_status(self, query_execution_id: str) -> dict:
        def _status():
            client = self._get_client()
            return client.get_query_execution(QueryExecutionId=query_execution_id)

        return await asyncio.to_thread(_status)

    async def _cancel_query(self, query_execution_id: str) -> None:
        def _cancel():
            client = self._get_client()
            client.stop_query_execution(QueryExecutionId=query_execution_id)
            logger.warning("athena_query_cancelled", query_id=query_execution_id)

        await asyncio.to_thread(_cancel)


# ---------------------------------------------------------------------------
# Register Athena tools on MCP server
# ---------------------------------------------------------------------------
def register_athena_tools(mcp_server: FastMCP, config: AthenaConfig) -> None:
    """
    Register all Athena MCP tools on the given FastMCP server.
    """
    client = AthenaClient(config)

    @mcp_server.tool(
        name="execute_athena_query",
        description=(
            "Execute a SQL query on Amazon Athena (serverless). "
            "Only SELECT/WITH queries allowed in read-only mode. "
            f"Workgroup: {config.workgroup}. "
            f"Default database: {config.database}."
        ),
    )
    async def tool_execute_athena_query(
        query: str,
        database: str | None = None,
        max_rows: int = 1000,
        ctx: Context[ServerSession, Any] = None,
    ) -> str:
        """
        Execute an Athena SQL query and return results.

        Args:
            query:    SQL query (only SELECT/WITH in read-only mode)
            database: Target Glue database (defaults to config.database)
            max_rows: Max rows to return (capped by server limit)
        """
        caller = (ctx.client_id or "unknown") if ctx else "system"
        start = time.monotonic()

        try:
            check_rate_limit(caller, "execute_athena_query")
            results = await client.execute_query(query, database, max_rows)
            response = json.dumps(
                {"status": "success", **results},
                indent=2,
                default=str,
            )
            response = redact_pii(response)
            response = cap_result_size(response)
            duration = (time.monotonic() - start) * 1000
            audit_log(
                "execute_athena_query",
                caller,
                {"query": query[:200], "database": database or config.database},
                f"{results.get('row_count', 0)} rows, {results.get('bytes_scanned', 0)} bytes scanned",
                True,
                duration,
            )
            return response
        except Exception as e:
            duration = (time.monotonic() - start) * 1000
            audit_log("execute_athena_query", caller, {"query": query[:200]}, "", False, duration, error=str(e))
            raise

    @mcp_server.tool(
        name="list_athena_databases",
        description="List available Glue databases for Athena queries.",
    )
    async def tool_list_athena_databases(
        ctx: Context[ServerSession, Any] = None,
    ) -> str:
        """List accessible Athena/Glue databases."""
        caller = (ctx.client_id or "unknown") if ctx else "system"
        start = time.monotonic()

        try:
            check_rate_limit(caller, "list_athena_databases")
            databases = await client.list_databases()
            response = json.dumps(
                {"status": "success", "databases": databases, "count": len(databases)},
                indent=2,
            )
            duration = (time.monotonic() - start) * 1000
            audit_log("list_athena_databases", caller, {}, f"{len(databases)} databases", True, duration)
            return response
        except Exception as e:
            duration = (time.monotonic() - start) * 1000
            audit_log("list_athena_databases", caller, {}, "", False, duration, error=str(e))
            raise

    @mcp_server.tool(
        name="list_athena_tables",
        description="List tables in an Athena/Glue database with column metadata.",
    )
    async def tool_list_athena_tables(
        database: str | None = None,
        ctx: Context[ServerSession, Any] = None,
    ) -> str:
        """List tables in a Glue database."""
        caller = (ctx.client_id or "unknown") if ctx else "system"
        start = time.monotonic()
        effective_db = database or config.database

        try:
            check_rate_limit(caller, "list_athena_tables")
            tables = await client.list_tables_in_database(effective_db)
            response = json.dumps(
                {"status": "success", "database": effective_db, "tables": tables, "count": len(tables)},
                indent=2,
            )
            duration = (time.monotonic() - start) * 1000
            audit_log("list_athena_tables", caller, {"database": effective_db}, f"{len(tables)} tables", True, duration)
            return response
        except Exception as e:
            duration = (time.monotonic() - start) * 1000
            audit_log("list_athena_tables", caller, {"database": effective_db}, "", False, duration, error=str(e))
            raise

    @mcp_server.tool(
        name="start_athena_query",
        description=(
            "Start an Athena query without waiting for results. Returns a QueryExecutionId to check status later."
        ),
    )
    async def tool_start_athena_query(
        query: str,
        database: str | None = None,
        ctx: Context[ServerSession, Any] = None,
    ) -> str:
        """Start an async Athena query. Use check_athena_query to get results."""
        caller = (ctx.client_id or "unknown") if ctx else "system"
        start = time.monotonic()

        try:
            check_rate_limit(caller, "start_athena_query")
            query_id = await client.start_query(query, database)
            response = json.dumps(
                {
                    "status": "started",
                    "query_execution_id": query_id,
                    "message": "Query started. Use check_athena_query tool to poll for results.",
                },
                indent=2,
            )
            duration = (time.monotonic() - start) * 1000
            audit_log("start_athena_query", caller, {"query": query[:200]}, f"id={query_id}", True, duration)
            return response
        except Exception as e:
            duration = (time.monotonic() - start) * 1000
            audit_log("start_athena_query", caller, {"query": query[:200]}, "", False, duration, error=str(e))
            raise

    @mcp_server.tool(
        name="check_athena_query",
        description="Check the status of an async Athena query and fetch results if complete.",
    )
    async def tool_check_athena_query(
        query_execution_id: str,
        max_rows: int = 1000,
        ctx: Context[ServerSession, Any] = None,
    ) -> str:
        """Check status and fetch results for a previously started Athena query."""
        caller = (ctx.client_id or "unknown") if ctx else "system"
        start = time.monotonic()

        try:
            check_rate_limit(caller, "check_athena_query")
            status_info = await client._get_query_status(query_execution_id)
            state = status_info["QueryExecution"]["Status"]["State"]

            result: dict[str, Any] = {
                "query_execution_id": query_execution_id,
                "state": state,
            }

            if state == "SUCCEEDED":
                data = await client.get_query_results(query_execution_id, max_rows)
                result.update(data)
                result["status"] = "success"
            elif state in ("FAILED", "CANCELLED"):
                reason = status_info["QueryExecution"]["Status"].get("StateChangeReason", "Unknown")
                result["status"] = "error"
                result["error"] = reason
            else:
                result["status"] = "running"
                result["message"] = "Query is still running. Check again in a few seconds."

            response = json.dumps(result, indent=2, default=str)
            response = redact_pii(response)
            response = cap_result_size(response)
            duration = (time.monotonic() - start) * 1000
            audit_log("check_athena_query", caller, {"query_id": query_execution_id}, state, True, duration)
            return response
        except Exception as e:
            duration = (time.monotonic() - start) * 1000
            audit_log("check_athena_query", caller, {"query_id": query_execution_id}, "", False, duration, error=str(e))
            raise

    logger.info("athena_tools_registered", tool_count=5)
