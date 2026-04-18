"""
MCP Tool Registry — Declarative tool definitions with annotations and toolsets.

The WHY:
    STOLEN from googleapis/mcp-toolbox ``internal/tools/tools.go`` +
    ``internal/tools/toolsets.go``.

    The Toolbox's tool layer has three brilliant design choices:
    1. **Tool Annotations** (``ToolAnnotations`` struct, line 72-77):
       MCP spec compliance — ``readOnlyHint``, ``destructiveHint``, ``idempotentHint``.
       This tells AI agents *what a tool can do* before calling it.
    2. **Manifest** (``McpManifest`` struct, line 143-152):
       A serializable description of a tool for discovery by MCP clients.
    3. **Toolsets** (``toolsets.go``):
       Named groups of tools for different agent personas. The postgres
       prebuilt config has 5 toolsets: data, monitor, health, view-config,
       replication — each exposing a different subset of the 24 tools.

    We adapt all three to Python, integrated with our existing
    ``DynamicSQLMCPFactory`` tools.

Pattern: STRATEGY + COMPOSITE (from Toolbox ``ToolConfig.Initialize()``)
SOLID: ISP — tools only see ``SourceProvider``, not the full server.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any

from centrag.mcp.source_registry import SourceRegistry, SQLSource, _validate_name
from centrag.utils.logger import get_logger

logger = get_logger("mcp.tool_registry")

# Blocked SQL keywords for read-only enforcement (carried from DynamicSQLMCPFactory)
_BLOCKED_KEYWORDS = frozenset(
    {
        "DROP",
        "DELETE",
        "UPDATE",
        "INSERT",
        "TRUNCATE",
        "ALTER",
        "CREATE",
        "GRANT",
        "REVOKE",
        "EXEC",
        "EXECUTE",
        "MERGE",
    }
)


def _is_read_only(query: str) -> bool:
    """Check if the SQL statement is read-only."""
    tokens = query.upper().split()
    return not any(token in _BLOCKED_KEYWORDS for token in tokens)


# ---------------------------------------------------------------------------
# Tool Annotations — STOLEN from Toolbox ``tools.go:72-95``
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ToolAnnotations:
    """MCP spec tool annotations for agent-side decision making.

    Stolen from Toolbox ``ToolAnnotations`` (``tools.go:72-77``).
    These hints tell AI agents whether a tool modifies data, is safe
    to retry, or accesses external systems — BEFORE calling it.

    Reference: https://modelcontextprotocol.io/specification/2025-06-18/schema#toolannotations
    """

    read_only_hint: bool | None = None
    destructive_hint: bool | None = None
    idempotent_hint: bool | None = None
    open_world_hint: bool | None = None

    @classmethod
    def read_only(cls) -> ToolAnnotations:
        """Factory for read-only tools (mirrors Toolbox ``NewReadOnlyAnnotations``)."""
        return cls(read_only_hint=True)

    @classmethod
    def destructive(cls) -> ToolAnnotations:
        """Factory for destructive tools (mirrors Toolbox ``NewDestructiveAnnotations``)."""
        return cls(read_only_hint=False, destructive_hint=True)

    def to_dict(self) -> dict[str, Any]:
        """Serialize for MCP manifest."""
        result: dict[str, Any] = {}
        if self.read_only_hint is not None:
            result["readOnlyHint"] = self.read_only_hint
        if self.destructive_hint is not None:
            result["destructiveHint"] = self.destructive_hint
        if self.idempotent_hint is not None:
            result["idempotentHint"] = self.idempotent_hint
        if self.open_world_hint is not None:
            result["openWorldHint"] = self.open_world_hint
        return result


# ---------------------------------------------------------------------------
# Tool Manifest — STOLEN from Toolbox ``tools.go:136-152``
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ToolManifest:
    """MCP-discoverable tool description.

    Stolen from Toolbox ``McpManifest`` (``tools.go:143-152``).
    This is what MCP clients receive during tool listing — the name,
    description, input schema, and annotations.
    """

    name: str
    description: str
    source_name: str
    annotations: ToolAnnotations = field(default_factory=ToolAnnotations.read_only)
    parameters: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to MCP-compatible manifest format."""
        result: dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "source": self.source_name,
        }
        annotations_dict = self.annotations.to_dict()
        if annotations_dict:
            result["annotations"] = annotations_dict
        if self.parameters:
            result["inputSchema"] = {
                "type": "object",
                "properties": {
                    p["name"]: {
                        "type": p.get("type", "string"),
                        "description": p.get("description", ""),
                    }
                    for p in self.parameters
                },
            }
        return result


