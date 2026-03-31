"""
AWS DynamoDB MCP Connection
============================
MCP tools for interacting with Amazon DynamoDB with enterprise guardrails.

Architecture:
  ┌─────────────┐    ┌────────────┐    ┌──────────────┐    ┌──────────────┐
  │ MCP Client  │───▶│ MCP Server │───▶│  Guardrails  │───▶│  DynamoDB    │
  │ (AI Agent)  │    │ (FastMCP)  │    │  (validate)  │    │ (via boto3)  │
  └─────────────┘    └────────────┘    └──────────────┘    └──────────────┘

Security layers:
  1. IAM Role-Based Access    — STS AssumeRole with short-lived creds
  2. Table Whitelisting       — Only approved tables are accessible
  3. Permission Level Control — READ_ONLY blocks PutItem, DeleteItem, etc.
  4. Item Count Limits        — Hard cap on scan/query result count
  5. PII Redaction            — Strips PII from returned data
  6. Rate Limiting + Audit    — Per-caller throttling and invocation logging

Key Design Decisions:
  - Uses boto3 high-level resource API for scan/query (simpler pagination)
  - Uses low-level client API for describe_table and list_tables
  - All operations are async-compatible via asyncio.to_thread
"""

from __future__ import annotations

import json
import time
import asyncio
from typing import Any, Optional
from decimal import Decimal

import boto3
import structlog

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession

from mcp_enterprise_server.config import DynamoDBConfig, PermissionLevel
from mcp_enterprise_server.aws_credentials import AWSCredentialManager
from mcp_enterprise_server.guardrails import (
    validate_table_access,
    check_rate_limit,
    redact_pii,
    cap_result_size,
    audit_log,
)

logger = structlog.get_logger("dynamodb_mcp")


# ---------------------------------------------------------------------------
# DynamoDB JSON Encoder (handles Decimal types from DynamoDB)
# ---------------------------------------------------------------------------
class DynamoDBEncoder(json.JSONEncoder):
    """Custom JSON encoder for DynamoDB items (Decimal → float/int)."""
    def default(self, obj):
        if isinstance(obj, Decimal):
            if obj % 1 == 0:
                return int(obj)
            return float(obj)
        if isinstance(obj, set):
            return list(obj)
        if isinstance(obj, bytes):
            return obj.decode("utf-8", errors="replace")
        return super().default(obj)


