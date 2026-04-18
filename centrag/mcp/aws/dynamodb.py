"""
DynamoDB AWS MCP Tools
======================
Generates tools for an AWSSource containing DynamoDB capabilities.
"""

import asyncio
import json

from boto3.dynamodb.types import TypeDeserializer, TypeSerializer

from centrag.guardrails.pii import redact_pii
from centrag.mcp.source_registry import AWSSource
from centrag.mcp.tool_registry import MCPTool, ToolAnnotations, ToolManifest
from centrag.utils.logger import get_logger

logger = get_logger("mcp.aws.dynamodb")


def cap_result_size(data: str, max_bytes: int = 5 * 1024 * 1024) -> str:
    encoded = data.encode("utf-8")
    if len(encoded) > max_bytes:
        marker = f"\n\n[TRUNCATED: Result exceeded {max_bytes} bytes]"
        marker_bytes = marker.encode("utf-8")
        cutoff = max(0, max_bytes - len(marker_bytes))
        truncated = encoded[:cutoff].decode("utf-8", errors="ignore")
        return truncated + marker
    return data


def generate_dynamodb_tools(source: AWSSource) -> list[MCPTool]:
    """Generate all DynamoDB interactive tools bounds to the specific source."""

    options = source._config.options
    allowed_tables = options.get("allowed_tables", [])
    max_scan_items = options.get("max_scan_items", 100)

    serializer = TypeSerializer()
    deserializer = TypeDeserializer()

    def _validate_table(table: str) -> None:
        if allowed_tables and table not in allowed_tables:
            logger.warning("unauthorized_table_access", table=table, allowed_tables=allowed_tables)
            raise PermissionError("Access to requested table is not permitted")

    def _get_client():
        return source.cred_manager.get_client("dynamodb")

    async def list_dynamodb_tables(**kwargs) -> str:
        def _list():
            client = _get_client()
            paginator = client.get_paginator("list_tables")
            all_tables = []
            for page in paginator.paginate():
                for tb in page.get("TableNames", []):
                    if allowed_tables and tb not in allowed_tables:
                        continue
                    all_tables.append(tb)
            return sorted(all_tables)

        try:
            tables = await asyncio.to_thread(_list)
            return json.dumps({"status": "success", "tables": tables}, default=str, indent=2)
        except Exception as e:
            logger.exception("DynamoDB error during list_dynamodb_tables", error=str(e))
            return "Failed to query DynamoDB"

    async def query_dynamodb(**kwargs) -> str:
        table_name = kwargs.get("table_name", "")
        key_condition = kwargs.get("key_condition_expression", "")
        expr_attr_values = kwargs.get("expression_attribute_values", {})

        try:
            _validate_table(table_name)

            def _query():
                client = _get_client()
                serialized_values = {k: serializer.serialize(v) for k, v in expr_attr_values.items()}
                response = client.query(
                    TableName=table_name,
                    KeyConditionExpression=key_condition,
                    ExpressionAttributeValues=serialized_values,
                    Limit=max_scan_items,
                )
                items = [
                    {k: deserializer.deserialize(v) for k, v in item.items()} for item in response.get("Items", [])
                ]
                return {"items": items, "last_evaluated_key": response.get("LastEvaluatedKey")}

            query_result = await asyncio.to_thread(_query)
            result = json.dumps({"status": "success", "items": query_result["items"], "last_evaluated_key": query_result.get("last_evaluated_key")}, default=str, indent=2)
            return cap_result_size(redact_pii(result, enable=True))
        except Exception as e:
            logger.exception("DynamoDB error during query_dynamodb", error=str(e))
            return "Failed to query DynamoDB"

    async def describe_dynamodb_table(**kwargs) -> str:
        table_name = kwargs.get("table_name", "")
        try:
            _validate_table(table_name)

            def _describe():
                client = _get_client()
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
                    if table.get("CreationDateTime")
                    else None,
                    "billing_mode": table.get("BillingModeSummary", {}).get("BillingMode", "PROVISIONED"),
                    "global_secondary_indexes": [
                        {
                            "index_name": gsi["IndexName"],
                            "key_schema": gsi["KeySchema"],
                            "projection": gsi["Projection"],
                        }
                        for gsi in table.get("GlobalSecondaryIndexes", [])
                    ],
                }

            table_info = await asyncio.to_thread(_describe)
            result = json.dumps({"status": "success", "table": table_info}, default=str, indent=2)
            return cap_result_size(redact_pii(result, enable=True))
        except Exception as e:
            logger.exception("DynamoDB error during describe_dynamodb_table", error=str(e))
            return "Failed to query DynamoDB"

    target_source_name = source.name
    ans = ToolAnnotations.read_only()

    return [
        MCPTool(
            manifest=ToolManifest(
                name=f"{target_source_name}.list_dynamodb_tables",
                description=f"List accessible DynamoDB tables on source {target_source_name}.",
                source_name=target_source_name,
                annotations=ans,
                parameters=[],
            ),
            handler=list_dynamodb_tables,
        ),
        MCPTool(
            manifest=ToolManifest(
                name=f"{target_source_name}.query_dynamodb",
                description=f"Query a DynamoDB table on source {target_source_name}.",
                source_name=target_source_name,
                annotations=ans,
                parameters=[
                    {"name": "table_name", "type": "string"},
                    {"name": "key_condition_expression", "type": "string", "description": "e.g. pk = :pk"},
                    {"name": "expression_attribute_values", "type": "object", "description": "JSON object mapping"},
                ],
            ),
            handler=query_dynamodb,
        ),
        MCPTool(
            manifest=ToolManifest(
                name=f"{target_source_name}.describe_dynamodb_table",
                description=(
                    f"Get schema, indexes, and throughput details for a DynamoDB "
                    f"table on {target_source_name}."
                ),
                source_name=target_source_name,
                annotations=ans,
                parameters=[
                    {
                        "name": "table_name",
                        "type": "string",
                        "description": "The name of the DynamoDB table to describe.",
                    },
                ],
            ),
            handler=describe_dynamodb_table,
        ),
    ]
