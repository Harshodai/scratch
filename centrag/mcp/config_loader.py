"""
MCP Config Loader — Declarative YAML-based tool configuration.

The WHY:
    STOLEN from googleapis/mcp-toolbox ``internal/server/config.go``.

    The Toolbox's config parser uses a ``kind/name/type`` dispatch pattern:
    - ``kind`` determines the resource category (source, tool, toolset)
    - ``type`` selects the concrete implementation (postgres, sqlite, etc.)
    - ``name`` provides a unique identifier for cross-referencing

    This is genuinely better than CentRAG's current programmatic-only
    approach (``mcp_internal_dbs`` dict in Settings). It allows DevOps
    teams to configure MCP tools via YAML without touching Python code,
    while CentRAG still enforces ``team_id`` isolation at the engine level.

    Key design from ``config.go:149-238``:
    ```go
    switch kind {
    case "source": c, err = UnmarshalYAMLSourceConfig(ctx, name, resource)
    case "tool":   c, err = UnmarshalYAMLToolConfig(ctx, name, resource)
    case "toolset": c, err = UnmarshalYAMLToolsetConfig(ctx, name, resource)
    }
    ```

Pattern: FACTORY METHOD + DISPATCH (from Toolbox ``UnmarshalResourceConfig()``)
SOLID: OCP — new YAML ``kind`` values require zero changes here.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml  # PyYAML — already in our dependencies

from centrag.mcp.source_registry import SourceRegistry, SQLSourceConfig
from centrag.mcp.tool_registry import (
    MCPTool,
    ToolAnnotations,
    ToolManifest,
    ToolRegistry,
    Toolset,
)
from centrag.utils.logger import get_logger

logger = get_logger("mcp.config_loader")

# ---------------------------------------------------------------------------
# Environment variable substitution (mirrors Toolbox's ${VAR:default} syntax)
# ---------------------------------------------------------------------------
_ENV_PATTERN = re.compile(r"\$\{([^}]+)\}")


def _resolve_env_vars(value: str) -> str:
    """Resolve ``${VAR}`` and ``${VAR:default}`` patterns in config values.

    Stolen from Toolbox's YAML env-var interpolation seen in prebuilt
    configs (e.g. ``${POSTGRES_HOST:localhost}``).
    """

    def replacer(match: re.Match) -> str:
        expr = match.group(1)
        if ":" in expr:
            var_name, default = expr.split(":", 1)
            return os.environ.get(var_name.strip(), default.strip())
        return os.environ.get(expr.strip(), "")

    return _ENV_PATTERN.sub(replacer, value)


def _resolve_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Recursively resolve environment variables in a config dict."""
    resolved: dict[str, Any] = {}
    for key, value in data.items():
        if isinstance(value, str):
            resolved[key] = _resolve_env_vars(value)
        elif isinstance(value, dict):
            resolved[key] = _resolve_dict(value)
        elif isinstance(value, list):
            resolved[key] = [_resolve_env_vars(v) if isinstance(v, str) else v for v in value]
        else:
            resolved[key] = value
    return resolved


