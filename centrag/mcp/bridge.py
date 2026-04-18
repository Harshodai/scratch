"""
MCP Bridge — The central registry for all MCP-based data sources.

The WHY:
    This bridge orchestrates the ProcessManager (for external servers like AWS)
    and the new Source→Tool architecture (stolen from googleapis/mcp-toolbox).

    Architecture evolution:
    - v1: ``DynamicSQLMCPFactory`` coupled connection + tool creation.
    - v2 (current): Sources, Tools, and Toolsets are first-class citizens.

    Three design patterns stolen from MCP Toolbox:
    1. **Source/Tool Separation** (``sources/sources.go`` + ``tools/tools.go``)
       — Sources manage connections, Tools reference sources by name.
    2. **Declarative YAML Config** (``server/config.go``)
       — ``mcp_tools.yaml`` files parsed at startup.
    3. **Prebuilt Config Templates** (``prebuiltconfigs/prebuiltconfigs.go``)
       — Ready-to-copy YAML templates for postgres, mysql, sqlite.

Pattern: FACADE / REGISTRY
SOLID: SRP — only coordinates MCP servers, no business logic.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from centrag.mcp.config_loader import (
    get_prebuilt_config,
    list_prebuilt_configs,
    load_mcp_config,
)
from centrag.mcp.process_manager import MCPProcessManager
from centrag.mcp.source_registry import SourceRegistry, SQLSourceConfig
from centrag.mcp.tool_registry import ToolRegistry
from centrag.utils.logger import get_logger

if TYPE_CHECKING:
    from pathlib import Path

logger = get_logger("mcp.bridge")


class MCPBridge:
    """
    Orchestrates multiple MCP servers and exposes their tools to the engine.

    Architecture (stolen from MCP Toolbox):
        SourceRegistry  → manages database connections (Source instances)
        ToolRegistry    → manages executable tools + toolset groups
        ProcessManager  → manages external subprocess-based MCP servers

    Usage (programmatic):
        bridge = MCPBridge()
        await bridge.register_dynamic_db("gos", "postgresql://...", schema="public")
        result = await bridge.call_tool("gos.query_orders", {"limit": 10})

    Usage (declarative):
        bridge = MCPBridge()
        bridge.load_config("mcp_tools.yaml")
        result = await bridge.call_tool("gos.query_orders", {"limit": 10})
    """

    def __init__(self) -> None:
        self.source_registry = SourceRegistry()
        self.tool_registry = ToolRegistry(self.source_registry)
        self.process_manager = MCPProcessManager()

        import contextlib
        import asyncio

        self._exit_stack = contextlib.AsyncExitStack()
        self._external_sessions: dict[str, Any] = {}
        
        # We lazily initialize the semaphore to avoid attaching 
        # to the wrong asyncio event loop during synchronous startup.
        self._external_semaphore: asyncio.Semaphore | None = None

        # Backward compat: retained for legacy code paths
        self._dynamic_servers: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Declarative Config (Steal #2 from Toolbox)
    # ------------------------------------------------------------------
    def load_config(self, config_path: str | Path) -> dict[str, Any]:
        """Load an ``mcp_tools.yaml`` config file and register all resources.

        This is the primary entry point for declarative configuration,
        stolen from Toolbox's ``config.go:UnmarshalResourceConfig()``.

        Args:
            config_path: Path to the YAML config file.

        Returns:
            Summary dict with counts of registered sources, tools, toolsets.
        """
        return load_mcp_config(
            config_path=config_path,
            source_registry=self.source_registry,
            tool_registry=self.tool_registry,
        )

    # ------------------------------------------------------------------
    # Programmatic Registration (backward compat + new Source API)
    # ------------------------------------------------------------------
    def register_dynamic_db(
        self,
        name: str,
        connection_string: str,
        schema: str | None = None,
        tables: list[str] | None = None,
    ) -> bool:
        """Create and register a dynamic SQL MCP source with auto-generated tools.

        The WHY:
            Refactored from the old ``DynamicSQLMCPFactory.create_server()``
            into the new Source→Tool architecture. The connection (Source)
            is now decoupled from the tools, allowing toolset grouping
            and independent lifecycle management.
        """
        try:
            # 1. Register the Source (connection)
            config = SQLSourceConfig(
                name=name,
                connection_string=connection_string,
                kind=self._detect_dialect(connection_string),
                schema=schema,
                read_only=True,
            )
            source = self.source_registry.add(config)

            # 2. If specific tables requested, filter source.tables
            if tables and hasattr(source, "tables"):
                source.tables = [t for t in source.tables if t in tables]

            # 3. Generate tools from schema reflection
            tools_created = self.tool_registry.generate_sql_tools(name)

            logger.info(
                "mcp_bridge_db_registered",
                name=name,
                tools_created=tools_created,
            )
            return True
        except Exception as e:
            logger.error(
                "mcp_bridge_db_registration_failed",
                name=name,
                error=str(e),
            )
            return False

    def register_aws_source(
        self,
        name: str,
        kind: str,
        region: str = "us-east-1",
        role_arn: str | None = None,
        options: dict[str, Any] | None = None,
    ) -> bool:
        """Create and register an AWS MCP source dynamically (e.g. from UI)."""
        try:
            from centrag.mcp.source_registry import AWSSourceConfig

            config = AWSSourceConfig(name=name, kind=kind, region=region, role_arn=role_arn, options=options or {})
            source = self.source_registry.add(config)

            tools_created = 0
            if kind == "aws-dynamodb":
                from centrag.mcp.aws.dynamodb import generate_dynamodb_tools

                tools = generate_dynamodb_tools(source)
            elif kind == "aws-athena":
                from centrag.mcp.aws.athena import generate_athena_tools

                tools = generate_athena_tools(source)
            elif kind == "aws-s3":
                from centrag.mcp.aws.s3 import generate_s3_tools

                tools = generate_s3_tools(source)
            elif kind == "aws-emr":
                from centrag.mcp.aws.emr import generate_emr_tools

                tools = generate_emr_tools(source)
            else:
                tools = []

            for t in tools:
                self.tool_registry.register(t)
            tools_created = len(tools)

            logger.info(
                "mcp_bridge_aws_registered",
                name=name,
                kind=kind,
                tools_created=tools_created,
            )
            return True
        except Exception as e:
            logger.error(
                "mcp_bridge_aws_registration_failed",
                name=name,
                error=str(e),
            )
            return False

    async def register_external_mcp_sse(self, name: str, url: str, headers: dict[str, str] | None = None) -> bool:
        """Register a remote SSE MCP server and proxy its tools."""
        try:
            from mcp.client.session import ClientSession
            from mcp.client.sse import sse_client

            read, write = await self._exit_stack.enter_async_context(sse_client(url, headers=headers))
            session = await self._exit_stack.enter_async_context(ClientSession(read, write))
            await session.initialize()

            self._external_sessions[name] = session
            await self._proxy_tools(name, session)
            logger.info("mcp_bridge_external_sse_registered", name=name, url=url)
            return True
        except Exception as e:
            logger.error("mcp_bridge_sse_registration_failed", name=name, error=str(e))
            return False

    async def register_external_mcp_stdio(
        self, name: str, command: str, args: list[str], env: dict[str, str] | None = None
    ) -> bool:
        """Register a local stdio MCP server and proxy its tools."""
        try:
            from mcp.client.session import ClientSession
            from mcp.client.stdio import StdioServerParameters, stdio_client

            # Start via process manager for lifetime tracking context (legacy UI check)
            cmd = [command] + args
            await self.launch_external_server(name, cmd, env)

            server_params = StdioServerParameters(command=command, args=args, env=env)
            read, write = await self._exit_stack.enter_async_context(stdio_client(server_params))
            session = await self._exit_stack.enter_async_context(ClientSession(read, write))
            await session.initialize()

            self._external_sessions[name] = session
            await self._proxy_tools(name, session)
            logger.info("mcp_bridge_external_stdio_registered", name=name, command=command)
            return True
        except Exception as e:
            logger.error("mcp_bridge_stdio_registration_failed", name=name, error=str(e))
            return False

    async def _proxy_tools(self, source_name: str, session: Any) -> None:
        """Proxy upstream tools into the internal ToolRegistry."""
        from centrag.mcp.tool_registry import MCPTool, ToolManifest

        tools_response = await session.list_tools()
        for t in tools_response.tools:

            async def proxy_handler(tool_target=t.name, session_ref=session, **kwargs) -> str:
                import asyncio
                
                # Lazy initialization logic
                if self._external_semaphore is None:
                    self._external_semaphore = asyncio.Semaphore(10)
                    
                # Rate limit execution using centralized semaphore and wait_for execution limits
                async with self._external_semaphore:
                    try:
                        res = await asyncio.wait_for(
                            session_ref.call_tool(tool_target, arguments=kwargs),
                            timeout=60.0
                        )
                        if hasattr(res, "content") and res.content:
                            return "\n".join(b.text for b in res.content if hasattr(b, "text"))
                        return str(res)
                    except asyncio.TimeoutError:
                        logger.error("mcp_bridge_proxy_timeout", tool=tool_target)
                        return f"Error: MCP Server proxy call to '{tool_target}' timed out after 60 seconds."

            input_params = []
            if getattr(t, "inputSchema", None):
                props = t.inputSchema.get("properties", {})
                for prop_name, prop_details in props.items():
                    input_params.append(
                        {
                            "name": prop_name,
                            "type": prop_details.get("type", "string"),
                            "description": prop_details.get("description", ""),
                        }
                    )

            manifest = ToolManifest(
                name=f"{source_name}.{t.name}",
                description=t.description or "",
                source_name=source_name,
                parameters=input_params,
            )
            proxy_tool = MCPTool(manifest=manifest, handler=proxy_handler)
            self.tool_registry.register(proxy_tool)

    async def launch_external_server(
        self,
        name: str,
        command: list[str],
        env: dict[str, str] | None = None,
    ) -> bool:
        """Launch an external MCP server process (e.g. AWS, Jira).

        The WHY:
            External MCP servers (AWS, Jira, Confluence) run as standalone
            processes. This method wraps the ProcessManager to provide a
            unified lifecycle API.
        """
        return self.process_manager.launch_server(name, command, env)

    # ------------------------------------------------------------------
    # Tool Execution
    # ------------------------------------------------------------------
    async def call_tool(self, tool_name: str, params: dict[str, Any]) -> str:
        """
        Unified tool calling gateway with 3-tier resolution.

        Resolution order (mirrors Toolbox's tool lookup):
        1. ToolRegistry (new Source→Tool architecture)
        2. Legacy DynamicSQLMCPFactory servers (backward compat)
        3. External subprocess MCP servers

        Args:
            tool_name: Fully qualified tool name (e.g. "gos.query_orders")
                       or legacy format ("server_name", "tool_name")
            params: Tool parameters dict
        """
        # Tier 1: New ToolRegistry (Source→Tool architecture)
        tool = self.tool_registry.get(tool_name)
        if tool is not None:
            try:
                result = await tool.invoke(params)
                return result
            except Exception as e:
                logger.error(
                    "mcp_bridge_tool_call_error",
                    tool=tool_name,
                    error=str(e),
                )
                return f"MCP Tool Error: {e}"

        # Tier 2: Legacy Dynamic Servers (backward compat)
        # Parse "server.tool" format for legacy routing
        if "." in tool_name:
            server_name, legacy_tool = tool_name.split(".", 1)
        else:
            server_name = tool_name
            legacy_tool = ""

        if server_name in self._dynamic_servers:
            server = self._dynamic_servers[server_name]
            try:
                result = await server.call_tool(legacy_tool or tool_name, params)
                return str(result)
            except Exception as e:
                logger.error(
                    "mcp_bridge_legacy_tool_error",
                    server=server_name,
                    tool=legacy_tool,
                    error=str(e),
                )
                return f"MCP Legacy Error: {e}"

        # Tier 3: External Subprocess Servers
        if self.process_manager.is_alive(server_name):
            logger.warning(
                "mcp_bridge_external_client_not_ready",
                server=server_name,
            )
            return f"Error: MCP Client Session for external server '{server_name}' not yet initialized."

        return f"Error: MCP tool '{tool_name}' not found in any tier."

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------
    def list_servers(self) -> dict[str, str]:
        """List all registered sources and servers with their status."""
        result: dict[str, str] = {}

        # Sources from the new registry
        for name, source_type in self.source_registry.list_sources().items():
            result[name] = f"source_{source_type}_active"

        # Legacy dynamic servers
        for name in self._dynamic_servers:
            if name not in result:
                result[name] = "legacy_dynamic_active"

        # External processes
        for name in list(self.process_manager._processes.keys()):
            if name not in result:
                status = "external_alive" if self.process_manager.is_alive(name) else "external_dead"
                result[name] = status

        return result

    def list_tools(self) -> dict[str, dict[str, Any]]:
        """List all registered tools with their manifests."""
        return self.tool_registry.list_tools()

    def list_toolsets(self) -> dict[str, list[str]]:
        """List all toolset groupings."""
        return self.tool_registry.list_toolsets()

    def list_prebuilt_templates(self) -> list[str]:
        """List available prebuilt config templates (Steal #3)."""
        return list_prebuilt_configs()

    def get_prebuilt_template(self, name: str) -> str | None:
        """Get a prebuilt config template by database type."""
        return get_prebuilt_config(name)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    async def shutdown(self) -> None:
        """Cleanup all managed resources."""
        if hasattr(self, "_exit_stack"):
            await self._exit_stack.aclose()
        self.process_manager.shutdown_all()
        self._dynamic_servers.clear()
        logger.info("mcp_bridge_shutdown_complete")

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    @staticmethod
    def _detect_dialect(connection_string: str) -> str:
        """Detect SQLAlchemy dialect from connection string."""
        cs = connection_string.lower()
        if cs.startswith("postgresql") or cs.startswith("postgres"):
            return "postgres"
        elif cs.startswith("mysql"):
            return "mysql"
        elif cs.startswith("sqlite"):
            return "sqlite"
        elif cs.startswith("oracle"):
            return "oracle"
        elif cs.startswith("mssql"):
            return "mssql"
        return "postgres"  # Default fallback
