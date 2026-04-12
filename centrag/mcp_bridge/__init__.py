# centrag/mcp_bridge/__init__.py
"""
MCP Bridge — Integration layer between RAG and MCP.

Three integration patterns:
  1. RAG-as-MCP-Tool:  Expose RAG pipeline as MCP tools for AI agents
  2. MCP-as-RAG-Source: Use MCP servers as live data sources in RAG
  3. Hybrid Orchestrator: Agentic router that combines both

This bridge enables CentRAG to participate in the MCP ecosystem
while maintaining clean boundaries.
"""

from centrag.mcp_bridge.mcp_as_rag_source import MCPDataSource
from centrag.mcp_bridge.rag_as_mcp_tool import register_rag_tools

__all__ = ["register_rag_tools", "MCPDataSource"]