# ---------------------------------------------------------------------------
# Tool — the executable unit
# ---------------------------------------------------------------------------

# Async callable type for tool handlers
ToolHandler = Callable[..., Coroutine[Any, Any, str]]


@dataclass
class MCPTool:
    """A registered, executable MCP tool.

    Combines Toolbox's ``Tool`` interface (``tools.go:116-126``) with
    CentRAG's existing dynamic SQL generation. Each tool has:
    - A manifest (for discovery)
    - A handler (async callable for execution)
    - A reference to its source (by name, not direct coupling)
    """

    manifest: ToolManifest
    handler: ToolHandler

    @property
    def name(self) -> str:
        return self.manifest.name

    @property
    def source_name(self) -> str:
        return self.manifest.source_name

    async def invoke(self, params: dict[str, Any]) -> str:
        """Execute the tool with the given parameters."""
        return await self.handler(**params)


# ---------------------------------------------------------------------------
# Toolset — STOLEN from Toolbox ``toolsets.go:22-67``
# ---------------------------------------------------------------------------
@dataclass
class Toolset:
    """Named group of tools for a specific agent persona.

    Stolen from Toolbox ``toolsets.go`` — the postgres prebuilt config
    groups 24 tools into 5 toolsets (data, monitor, health, view-config,
    replication). This lets different agents see different tool subsets
    from the same database.

    Example from Toolbox ``prebuiltconfigs/tools/postgres.yaml:202-240``:
        toolsets:
            data: [execute_sql, list_tables, list_views, ...]
            monitor: [list_query_stats, get_query_plan, ...]
            health: [list_top_bloated_tables, ...]
    """

    name: str
    tool_names: list[str]
    description: str = ""

    def resolve(self, tool_map: dict[str, MCPTool]) -> list[MCPTool]:
        """Resolve tool names to actual tool instances.

        Mirrors Toolbox ``ToolsetConfig.Initialize()`` (``toolsets.go:43-67``).
        """
        resolved = []
        for tool_name in self.tool_names:
            if tool_name in tool_map:
                resolved.append(tool_map[tool_name])
            else:
                logger.warning(
                    "toolset_missing_tool",
                    toolset=self.name,
                    missing_tool=tool_name,
                )
        return resolved