# ---------------------------------------------------------------------------
# DynamoDB Client Wrapper
# ---------------------------------------------------------------------------
class DynamoDBClient:
    """
    Managed DynamoDB client with credential rotation and guardrails.
    """

    def __init__(self, config: DynamoDBConfig):
        self._config = config
        self._cred_manager = AWSCredentialManager(
            region=config.region.value,
            role_arn=config.role_arn,
            session_name="MCP_DynamoDB_Session",
            session_duration=config.session_duration_seconds,
            endpoint_url=config.endpoint_url,
        )

    def _get_client(self):
        return self._cred_manager.get_client("dynamodb")

    def _get_resource(self):
        return self._cred_manager.get_resource("dynamodb")

    # -- List Tables --
    async def list_tables(self) -> list[dict[str, Any]]:
        """List all DynamoDB tables, filtered by whitelist if configured."""
        def _list():
            client = self._get_client()
            paginator = client.get_paginator("list_tables")
            all_tables = []
            for page in paginator.paginate():
                all_tables.extend(page.get("TableNames", []))

            # Apply whitelist filter
            if self._config.allowed_tables:
                all_tables = [
                    t for t in all_tables if t in self._config.allowed_tables
                ]

            return [{"table_name": t} for t in sorted(all_tables)]

        return await asyncio.to_thread(_list)

    # -- Describe Table --
    async def describe_table(self, table_name: str) -> dict[str, Any]:
        """Get table metadata including key schema, provisioned throughput, etc."""
        validate_table_access(table_name, self._config.allowed_tables)

        def _describe():
            client = self._get_client()
            response = client.describe_table(TableName=table_name)
            table = response["Table"]
            return {
                "table_name": table["TableName"],
                "table_status": table["TableStatus"],
                "key_schema": table["KeySchema"],
                "attribute_definitions": table["AttributeDefinitions"],
                "item_count": table.get("ItemCount", 0),
                "table_size_bytes": table.get("TableSizeBytes", 0),
                "creation_date": table.get("CreationDateTime", "").isoformat()
                if table.get("CreationDateTime") else None,
                "billing_mode": table.get("BillingModeSummary", {}).get(
                    "BillingMode", "PROVISIONED"
                ),
                "global_secondary_indexes": [
                    {
                        "index_name": gsi["IndexName"],
                        "key_schema": gsi["KeySchema"],
                        "projection": gsi["Projection"],
                    }
                    for gsi in table.get("GlobalSecondaryIndexes", [])
                ],
            }

        return await asyncio.to_thread(_describe)

    # -- Query Table --
    async def query_table(
        self,
        table_name: str,
        key_condition: str,
        expression_values: Optional[dict[str, Any]] = None,
        expression_names: Optional[dict[str, str]] = None,
        filter_expression: Optional[str] = None,
        index_name: Optional[str] = None,
        max_items: Optional[int] = None,
        scan_forward: bool = True,
    ) -> list[dict[str, Any]]:
        """
        Query a DynamoDB table using key condition expressions.

        Args:
            table_name:          Target table
            key_condition:       Key condition expression (e.g., "pk = :pk_val")
            expression_values:   Expression attribute values ({":pk_val": {"S": "123"}})
            expression_names:    Expression attribute names ({"#status": "status"})
            filter_expression:   Optional filter expression
            index_name:          Optional GSI/LSI name
            max_items:           Max items to return (capped by config)
            scan_forward:        Sort direction (True = ascending)
        """
        validate_table_access(table_name, self._config.allowed_tables)
        effective_limit = min(
            max_items or self._config.max_items_per_scan,
            self._config.max_items_per_scan,
        )

        def _query():
            resource = self._get_resource()
            table = resource.Table(table_name)

            query_kwargs: dict[str, Any] = {
                "KeyConditionExpression": key_condition,
                "Limit": effective_limit,
                "ScanIndexForward": scan_forward,
            }
            if expression_values:
                query_kwargs["ExpressionAttributeValues"] = expression_values
            if expression_names:
                query_kwargs["ExpressionAttributeNames"] = expression_names
            if filter_expression:
                query_kwargs["FilterExpression"] = filter_expression
            if index_name:
                query_kwargs["IndexName"] = index_name

            response = table.query(**query_kwargs)
            return response.get("Items", [])

        return await asyncio.to_thread(_query)

    # -- Scan Table --
    async def scan_table(
        self,
        table_name: str,
        filter_expression: Optional[str] = None,
        expression_values: Optional[dict[str, Any]] = None,
        expression_names: Optional[dict[str, str]] = None,
        max_items: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        """
        Scan a DynamoDB table with optional filter.
        Use queries over scans when possible — scans read the entire table.
        """
        validate_table_access(table_name, self._config.allowed_tables)
        effective_limit = min(
            max_items or self._config.max_items_per_scan,
            self._config.max_items_per_scan,
        )

        def _scan():
            resource = self._get_resource()
            table = resource.Table(table_name)

            scan_kwargs: dict[str, Any] = {"Limit": effective_limit}
            if filter_expression:
                scan_kwargs["FilterExpression"] = filter_expression
            if expression_values:
                scan_kwargs["ExpressionAttributeValues"] = expression_values
            if expression_names:
                scan_kwargs["ExpressionAttributeNames"] = expression_names

            response = table.scan(**scan_kwargs)
            return response.get("Items", [])

        return await asyncio.to_thread(_scan)

    # -- Put Item (write, requires READ_WRITE or ADMIN) --
    async def put_item(
        self,
        table_name: str,
        item: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Put an item into a DynamoDB table.
        Requires READ_WRITE or ADMIN permission level.
        """
        if self._config.permission_level == PermissionLevel.READ_ONLY:
            raise PermissionError(
                "Write operations are not allowed in READ_ONLY mode. "
                "Contact your administrator to upgrade permissions."
            )

        validate_table_access(table_name, self._config.allowed_tables)

        def _put():
            resource = self._get_resource()
            table = resource.Table(table_name)
            table.put_item(Item=item)
            return {"status": "success", "table": table_name}

        return await asyncio.to_thread(_put)

    # -- Get Item --
    async def get_item(
        self,
        table_name: str,
        key: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        """Get a single item by its primary key."""
        validate_table_access(table_name, self._config.allowed_tables)

        def _get():
            resource = self._get_resource()
            table = resource.Table(table_name)
            response = table.get_item(Key=key)
            return response.get("Item")

        return await asyncio.to_thread(_get)


# ---------------------------------------------------------------------------
# Register DynamoDB tools on MCP server
# ---------------------------------------------------------------------------
def register_dynamodb_tools(mcp_server: FastMCP, config: DynamoDBConfig) -> None:
    """
    Register all DynamoDB MCP tools on the given FastMCP server.
    """
    client = DynamoDBClient(config)

    @mcp_server.tool(
        name="list_dynamodb_tables",
        description=(
            "List all accessible DynamoDB tables. "
            + (f"Whitelisted: {config.allowed_tables}" if config.allowed_tables
               else "All tables accessible.")
        ),
    )
    async def tool_list_dynamodb_tables(
        ctx: Context[ServerSession, Any] = None,
    ) -> str:
        """List DynamoDB tables with whitelist filtering."""
        caller = (ctx.client_id or "unknown") if ctx else "system"
        start = time.monotonic()

        try:
            check_rate_limit(caller, "list_dynamodb_tables")
            tables = await client.list_tables()
            response = json.dumps(
                {"status": "success", "tables": tables, "count": len(tables)},
                cls=DynamoDBEncoder, indent=2,
            )
            response = redact_pii(response)
            duration = (time.monotonic() - start) * 1000
            audit_log("list_dynamodb_tables", caller, {}, f"{len(tables)} tables", True, duration)
            return response
        except Exception as e:
            duration = (time.monotonic() - start) * 1000
            audit_log("list_dynamodb_tables", caller, {}, "", False, duration, error=str(e))
            raise

    @mcp_server.tool(
        name="describe_dynamodb_table",
        description="Get metadata for a DynamoDB table: key schema, indexes, billing, item count.",
    )
    async def tool_describe_dynamodb_table(
        table_name: str,
        ctx: Context[ServerSession, Any] = None,
    ) -> str:
        """Describe a DynamoDB table."""
        caller = (ctx.client_id or "unknown") if ctx else "system"
        start = time.monotonic()

        try:
            check_rate_limit(caller, "describe_dynamodb_table")
            metadata = await client.describe_table(table_name)
            response = json.dumps(
                {"status": "success", **metadata},
                cls=DynamoDBEncoder, indent=2,
            )
            duration = (time.monotonic() - start) * 1000
            audit_log("describe_dynamodb_table", caller, {"table": table_name}, "ok", True, duration)
            return response
        except Exception as e:
            duration = (time.monotonic() - start) * 1000
            audit_log("describe_dynamodb_table", caller, {"table": table_name}, "", False, duration, error=str(e))
            raise

    @mcp_server.tool(
        name="query_dynamodb",
        description=(
            "Query a DynamoDB table using key conditions. "
            "Prefer this over Scan for targeted lookups. "
            f"Max {config.max_items_per_scan} items per query."
        ),
    )
    async def tool_query_dynamodb(
        table_name: str,
        key_condition: str,
        expression_values: Optional[str] = None,
        expression_names: Optional[str] = None,
        filter_expression: Optional[str] = None,
        index_name: Optional[str] = None,
        max_items: int = 100,
        ctx: Context[ServerSession, Any] = None,
    ) -> str:
        """Query DynamoDB with key conditions and optional filters."""
        caller = (ctx.client_id or "unknown") if ctx else "system"
        start = time.monotonic()

        try:
            check_rate_limit(caller, "query_dynamodb")
            ev = json.loads(expression_values) if expression_values else None
            en = json.loads(expression_names) if expression_names else None

            items = await client.query_table(
                table_name=table_name,
                key_condition=key_condition,
                expression_values=ev,
                expression_names=en,
                filter_expression=filter_expression,
                index_name=index_name,
                max_items=max_items,
            )
            response = json.dumps(
                {"status": "success", "table": table_name, "item_count": len(items), "items": items},
                cls=DynamoDBEncoder, indent=2,
            )
            response = redact_pii(response)
            response = cap_result_size(response)
            duration = (time.monotonic() - start) * 1000
            audit_log("query_dynamodb", caller, {"table": table_name, "key_condition": key_condition}, f"{len(items)} items", True, duration)
            return response
        except Exception as e:
            duration = (time.monotonic() - start) * 1000
            audit_log("query_dynamodb", caller, {"table": table_name}, "", False, duration, error=str(e))
            raise

    @mcp_server.tool(
        name="scan_dynamodb",
        description=(
            "Scan a DynamoDB table (reads entire table — use Query when possible). "
            f"Max {config.max_items_per_scan} items."
        ),
    )
    async def tool_scan_dynamodb(
        table_name: str,
        filter_expression: Optional[str] = None,
        expression_values: Optional[str] = None,
        expression_names: Optional[str] = None,
        max_items: int = 100,
        ctx: Context[ServerSession, Any] = None,
    ) -> str:
        """Scan DynamoDB table with optional filter expression."""
        caller = (ctx.client_id or "unknown") if ctx else "system"
        start = time.monotonic()

        try:
            check_rate_limit(caller, "scan_dynamodb")
            ev = json.loads(expression_values) if expression_values else None
            en = json.loads(expression_names) if expression_names else None

            items = await client.scan_table(
                table_name=table_name,
                filter_expression=filter_expression,
                expression_values=ev,
                expression_names=en,
                max_items=max_items,
            )
            response = json.dumps(
                {"status": "success", "table": table_name, "item_count": len(items), "items": items},
                cls=DynamoDBEncoder, indent=2,
            )
            response = redact_pii(response)
            response = cap_result_size(response)
            duration = (time.monotonic() - start) * 1000
            audit_log("scan_dynamodb", caller, {"table": table_name}, f"{len(items)} items", True, duration)
            return response
        except Exception as e:
            duration = (time.monotonic() - start) * 1000
            audit_log("scan_dynamodb", caller, {"table": table_name}, "", False, duration, error=str(e))
            raise

    @mcp_server.tool(
        name="get_dynamodb_item",
        description="Get a single item from a DynamoDB table by primary key.",
    )
    async def tool_get_dynamodb_item(
        table_name: str,
        key: str,
        ctx: Context[ServerSession, Any] = None,
    ) -> str:
        """Get a single item by key. Key should be JSON string, e.g. '{"pk": "user_123"}'."""
        caller = (ctx.client_id or "unknown") if ctx else "system"
        start = time.monotonic()

        try:
            check_rate_limit(caller, "get_dynamodb_item")
            key_dict = json.loads(key)
            item = await client.get_item(table_name, key_dict)
            response = json.dumps(
                {"status": "success" if item else "not_found", "table": table_name, "item": item},
                cls=DynamoDBEncoder, indent=2,
            )
            response = redact_pii(response)
            duration = (time.monotonic() - start) * 1000
            audit_log("get_dynamodb_item", caller, {"table": table_name, "key": key}, "ok", True, duration)
            return response
        except Exception as e:
            duration = (time.monotonic() - start) * 1000
            audit_log("get_dynamodb_item", caller, {"table": table_name}, "", False, duration, error=str(e))
            raise

    @mcp_server.tool(
        name="put_dynamodb_item",
        description=(
            "Write an item to a DynamoDB table. "
            "Requires READ_WRITE permission level. "
            "Item should be a JSON string."
        ),
    )
    async def tool_put_dynamodb_item(
        table_name: str,
        item: str,
        ctx: Context[ServerSession, Any] = None,
    ) -> str:
        """Put an item into DynamoDB. Item must be JSON string."""
        caller = (ctx.client_id or "unknown") if ctx else "system"
        start = time.monotonic()

        try:
            check_rate_limit(caller, "put_dynamodb_item")
            item_dict = json.loads(item)
            result = await client.put_item(table_name, item_dict)
            response = json.dumps(result, indent=2)
            duration = (time.monotonic() - start) * 1000
            audit_log("put_dynamodb_item", caller, {"table": table_name}, "item_written", True, duration)
            return response
        except Exception as e:
            duration = (time.monotonic() - start) * 1000
            audit_log("put_dynamodb_item", caller, {"table": table_name}, "", False, duration, error=str(e))
            raise

    logger.info("dynamodb_tools_registered", tool_count=6)
