"""
MCP Client Examples
====================
Shows how consumers (AI agents, internal tools) connect to the MCP server
and invoke tools for GOS DB, DynamoDB, and Athena.

These examples demonstrate both stdio and HTTP transports.
"""

from __future__ import annotations

import asyncio
import json
import os

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


# ===========================================================================
# Example 1: Connect via stdio transport (local development)
# ===========================================================================
async def example_stdio_client():
    """
    Connect to the MCP server via stdio.
    Useful for local testing with Claude Desktop or similar.
    """
    server_params = StdioServerParameters(
        command="python",
        args=["-m", "mcp_enterprise_server.server", "--transport", "stdio"],
        env={
            "GOS_DB_HOST": os.environ.get("GOS_DB_HOST", "gosdb.internal.jpmc.com"),
            "GOS_DB_PASSWORD": os.environ.get("GOS_DB_PASSWORD", ""),
            "DYNAMODB_REGION": "us-east-1",
            "ATHENA_REGION": "us-east-1",
            "ATHENA_OUTPUT_BUCKET": "s3://my-athena-results/",
        },
    )

    async with stdio_client(server_params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()

        # -- List available tools --
        tools = await session.list_tools()
        print("Available Tools:")
        for tool in tools.tools:
            print(f"  📦 {tool.name}: {tool.description[:80]}...")

        # -- List available resources --
        resources = await session.list_resources()
        print("\nAvailable Resources:")
        for resource in resources.resources:
            print(f"  📄 {resource.uri}")

        # ---------------------------------------------------------------
        # Example: Query GOS DB
        # ---------------------------------------------------------------
        print("\n" + "=" * 60)
        print("Example: Query GOS DB")
        print("=" * 60)

        result = await session.call_tool(
            "tool_query_gosdb",
            arguments={
                "query": "SELECT * FROM APP_DATA.transactions WHERE amount > :min_amount",
                "schema": "APP_DATA",
                "max_rows": 10,
                # Note: params would need to be JSON string in practice
            },
        )
        print(f"GOS DB Result: {result.content[0].text[:500]}")

        # ---------------------------------------------------------------
        # Example: List DynamoDB Tables
        # ---------------------------------------------------------------
        print("\n" + "=" * 60)
        print("Example: List DynamoDB Tables")
        print("=" * 60)

        result = await session.call_tool("tool_list_dynamodb_tables", arguments={})
        print(f"DynamoDB Tables: {result.content[0].text[:500]}")

        # ---------------------------------------------------------------
        # Example: Query DynamoDB
        # ---------------------------------------------------------------
        print("\n" + "=" * 60)
        print("Example: Query DynamoDB Table")
        print("=" * 60)

        result = await session.call_tool(
            "tool_query_dynamodb",
            arguments={
                "table_name": "user-sessions",
                "key_condition": "user_id = :uid",
                "expression_values": json.dumps({":uid": "user_12345"}),
                "max_items": 5,
            },
        )
        print(f"DynamoDB Query: {result.content[0].text[:500]}")

        # ---------------------------------------------------------------
        # Example: Execute Athena Query
        # ---------------------------------------------------------------
        print("\n" + "=" * 60)
        print("Example: Execute Athena Query")
        print("=" * 60)

        result = await session.call_tool(
            "tool_execute_athena_query",
            arguments={
                "query": "SELECT * FROM logs.api_access_logs LIMIT 10",
                "database": "logs",
                "max_rows": 10,
            },
        )
        print(f"Athena Result: {result.content[0].text[:500]}")

        # ---------------------------------------------------------------
        # Example: Describe DynamoDB Table
        # ---------------------------------------------------------------
        print("\n" + "=" * 60)
        print("Example: Describe DynamoDB Table")
        print("=" * 60)

        result = await session.call_tool(
            "tool_describe_dynamodb_table",
            arguments={"table_name": "user-sessions"},
        )
        print(f"Table Description: {result.content[0].text[:500]}")

        # ---------------------------------------------------------------
        # Example: List Athena Databases
        # ---------------------------------------------------------------
        print("\n" + "=" * 60)
        print("Example: List Athena Databases")
        print("=" * 60)

        result = await session.call_tool("tool_list_athena_databases", arguments={})
        print(f"Athena Databases: {result.content[0].text[:500]}")


# ===========================================================================
# Example 2: Connect via HTTP transport (production)
# ===========================================================================
async def example_http_client():
    """
    Connect to the MCP server via Streamable HTTP.
    This is the production deployment pattern.
    """
    from mcp.client.streamable_http import streamablehttp_client

    async with streamablehttp_client("http://localhost:8000/mcp") as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # List tools
            tools = await session.list_tools()
            print(f"Connected to MCP server. {len(tools.tools)} tools available.")

            # Execute a GOS DB query
            result = await session.call_tool(
                "tool_query_gosdb",
                arguments={
                    "query": "SELECT COUNT(*) AS total FROM APP_DATA.orders",
                    "schema": "APP_DATA",
                },
            )
            print(f"Result: {result.content[0].text}")


# ===========================================================================
# Claude Desktop Configuration
# ===========================================================================
CLAUDE_DESKTOP_CONFIG = {
    "mcpServers": {
        "enterprise-rag": {
            "command": "python",
            "args": ["-m", "mcp_enterprise_server.server", "--transport", "stdio"],
            "env": {
                "GOS_DB_HOST": "gosdb.internal.jpmc.com",
                "GOS_DB_USERNAME": "mcp_reader",
                "GOS_DB_PASSWORD": "${GOS_DB_PASSWORD}",
                "DYNAMODB_ROLE_ARN": "arn:aws:iam::123456789012:role/MCP-DynamoDB-Reader",
                "DYNAMODB_REGION": "us-east-1",
                "ATHENA_ROLE_ARN": "arn:aws:iam::123456789012:role/MCP-Athena-Reader",
                "ATHENA_REGION": "us-east-1",
                "ATHENA_OUTPUT_BUCKET": "s3://enterprise-mcp-athena-results/",
                "ATHENA_WORKGROUP": "analytics-team",
            },
        }
    }
}


def print_claude_config():
    """Print the Claude Desktop MCP configuration."""
    print("Claude Desktop MCP Configuration")
    print("=" * 50)
    print("Save this to: %APPDATA%/Claude/claude_desktop_config.json")
    print()
    print(json.dumps(CLAUDE_DESKTOP_CONFIG, indent=2))


# ===========================================================================
# Main
# ===========================================================================
if __name__ == "__main__":
    import sys

    if "--http" in sys.argv:
        asyncio.run(example_http_client())
    elif "--config" in sys.argv:
        print_claude_config()
    else:
        asyncio.run(example_stdio_client())
