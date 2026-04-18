"""
Athena AWS MCP Tools
====================
Generates tools for an AWSSource containing Athena capabilities.
"""

import asyncio
import json
import re
import time
from typing import Any

from centrag.guardrails.pii import redact_pii
from centrag.mcp.source_registry import AWSSource
from centrag.mcp.tool_registry import MCPTool, ToolAnnotations, ToolManifest
from centrag.utils.logger import get_logger

logger = get_logger("mcp.aws.athena")


# ---------------------------------------------------------------------------
# SQL Validation Guardrails
# ---------------------------------------------------------------------------
_DANGEROUS_PATTERNS: list[re.Pattern] = [
    re.compile(r"--"),
    re.compile(r"/\*"),
    re.compile(r";\s*\w"),
    re.compile(r"'\s*OR\s+'", re.IGNORECASE),
    re.compile(r"UNION\s+SELECT", re.IGNORECASE),
    re.compile(r"xp_\w+", re.IGNORECASE),
]


class QueryValidationError(Exception):
    pass


def validate_sql_query(query: str, blocked_keywords: list[str], read_only: bool) -> str:
    upper_query = query.upper().strip()

    # Read-only mode: only SELECT and WITH (CTEs) are permitted
    if read_only:
        stripped_after_lstrip = upper_query.lstrip("( ")
        split_result = stripped_after_lstrip.split()
        first_keyword = split_result[0] if split_result else ""
        if first_keyword not in ("SELECT", "WITH", "EXPLAIN", "DESCRIBE", "SHOW"):
            raise QueryValidationError(f"Read-only mode only allows SELECT/WITH/EXPLAIN queries. Got: {first_keyword}")

    for keyword in blocked_keywords:
        pattern = re.compile(rf"\b{keyword}\b", re.IGNORECASE)
        if pattern.search(upper_query):
            raise QueryValidationError(f"Blocked keyword '{keyword}' detected.")

    for pattern in _DANGEROUS_PATTERNS:
        if pattern.search(query):
            raise QueryValidationError(f"Potentially dangerous SQL pattern detected: {pattern.pattern}")

    return query.strip()


def cap_result_size(data: str, max_bytes: int = 5 * 1024 * 1024) -> str:
    encoded = data.encode("utf-8")
    if len(encoded) > max_bytes:
        truncated = encoded[:max_bytes].decode("utf-8", errors="ignore")
        return truncated + f"\n\n[TRUNCATED: Result exceeded {max_bytes} bytes]"
    return data


