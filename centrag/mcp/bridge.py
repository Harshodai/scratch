"""
MCP Bridge — The central registry for all MCP-based data sources.

The WHY:
    This bridge orchestrates the ProcessManager (for external servers like AWS)
    and the DynamicSQLMCPFactory (for internal DBs). It provides a unified
    client interface for the RetrievalEngine to call tools across all servers.

Pattern: FACADE / REGISTRY
SOLID: SRP — only coordinates MCP servers, no business logic.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from centrag.mcp.process_manager import MCPProcessManager
from centrag.mcp.dynamic_db_factory import DynamicSQLMCPFactory
from centrag.utils.logger import get_logger

logger = get_logger("mcp.bridge")


class MCPBridge:
    """
    Orchestrates multiple MCP servers and exposes their tools to the engine.

    Usage:
        bridge = MCPBridge()
        await bridge.register_dynamic_db("gos", "postgresql://...", schema="public")
        result = await bridge.call_tool("gos", "query_orders", {"limit": 10})
    """

    def __init__(self) -> None:
        self.process_manager = MCPProcessManager()
        self.dynamic_factory = DynamicSQLMCPFactory()
        self._dynamic_servers: Dict[str, Any] = {}  # In-memory FastMCP instances

    async def register_dynamic_db(
        self,
        name: str,
        connection_string: str,
        schema: Optional[str] = None,
        tables: Optional[list[str]] = None,
    ) -> bool:
        """Create and register a dynamic SQL MCP server.

        The WHY:
            Allows the RetrievalEngine to add new database data sources at
            runtime without redeployment. When a user provides a connection
            string, this method generates all MCP tools via SQLAlchemy reflection.
        """
        try:
            mcp_server = self.dynamic_factory.create_server(
                name=name,
                connection_string=connection_string,
                schema=schema,
                tables=tables,
            )
            self._dynamic_servers[name] = mcp_server
            logger.info("mcp_bridge_db_registered", name=name)
            return True
        except Exception as e:
            logger.error("mcp_bridge_db_registration_failed", name=name, error=str(e))
            return False

    async def launch_external_server(
        self,
        name: str,
        command: List[str],
        env: Optional[Dict[str, str]] = None,
    ) -> bool:
        """Launch an external MCP server process (e.g. AWS, Jira).

        The WHY:
            External MCP servers (AWS, Jira, Confluence) run as standalone
            processes. This method wraps the ProcessManager to provide a
            unified lifecycle API.
        """
        return self.process_manager.launch_server(name, command, env)

    async def call_tool(
        self, server_name: str, tool_name: str, params: Dict[str, Any]
    ) -> str:
        """
        Unified tool calling gateway.

        Routes calls to either dynamic internal servers or external subprocesses.

        NOTE: External subprocess client sessions require an MCP Client Session
        to communicate over stdio pipes. This is an architectural boundary —
        the full client implementation is tracked as a Phase 3 deliverable.
        """
        # 1. Route to Dynamic Internal Servers first
        if server_name in self._dynamic_servers:
            server = self._dynamic_servers[server_name]
            try:
                result = await server.call_tool(tool_name, params)
                return str(result)
            except Exception as e:
                logger.error(
                    "mcp_bridge_tool_call_error",
                    server=server_name,
                    tool=tool_name,
                    error=str(e),
                )
                return f"MCP Internal Error: {str(e)}"

        # 2. Route to External Subprocesses
        if self.process_manager.is_alive(server_name):
            # NOTE: Full MCP Client Session integration pending.
            logger.warning(
                "mcp_bridge_external_client_not_ready",
                server=server_name,
            )
            return (
                f"Error: MCP Client Session for external server "
                f"'{server_name}' not yet initialized."
            )

        return f"Error: MCP Server '{server_name}' not found or not running."

    def list_servers(self) -> Dict[str, str]:
        """List all registered servers and their status."""
        result = {}
        for name in self._dynamic_servers:
            result[name] = "dynamic_active"
        for name in list(self.process_manager._processes.keys()):
            result[name] = "external_alive" if self.process_manager.is_alive(name) else "external_dead"
        return result

    def shutdown(self) -> None:
        """Cleanup all managed resources."""
        self.process_manager.shutdown_all()
        self._dynamic_servers.clear()
        logger.info("mcp_bridge_shutdown_complete")