# ---------------------------------------------------------------------------
# Tool Registry — The unified tool store
# ---------------------------------------------------------------------------
class ToolRegistry:
    """Central registry for all MCP tools, with toolset grouping.

    Combines patterns from:
    - Toolbox ``toolRegistry`` (``tools.go:36``)
    - Toolbox ``ToolsetConfig`` (``toolsets.go``)

    The WHY:
        The old ``DynamicSQLMCPFactory`` created tools inside FastMCP
        instances with no way to inspect, group, or filter them.
        This registry makes tools first-class citizens that can be:
        - Listed by source
        - Grouped into toolsets
        - Filtered by annotations (read-only, destructive)
        - Serialized to MCP manifests
    """

    def __init__(self, source_registry: SourceRegistry) -> None:
        self._source_registry = source_registry
        self._tools: dict[str, MCPTool] = {}
        self._toolsets: dict[str, Toolset] = {}

    def register(self, tool: MCPTool) -> None:
        """Register a tool instance."""
        _validate_name(tool.name)
        self._tools[tool.name] = tool
        logger.info(
            "tool_registered",
            name=tool.name,
            source=tool.source_name,
            read_only=tool.manifest.annotations.read_only_hint,
        )

    def register_toolset(self, toolset: Toolset) -> None:
        """Register a toolset (named group of tools)."""
        _validate_name(toolset.name)
        self._toolsets[toolset.name] = toolset
        logger.info(
            "toolset_registered",
            name=toolset.name,
            tool_count=len(toolset.tool_names),
        )

    def get(self, name: str) -> MCPTool | None:
        """Look up a tool by name."""
        return self._tools.get(name)

    def get_toolset(self, name: str) -> list[MCPTool] | None:
        """Get resolved tools for a toolset."""
        toolset = self._toolsets.get(name)
        if toolset is None:
            return None
        return toolset.resolve(self._tools)

    def list_tools(self) -> dict[str, dict[str, Any]]:
        """List all tools with their manifests."""
        return {name: tool.manifest.to_dict() for name, tool in self._tools.items()}

    def list_toolsets(self) -> dict[str, list[str]]:
        """List all toolsets and their tool names."""
        return {name: ts.tool_names for name, ts in self._toolsets.items()}

    def tools_for_source(self, source_name: str) -> list[MCPTool]:
        """Get all tools bound to a specific source."""
        return [t for t in self._tools.values() if t.source_name == source_name]

    async def invoke(self, tool_name: str, params: dict[str, Any]) -> str:
        """Execute a tool by name with the given parameters."""
        tool = self._tools.get(tool_name)
        if tool is None:
            return f"Error: Tool '{tool_name}' not found."
        return await tool.invoke(params)

    @property
    def count(self) -> int:
        return len(self._tools)

    # ------------------------------------------------------------------
    # Dynamic SQL tool generation (migrated from DynamicSQLMCPFactory)
    # ------------------------------------------------------------------
    def generate_sql_tools(self, source_name: str) -> int:
        """Auto-generate read-only SQL tools for a registered SQL source.

        The WHY:
            This is our UNIQUE ADVANTAGE over the Toolbox. The Toolbox
            requires pre-defining every tool in YAML. We use SQLAlchemy
            reflection to discover tables at runtime and generate tools
            dynamically. If someone adds a table to the DB, we see it
            without a config restart.
        """
        source = self._source_registry.get_sql(source_name)
        if source is None:
            raise ValueError(f"SQL source '{source_name}' not found in registry.")

        tools_created = 0

        # 1. Generic execute_read_query tool
        self._register_execute_query_tool(source)
        tools_created += 1

        # 2. Per-table query tools
        for table in source.tables:
            self._register_table_query_tool(source, table)
            tools_created += 1

        # 3. Schema description tool
        self._register_describe_schema_tool(source)
        tools_created += 1

        # 4. Auto-create a toolset grouping
        all_tool_names = [
            f"{source_name}.execute_read_query",
            *[f"{source_name}.query_{t}" for t in source.tables],
            f"{source_name}.describe_schema",
        ]
        self.register_toolset(
            Toolset(
                name=f"{source_name}_data",
                tool_names=all_tool_names,
                description=f"Data tools for {source_name} ({source.source_type})",
            )
        )

        logger.info(
            "sql_tools_generated",
            source=source_name,
            tools_count=tools_created,
        )
        return tools_created

    def _register_execute_query_tool(self, source: SQLSource) -> None:
        """Register the generic read-only SQL execution tool."""
        from sqlalchemy import text

        async def handler(query: str = "", limit: int = 100) -> str:
            if not query:
                return "Error: No query provided."
            if not _is_read_only(query):
                return "Error: Only read-only SELECT queries are allowed."
            try:
                with source.engine.connect() as conn:
                    result = conn.execute(text(query))
                    if result.returns_rows:
                        columns = list(result.keys())
                        rows = [dict(zip(columns, row, strict=False)) for row in result.fetchmany(limit)]
                        return json.dumps(
                            {"columns": columns, "rows": rows, "count": len(rows), "truncated": len(rows) >= limit},
                            default=str,
                        )
                    return "Query executed (no rows returned)."
            except Exception as e:
                return f"Database Error: {e}"

        self.register(
            MCPTool(
                manifest=ToolManifest(
                    name=f"{source.name}.execute_read_query",
                    description=f"Execute a read-only SQL query on {source.name}.",
                    source_name=source.name,
                    annotations=ToolAnnotations.read_only(),
                    parameters=[
                        {"name": "query", "type": "string", "description": "SQL SELECT statement."},
                        {"name": "limit", "type": "integer", "description": "Max rows (default 100)."},
                    ],
                ),
                handler=handler,
            )
        )

    def _register_table_query_tool(self, source: SQLSource, table: str) -> None:
        """Register a parameterized query tool for a specific table."""
        from sqlalchemy import inspect as sa_inspect
        from sqlalchemy import text

        insp = sa_inspect(source.engine)
        reflected_cols = [c["name"] for c in insp.get_columns(table, schema=source.schema)]

        async def handler(
            columns: str = "",
            where_column: str = "",
            where_value: str = "",
            limit: int = 50,
        ) -> str:
            if columns:
                requested = [c.strip() for c in columns.split(",")]
                invalid = [c for c in requested if c not in reflected_cols]
                if invalid:
                    return f"Error: Invalid columns: {invalid}. Valid: {reflected_cols}"
                col_str = ", ".join(requested)
            else:
                col_str = "*"

            sql = f"SELECT {col_str} FROM {source.schema}.{table}"
            params: dict[str, Any] = {}

            if where_column and where_value:
                if where_column not in reflected_cols:
                    return f"Error: Invalid filter column '{where_column}'."
                sql += f" WHERE {where_column} = :filter_value"
                params["filter_value"] = where_value

            sql += " LIMIT :row_limit"
            params["row_limit"] = limit

            try:
                with source.engine.connect() as conn:
                    result = conn.execute(text(sql), params)
                    col_names = list(result.keys())
                    rows = [dict(zip(col_names, row, strict=False)) for row in result.fetchall()]
                    return json.dumps(
                        {"table": table, "columns": col_names, "rows": rows, "count": len(rows)},
                        default=str,
                    )
            except Exception as e:
                return f"Database Error: {e}"

        self.register(
            MCPTool(
                manifest=ToolManifest(
                    name=f"{source.name}.query_{table}",
                    description=f"Query the '{table}' table in {source.name} with optional filtering.",
                    source_name=source.name,
                    annotations=ToolAnnotations.read_only(),
                    parameters=[
                        {
                            "name": "columns",
                            "type": "string",
                            "description": "Comma-separated column names (default: all).",
                        },
                        {"name": "where_column", "type": "string", "description": "Column name for WHERE filter."},
                        {"name": "where_value", "type": "string", "description": "Value to filter by."},
                        {"name": "limit", "type": "integer", "description": "Max rows (default 50)."},
                    ],
                ),
                handler=handler,
            )
        )

    def _register_describe_schema_tool(self, source: SQLSource) -> None:
        """Register a schema introspection tool."""
        from sqlalchemy import inspect as sa_inspect

        async def handler() -> str:
            insp = sa_inspect(source.engine)
            manifest: dict[str, Any] = {}
            for t in source.tables:
                cols = insp.get_columns(t, schema=source.schema)
                manifest[t] = [{"name": c["name"], "type": str(c["type"]), "nullable": c["nullable"]} for c in cols]
            return json.dumps(manifest, indent=2)

        self.register(
            MCPTool(
                manifest=ToolManifest(
                    name=f"{source.name}.describe_schema",
                    description=f"List all tables and columns available in {source.name}.",
                    source_name=source.name,
                    annotations=ToolAnnotations.read_only(),
                ),
                handler=handler,
            )
        )