def generate_athena_tools(source: AWSSource) -> list[MCPTool]:
    """Generate all Athena interactive tools bound to the specific source."""

    options = source._config.options
    database = options.get("database", "default")
    catalog = options.get("catalog", "AwsDataCatalog")
    workgroup = options.get("workgroup", "primary")
    output_bucket = options.get("output_bucket")
    allowed_databases = options.get("allowed_databases", [])
    blocked_keywords = options.get("blocked_keywords", ["DROP", "DELETE", "TRUNCATE", "UPDATE", "INSERT"])
    query_timeout_seconds = options.get("query_timeout_seconds", 60)
    read_only = options.get("read_only", True)

    def _get_client():
        return source.cred_manager.get_client("athena")

    async def _start_query(query: str, target_db: str | None = None) -> str:
        effective_db = target_db or database
        if allowed_databases and effective_db not in allowed_databases:
            raise QueryValidationError(f"Database '{effective_db}' is not in the allowed list: {allowed_databases}")

        validate_sql_query(query, blocked_keywords, read_only)

        def _start():
            client = _get_client()
            kwargs = {
                "QueryString": query,
                "QueryExecutionContext": {"Database": effective_db, "Catalog": catalog},
                "WorkGroup": workgroup,
            }
            if output_bucket:
                kwargs["ResultConfiguration"] = {"OutputLocation": output_bucket}
            response = client.start_query_execution(**kwargs)
            return response["QueryExecutionId"]

        return await asyncio.to_thread(_start)

    async def _get_query_status(query_execution_id: str) -> dict:
        def _status():
            return _get_client().get_query_execution(QueryExecutionId=query_execution_id)

        return await asyncio.to_thread(_status)

    async def _cancel_query(query_execution_id: str) -> None:
        def _cancel():
            _get_client().stop_query_execution(QueryExecutionId=query_execution_id)

        await asyncio.to_thread(_cancel)

    async def _wait_for_query(query_execution_id: str, poll_interval: float = 1.0) -> dict[str, Any]:
        start_time = time.monotonic()
        while True:
            if time.monotonic() - start_time > query_timeout_seconds:
                await _cancel_query(query_execution_id)
                raise TimeoutError(f"Athena query {query_execution_id} timed out after {query_timeout_seconds}s.")

            status = await _get_query_status(query_execution_id)
            state = status["QueryExecution"]["Status"]["State"]

            if state == "SUCCEEDED":
                stats = status["QueryExecution"].get("Statistics", {})
                return {
                    "state": state,
                    "query_execution_id": query_execution_id,
                    "bytes_scanned": stats.get("DataScannedInBytes", 0),
                    "execution_time_ms": stats.get("EngineExecutionTimeInMillis", 0),
                }
            elif state in ("FAILED", "CANCELLED"):
                reason = status["QueryExecution"]["Status"].get("StateChangeReason", "Unknown")
                raise RuntimeError(f"Athena query {state}: {reason}")

            await asyncio.sleep(poll_interval)

    async def _get_query_results(query_execution_id: str, max_rows: int = 1000) -> dict[str, Any]:
        def _fetch():
            client = _get_client()
            paginator = client.get_paginator("get_query_results")
            all_rows = []
            columns = []
            first_page = True

            for page in paginator.paginate(
                QueryExecutionId=query_execution_id, PaginationConfig={"MaxItems": max_rows + 1}
            ):
                result_set = page["ResultSet"]
                if first_page and "ResultSetMetadata" in result_set:
                    columns = [
                        {"name": col["Name"], "type": col.get("Type", "unknown")}
                        for col in result_set["ResultSetMetadata"]["ColumnInfo"]
                    ]
                    first_page = False
                for row in result_set.get("Rows", []):
                    values = [datum.get("VarCharValue", None) for datum in row.get("Data", [])]
                    all_rows.append(values)

            header = all_rows[0] if all_rows else []
            data_rows = all_rows[1 : max_rows + 1] if len(all_rows) > 1 else []
            col_names = [c["name"] for c in columns] if columns else header
            records = [dict(zip(col_names, row, strict=False)) for row in data_rows]

            return {"columns": columns, "row_count": len(records), "data": records}

        return await asyncio.to_thread(_fetch)

    # ---------- Handler Functions ---------- #

    async def execute_athena_query(**kwargs) -> str:
        query = kwargs.get("query", "")
        target_db = kwargs.get("database")
        max_rows = kwargs.get("max_rows", 1000)

        try:
            query_id = await _start_query(query, target_db)
            status = await _wait_for_query(query_id)
            results = await _get_query_results(query_id, max_rows=max_rows)

            response = json.dumps({"status": "success", **status, **results}, indent=2, default=str)
            return cap_result_size(redact_pii(response))
        except Exception as e:
            return f"Athena Error: {e}"

    async def list_athena_databases(**kwargs) -> str:
        def _list():
            client = _get_client()
            paginator = client.get_paginator("list_databases")
            databases = []
            for page in paginator.paginate(CatalogName=catalog):
                for db in page.get("DatabaseList", []):
                    db_name = db["Name"]
                    if not allowed_databases or db_name in allowed_databases:
                        databases.append(
                            {
                                "name": db_name,
                                "description": db.get("Description", ""),
                            }
                        )
            return databases

        try:
            dbs = await asyncio.to_thread(_list)
            result = json.dumps({"status": "success", "databases": dbs, "count": len(dbs)}, indent=2)
            return cap_result_size(redact_pii(result, enable=True))
        except Exception as e:
            return f"Athena Error: {e}"

    async def list_athena_tables(**kwargs) -> str:
        target_db = kwargs.get("database")
        effective_db = target_db or database
        if allowed_databases and effective_db not in allowed_databases:
            return f"Athena Error: Database '{effective_db}' is not in the allowed list."

        def _list():
            client = _get_client()
            paginator = client.get_paginator("list_table_metadata")
            tables = []
            for page in paginator.paginate(CatalogName=catalog, DatabaseName=effective_db):
                for tbl in page.get("TableMetadataList", []):
                    tables.append(
                        {
                            "name": tbl["Name"],
                            "type": tbl.get("TableType", ""),
                            "columns": [{"name": c["Name"], "type": c.get("Type", "")} for c in tbl.get("Columns", [])],
                        }
                    )
            return tables

        try:
            tbls = await asyncio.to_thread(_list)
            result = json.dumps(
                {"status": "success", "database": effective_db, "tables": tbls, "count": len(tbls)}, indent=2
            )
            return cap_result_size(redact_pii(result, enable=True))
        except Exception as e:
            return f"Athena Error: {e}"

    async def get_athena_workgroup(**kwargs) -> str:
        name = kwargs.get("name")
        if not name:
            raise ValueError("work group name is required")

        def _get():
            return _get_client().get_work_group(WorkGroup=name)

        try:
            wg = await asyncio.to_thread(_get)
            result = json.dumps({"status": "success", "work_group": wg.get("WorkGroup", {})}, indent=2, default=str)
            return cap_result_size(redact_pii(result, enable=True))
        except Exception as e:
            return f"Athena Error: {e}"

    async def list_athena_workgroups(**kwargs) -> str:
        max_results = kwargs.get("max_results", 50)

        def _list():
            client = _get_client()
            paginator = client.get_paginator("list_work_groups")
            workgroups = []
            for page in paginator.paginate(PaginationConfig={"MaxItems": max_results}):
                workgroups.extend(page.get("WorkGroups", []))
            return workgroups

        try:
            wgs = await asyncio.to_thread(_list)
            result = json.dumps({"status": "success", "workgroups": wgs, "count": len(wgs)}, indent=2, default=str)
            return cap_result_size(redact_pii(result, enable=True))
        except Exception as e:
            return f"Athena Error: {e}"

    target_source_name = source.name
    ans = ToolAnnotations.read_only() if read_only else ToolAnnotations.destructive()

    return [
        MCPTool(
            manifest=ToolManifest(
                name=f"{target_source_name}.execute_athena_query",
                description=f"Execute an SQL query synchronously on Athena using source {target_source_name}.",
                source_name=target_source_name,
                annotations=ans,
                parameters=[
                    {"name": "query", "type": "string", "description": "SQL query to execute."},
                    {
                        "name": "database",
                        "type": "string",
                        "description": "Target database (optional).",
                        "required": False,
                    },
                    {
                        "name": "max_rows",
                        "type": "integer",
                        "description": "Max rows to return (default 1000).",
                        "required": False,
                    },
                ],
            ),
            handler=execute_athena_query,
        ),
        MCPTool(
            manifest=ToolManifest(
                name=f"{target_source_name}.list_athena_databases",
                description=f"List available Glue databases for Athena queries on source {target_source_name}.",
                source_name=target_source_name,
                annotations=ToolAnnotations.read_only(),
                parameters=[],
            ),
            handler=list_athena_databases,
        ),
        MCPTool(
            manifest=ToolManifest(
                name=f"{target_source_name}.list_athena_tables",
                description=f"List tables in an Athena/Glue database on source {target_source_name}.",
                source_name=target_source_name,
                annotations=ToolAnnotations.read_only(),
                parameters=[
                    {
                        "name": "database",
                        "type": "string",
                        "description": "Target database (optional).",
                        "required": False,
                    },
                ],
            ),
            handler=list_athena_tables,
        ),
        MCPTool(
            manifest=ToolManifest(
                name=f"{target_source_name}.list_athena_workgroups",
                description=f"List all available Athena workgroups on source {target_source_name}.",
                source_name=target_source_name,
                annotations=ToolAnnotations.read_only(),
                parameters=[
                    {
                        "name": "max_results",
                        "type": "integer",
                        "description": "Max results to return (default 50).",
                        "required": False,
                    },
                ],
            ),
            handler=list_athena_workgroups,
        ),
        MCPTool(
            manifest=ToolManifest(
                name=f"{target_source_name}.get_athena_workgroup",
                description=f"Get information about a specific Athena workgroup on source {target_source_name}.",
                source_name=target_source_name,
                annotations=ToolAnnotations.read_only(),
                parameters=[
                    {"name": "name", "type": "string", "description": "The name of the workgroup."},
                ],
            ),
            handler=get_athena_workgroup,
        ),
    ]
