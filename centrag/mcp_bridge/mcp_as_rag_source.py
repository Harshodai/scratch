"""
MCP-as-RAG-Source — Use MCP tools as live data sources in the RAG pipeline.

Pattern 2: The retrieval engine calls MCP tools to fetch live data
during the retrieval process. Results are injected into the LLM context
alongside vector search results.

Example use case:
  User asks: "Compare last quarter's revenue from the GOS database
              with the projections in our internal reports."

  Pipeline:
    1. Vector search → finds internal report chunks
    2. MCP tool call → queries GOS DB for live revenue data
    3. Both are injected into LLM context → synthesized answer

Design Standards:
  - MCPDataSource is protocol-compatible with the retrieval engine
  - Results are converted to SourceChunk format for uniform handling
  - Timeouts prevent MCP calls from blocking the pipeline
  - Errors are gracefully handled (pipeline continues without MCP data)
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger("mcp_bridge.data_source")


@dataclass(frozen=True)
class MCPSourceResult:
    """Result from calling an MCP tool as a data source."""
    content: str
    tool_name: str
    source_server: str
    metadata: dict[str, Any] = field(default_factory=dict)


class MCPDataSource:
    """
    Wraps MCP tool calls as data sources for the RAG pipeline.

    Usage in RetrievalEngine:
        mcp_source = MCPDataSource(mcp_client)
        
        # During retrieval, fetch live data:
        live_data = await mcp_source.fetch_context(
            query="revenue last quarter",
            tool_name="query_gosdb",
            params={"query": "SELECT revenue FROM quarterly_reports WHERE quarter='Q4'"},
        )
        
        # Inject into context alongside vector search results
        context = vector_results + live_data

    Design:
        - Timeout protection: MCP calls have configurable timeout
        - Graceful degradation: if MCP fails, pipeline continues
        - Result format: matches SourceChunk interface for uniformity
    """

    def __init__(
        self,
        mcp_client: Any = None,
        default_timeout: float = 10.0,
    ) -> None:
        """
        Args:
            mcp_client: An MCP client session (from mcp.client.session).
                        If None, all fetch calls return empty results.
            default_timeout: Max seconds to wait for MCP tool response.
        """
        self._client = mcp_client
        self._timeout = default_timeout

    async def fetch_context(
        self,
        query: str,
        tool_name: str,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> list[MCPSourceResult]:
        """
        Call an MCP tool and return results as context chunks.

        Args:
            query:     The user's original query (for logging/audit).
            tool_name: Name of the MCP tool to call.
            params:    Tool parameters.
            timeout:   Override default timeout for this call.

        Returns:
            List of MCPSourceResult (may be empty on error/timeout).
        """
        if self._client is None:
            logger.debug("mcp_client_not_configured", tool=tool_name)
            return []

        effective_timeout = timeout or self._timeout

        try:
            result = await asyncio.wait_for(
                self._call_tool(tool_name, params or {}),
                timeout=effective_timeout,
            )

            logger.info(
                "mcp_data_fetched",
                tool=tool_name,
                result_length=len(str(result)),
                query_preview=query[:50],
            )

            # Convert MCP result to context chunks
            return self._parse_result(result, tool_name)

        except asyncio.TimeoutError:
            logger.warning(
                "mcp_call_timeout",
                tool=tool_name,
                timeout=effective_timeout,
            )
            return []
        except Exception as e:
            logger.error(
                "mcp_call_error",
                tool=tool_name,
                error=str(e),
            )
            return []

    async def _call_tool(
        self,
        tool_name: str,
        params: dict[str, Any],
    ) -> Any:
        """
        Call an MCP tool via the client session.

        In the real MCP SDK, this would be:
            result = await self._client.call_tool(tool_name, params)
        """
        # Real implementation:
        if hasattr(self._client, "call_tool"):
            return await self._client.call_tool(tool_name, params)

        # Fallback for testing
        logger.warning("mcp_client_no_call_tool", tool=tool_name)
        return None

    def _parse_result(
        self,
        result: Any,
        tool_name: str,
    ) -> list[MCPSourceResult]:
        """Convert raw MCP tool result into MCPSourceResult chunks."""
        if result is None:
            return []

        # MCP results come as content blocks
        chunks: list[MCPSourceResult] = []

        if hasattr(result, "content"):
            for block in result.content:
                if hasattr(block, "text"):
                    chunks.append(
                        MCPSourceResult(
                            content=block.text,
                            tool_name=tool_name,
                            source_server="mcp_enterprise",
                            metadata={"type": "mcp_tool_result"},
                        )
                    )
        elif isinstance(result, str):
            chunks.append(
                MCPSourceResult(
                    content=result,
                    tool_name=tool_name,
                    source_server="mcp_enterprise",
                )
            )
        elif isinstance(result, dict):
            # Handle dict results (e.g., from query_gosdb)
            content = "\n".join(
                f"{k}: {v}" for k, v in result.items()
                if not k.startswith("_")
            )
            chunks.append(
                MCPSourceResult(
                    content=content,
                    tool_name=tool_name,
                    source_server="mcp_enterprise",
                    metadata=result,
                )
            )

        return chunks

    async def list_available_tools(self) -> list[dict[str, str]]:
        """List tools available from the connected MCP server."""
        if self._client is None:
            return []

        try:
            if hasattr(self._client, "list_tools"):
                tools_result = await self._client.list_tools()
                return [
                    {
                        "name": t.name,
                        "description": t.description or "",
                    }
                    for t in tools_result.tools
                ]
        except Exception as e:
            logger.error("mcp_list_tools_error", error=str(e))

        return []