# ---------------------------------------------------------------------------
# YAML Config Parser — mirrors Toolbox ``UnmarshalResourceConfig()``
# ---------------------------------------------------------------------------
def load_mcp_config(
    config_path: str | Path,
    source_registry: SourceRegistry,
    tool_registry: ToolRegistry,
) -> dict[str, Any]:
    """Parse a ``mcp_tools.yaml`` file and register all sources, tools, toolsets.

    Mirrors Toolbox ``config.go:149-238`` — reads YAML, dispatches by
    ``sources/tools/toolsets`` top-level keys, initializes everything.

    Config format (adapted from Toolbox's prebuilt config pattern):

        sources:
          my-postgres:
            kind: postgres
            connection_string: ${DATABASE_URL}
            schema: public
            read_only: true
        tools:
          custom_report:
            kind: sql-query
            source: my-postgres
            description: "Run the monthly report query."
            statement: "SELECT * FROM monthly_reports LIMIT 100"
        toolsets:
          analyst:
            - custom_report
            - my-postgres.execute_read_query
            - my-postgres.describe_schema

    Returns:
        Summary dict with counts of registered resources.
    """
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"MCP config file not found: {path}")

    raw = path.read_text(encoding="utf-8")
    config = yaml.safe_load(raw)
    if not isinstance(config, dict):
        raise ValueError(f"Invalid MCP config format in {path}")

    config = _resolve_dict(config)

    summary: dict[str, Any] = {"sources": 0, "tools": 0, "toolsets": 0}

    # 1. Parse Sources (mirrors Toolbox ``case "source":``)
    if "sources" in config:
        for name, source_def in config["sources"].items():
            kind = source_def.get("kind", "postgres")

            if kind.startswith("aws-"):
                from centrag.mcp.source_registry import AWSSourceConfig

                source_config = AWSSourceConfig(
                    name=name,
                    region=source_def.get("region", "us-east-1"),
                    role_arn=source_def.get("role_arn"),
                    session_duration=source_def.get("session_duration", 3600),
                    endpoint_url=source_def.get("endpoint_url"),
                    kind=kind,
                    options=source_def.get("options", {}),
                )
                source = source_registry.add(source_config)

                # Register the exact AWS tools based on the sub-kind
                if kind == "aws-s3":
                    from centrag.mcp.aws.s3 import generate_s3_tools

                    for t in generate_s3_tools(source):
                        tool_registry.register(t)
                elif kind == "aws-dynamodb":
                    from centrag.mcp.aws.dynamodb import generate_dynamodb_tools

                    for t in generate_dynamodb_tools(source):
                        tool_registry.register(t)
                elif kind == "aws-athena":
                    from centrag.mcp.aws.athena import generate_athena_tools

                    for t in generate_athena_tools(source):
                        tool_registry.register(t)
                elif kind == "aws-emr":
                    from centrag.mcp.aws.emr import generate_emr_tools

                    for t in generate_emr_tools(source):
                        tool_registry.register(t)
            else:
                source_config = SQLSourceConfig(
                    name=name,
                    connection_string=source_def.get("connection_string", ""),
                    kind=kind,
                    schema=source_def.get("schema"),
                    read_only=source_def.get("read_only", True),
                )
                source_registry.add(source_config)
                # Auto-generate tools from schema reflection
                tool_registry.generate_sql_tools(name)

            summary["sources"] += 1

    # 2. Parse Custom Tools (mirrors Toolbox ``case "tool":``)
    if "tools" in config:
        for name, tool_def in config["tools"].items():
            _parse_custom_tool(name, tool_def, source_registry, tool_registry)
            summary["tools"] += 1

    # 3. Parse Toolsets (mirrors Toolbox ``case "toolset":``)
    if "toolsets" in config:
        for name, tool_names in config["toolsets"].items():
            if isinstance(tool_names, dict):
                # Toolbox-style: toolset has description + tools list
                tools_list = tool_names.get("tools", [])
                desc = tool_names.get("description", "")
            elif isinstance(tool_names, list):
                tools_list = tool_names
                desc = ""
            else:
                logger.warning("invalid_toolset_format", name=name)
                continue

            tool_registry.register_toolset(Toolset(name=name, tool_names=tools_list, description=desc))
            summary["toolsets"] += 1

    logger.info(
        "mcp_config_loaded",
        path=str(path),
        sources=summary["sources"],
        tools=summary["tools"],
        toolsets=summary["toolsets"],
    )

    return summary


def _parse_custom_tool(
    name: str,
    tool_def: dict[str, Any],
    source_registry: SourceRegistry,
    tool_registry: ToolRegistry,
) -> None:
    """Parse a custom tool definition from YAML.

    Supports ``kind: sql-query`` for static SQL statement tools
    (like Toolbox's ``postgres-sql`` kind in the prebuilt config).
    """
    from sqlalchemy import text

    kind = tool_def.get("kind", "sql-query")
    source_name = tool_def.get("source", "")
    description = tool_def.get("description", f"Custom tool: {name}")
    statement = tool_def.get("statement", "")

    # Validate source exists
    source = source_registry.get_sql(source_name)
    if source is None:
        logger.error("custom_tool_missing_source", tool=name, source=source_name)
        return

    # Determine annotations
    annotations = ToolAnnotations.read_only()
    if tool_def.get("destructive", False):
        annotations = ToolAnnotations.destructive()

    # Parse parameters (mirrors Toolbox ``parameters`` field)
    param_defs = tool_def.get("parameters", [])

    if kind == "sql-query" and statement:
        # Static SQL tool — the statement is predefined in config
        async def handler(**kwargs: Any) -> str:
            try:
                with source.engine.connect() as conn:
                    result = conn.execute(text(statement), kwargs)
                    if result.returns_rows:
                        columns = list(result.keys())
                        rows = [dict(zip(columns, row, strict=False)) for row in result.fetchmany(100)]
                        return __import__("json").dumps(
                            {"columns": columns, "rows": rows, "count": len(rows)},
                            default=str,
                        )
                    return "Query executed (no rows returned)."
            except Exception as e:
                return f"Database Error: {e}"

        tool_registry.register(
            MCPTool(
                manifest=ToolManifest(
                    name=name,
                    description=description,
                    source_name=source_name,
                    annotations=annotations,
                    parameters=param_defs,
                ),
                handler=handler,
            )
        )
    else:
        logger.warning("unsupported_tool_kind", tool=name, kind=kind)


# ---------------------------------------------------------------------------
# Prebuilt Config Loader — mirrors Toolbox ``prebuiltconfigs/prebuiltconfigs.go``
# ---------------------------------------------------------------------------
_TEMPLATES_DIR = Path(__file__).parent / "templates"


def list_prebuilt_configs() -> list[str]:
    """List available prebuilt config templates.

    Mirrors Toolbox ``prebuiltconfigs.GetPrebuiltSources()`` which
    returns available prebuilt YAML template names.
    """
    if not _TEMPLATES_DIR.exists():
        return []
    return [f.stem for f in _TEMPLATES_DIR.glob("*.yaml")]


def get_prebuilt_config(name: str) -> str | None:
    """Get the raw YAML content of a prebuilt config template.

    Mirrors Toolbox ``prebuiltconfigs.Get()`` which looks up
    embedded YAML files by source type name.
    """
    path = _TEMPLATES_DIR / f"{name}.yaml"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return None
