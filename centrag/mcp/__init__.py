"""
CentRAG MCP — Dynamic MCP Integration Layer.

Components:
    - SourceRegistry: Decoupled connection management for databases.
    - ToolRegistry: Declarative tool definitions with annotations and toolsets.
    - ConfigLoader: YAML-based declarative configuration parser.
    - DynamicSQLMCPFactory: Legacy on-the-fly SQL tool generation.
    - MCPProcessManager: Lifecycle management for external MCP servers.
    - MCPBridge: Unified registry coordinating internal, external, and legacy servers.

Architecture:
    This layer follows the "Source/Tool Separation" pattern stolen from
    Google's mcp-toolbox to enable enterprise-grade, multi-tenant database
    intelligence with declarative configuration support.
"""

from centrag.mcp.bridge import MCPBridge
from centrag.mcp.config_loader import get_prebuilt_config, list_prebuilt_configs, load_mcp_config
from centrag.mcp.dynamic_db_factory import DynamicSQLMCPFactory
from centrag.mcp.process_manager import MCPProcessManager
from centrag.mcp.source_registry import SourceRegistry, SQLSource, SQLSourceConfig
from centrag.mcp.tool_registry import MCPTool, ToolAnnotations, ToolManifest, ToolRegistry, Toolset

__all__ = [
    "SourceRegistry",
    "SQLSource",
    "SQLSourceConfig",
    "ToolRegistry",
    "MCPTool",
    "Toolset",
    "ToolAnnotations",
    "ToolManifest",
    "load_mcp_config",
    "list_prebuilt_configs",
    "get_prebuilt_config",
    "MCPProcessManager",
    "MCPBridge",
    "DynamicSQLMCPFactory",
]
