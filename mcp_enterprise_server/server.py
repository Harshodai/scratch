"""
MCP Enterprise Server — Main Entrypoint
=========================================
Combines GOS DB, DynamoDB, and Athena MCP tools into a single FastMCP
server with lifecycle management.

Usage:
  # Start with streamable HTTP (production-ready)
  python -m mcp_enterprise_server.server

  # Start with stdio (for Claude Desktop / local agent)
  python -m mcp_enterprise_server.server --transport stdio

  # Environment variables for configuration:
  GOS_DB_HOST=gosdb.internal.jpmc.com
  GOS_DB_PASSWORD=<secret>
  DYNAMODB_ROLE_ARN=arn:aws:iam::123456789012:role/MCP-DynamoDB-Reader
  ATHENA_ROLE_ARN=arn:aws:iam::123456789012:role/MCP-Athena-Reader
  ATHENA_OUTPUT_BUCKET=s3://my-athena-results/
"""

from __future__ import annotations

import argparse
import sys
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import structlog
from mcp.server.fastmcp import FastMCP

from mcp_enterprise_server.athena_mcp import register_athena_tools
from mcp_enterprise_server.config import MCPServerConfig
from mcp_enterprise_server.dynamodb_mcp import register_dynamodb_tools
from mcp_enterprise_server.gosdb_mcp import GOSDBAppContext, GOSDBPool, register_gosdb_tools
from mcp_enterprise_server.guardrails import init_guardrails
from mcp_enterprise_server.s3_mcp import register_s3_tools

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

# ---------------------------------------------------------------------------
# Structured logging setup
# ---------------------------------------------------------------------------
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.dev.ConsoleRenderer() if sys.stderr.isatty() else structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(0),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger("mcp_server")


# ---------------------------------------------------------------------------
# Application Lifespan Context
# ---------------------------------------------------------------------------
# Note: We reuse GOSDBAppContext as the lifespan context since
# GOS DB tools need to access it by field name (.pool, .config).
# DynamoDB and Athena tools use Context[..., Any] and don't access
# the lifespan context (they manage their own credentials internally).


@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[GOSDBAppContext]:
    """
    Manage server lifecycle:
      - Startup:  Initialize GOS DB pool, validate AWS credentials
      - Shutdown: Close pools, flush logs
    """
    config = MCPServerConfig()
    logger.info(
        "server_starting",
        server_name=config.server_name,
        version=config.server_version,
        transport=config.transport,
    )

    # Initialize guardrails with config values
    init_guardrails(config.guardrails)

    # Initialize GOS DB connection pool
    gosdb_pool = GOSDBPool(config.gosdb)
    try:
        await gosdb_pool.initialize()
        logger.info("gosdb_pool_ready")
    except Exception as e:
        logger.warning(
            "gosdb_pool_init_failed",
            error=str(e),
            message="GOS DB tools will be unavailable. Server continues with AWS tools.",
        )

    try:
        yield GOSDBAppContext(pool=gosdb_pool, config=config.gosdb)
    finally:
        await gosdb_pool.close()
        logger.info("server_shutdown_complete")


# ---------------------------------------------------------------------------
# Server Factory
# ---------------------------------------------------------------------------
def create_server() -> FastMCP:
    """Create and configure the MCP server with all tools registered."""
    config = MCPServerConfig()

    mcp = FastMCP(
        name=config.server_name,
        lifespan=app_lifespan,
    )

    # Register tool sets
    register_gosdb_tools(mcp, config.gosdb)
    register_dynamodb_tools(mcp, config.dynamodb)
    register_athena_tools(mcp, config.athena)
    register_s3_tools(mcp, config.s3)

    # Add a health-check / info resource
    @mcp.resource("server://info")
    def server_info() -> str:
        """Server metadata and configuration summary."""
        import json

        return json.dumps(
            {
                "name": config.server_name,
                "version": config.server_version,
                "tools": {
                    "gosdb": {
                        "schemas": config.gosdb.allowed_schemas,
                        "permission": config.gosdb.permission_level.value,
                    },
                    "dynamodb": {
                        "region": config.dynamodb.region.value,
                        "tables": config.dynamodb.allowed_tables or ["*"],
                        "permission": config.dynamodb.permission_level.value,
                    },
                    "s3": {
                        "region": config.s3.region.value,
                        "buckets": config.s3.allowed_buckets or ["*"],
                        "permission": config.s3.permission_level.value,
                    },
                    "athena": {
                        "region": config.athena.region.value,
                        "workgroup": config.athena.workgroup,
                        "databases": config.athena.allowed_databases or ["*"],
                        "permission": config.athena.permission_level.value,
                    },
                },
                "guardrails": {
                    "rate_limit": config.guardrails.global_rate_limit,
                    "pii_redaction": config.guardrails.enable_pii_redaction,
                    "audit_logging": config.guardrails.enable_audit_logging,
                },
            },
            indent=2,
        )

    logger.info(
        "server_configured",
        gosdb_schemas=config.gosdb.allowed_schemas,
        dynamodb_region=config.dynamodb.region.value,
        athena_region=config.athena.region.value,
    )

    return mcp


# ---------------------------------------------------------------------------
# CLI Entrypoint
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Enterprise MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "streamable-http"],
        default="streamable-http",
        help="MCP transport protocol (default: streamable-http)",
    )
    parser.add_argument("--host", default="0.0.0.0", help="Bind host")
    parser.add_argument("--port", type=int, default=8000, help="Bind port")
    args = parser.parse_args()

    mcp = create_server()
    logger.info("starting_server", transport=args.transport, host=args.host, port=args.port)

    if args.transport == "streamable-http":
        mcp.run(transport="streamable-http", host=args.host, port=args.port)
    elif args.transport == "sse":
        mcp.run(transport="sse", host=args.host, port=args.port)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
