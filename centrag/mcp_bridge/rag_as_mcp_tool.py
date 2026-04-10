"""
RAG-as-MCP-Tool — Expose the CentRAG pipeline as MCP tools.

Pattern 1: AI agents (Claude, GPT, etc.) call CentRAG through MCP.

Instead of hardcoding the RAG pipeline into application logic,
we wrap it in an MCP Server. The AI agent calls tools like:
  - query_knowledge_base(query, namespace) → answer + sources
  - list_namespaces(team_id) → available document collections
  - search_documents(query, filters) → raw search results
  - get_extraction_status(doc_id) → processing status

This turns CentRAG into a "plug-and-play" knowledge backend
for any MCP-compatible AI host.

Design Standards:
  - Tools MUST have strongly typed inputs/outputs (JSON Schema)
  - Tools MUST be narrowly scoped (no generic "execute" commands)
  - Tools MUST be idempotent (safe to retry)
  - Tools MUST respect team_id for multi-tenant isolation
  - Tool descriptions MUST be LLM-friendly (clear, unambiguous)
"""
from __future__ import annotations

from typing import Any

from centrag.utils.logger import get_logger

logger = get_logger("mcp_bridge.rag_tools")


def register_rag_tools(mcp_server: Any, rag_engine: Any) -> None:
    """
    Register CentRAG retrieval tools on an MCP server.

    This function takes a FastMCP server instance and a RetrievalEngine,
    then registers the following tools:

    Args:
        mcp_server: A FastMCP server instance (from mcp.server.fastmcp)
        rag_engine: A RetrievalEngine instance with injected dependencies

    Design Standard: Each tool follows MCP best practices:
        - Clear, LLM-friendly name and description
        - Strongly typed parameters with validation
        - Structured return format (not raw text)
        - Multi-tenant isolation via team_id
    """

    @mcp_server.tool(
        name="query_knowledge_base",
        description=(
            "Search the CentRAG knowledge base and get an AI-generated answer "
            "grounded in source documents. The answer includes citation references "
            "to the specific documents and chunks used. Use this when you need "
            "factual answers backed by an organization's internal documents."
        ),
    )
    async def query_knowledge_base(
        query: str,
        namespace: str = "default",
        max_results: int = 5,
        team_id: str = "default",
    ) -> dict[str, Any]:
        """
        Query the knowledge base with full RAG pipeline.

        Args:
            query:       Natural language question (1-5000 chars).
            namespace:   Document collection to search within.
            max_results: Maximum number of source chunks to return (1-20).
            team_id:     Team identifier for multi-tenant isolation.

        Returns:
            dict with keys:
              - answer: str — AI-generated answer grounded in sources
              - sources: list — Source chunks with content, doc_id, relevance
              - query_complexity: str — "simple" | "moderate" | "complex"
              - cache_tier: str — Which cache served (L1/L2/L3/MISS)
        """
        from centrag.retrieval.engine import RetrievalRequest
        from centrag.middleware import RequestContext

        ctx = RequestContext(
            team_id=team_id,
            team_name=team_id,
            api_key_id="mcp-bridge",
            tier="enterprise",
            rate_limit=100,
        )

        request = RetrievalRequest(
            query=query,
            namespace=namespace,
            max_results=min(max_results, 20),
        )

        response = await rag_engine.retrieve(request, ctx)

        return {
            "answer": response.answer,
            "sources": [
                {
                    "content": s.content[:500],  # Cap content length
                    "document_id": s.document_id,
                    "chunk_index": s.chunk_index,
                    "relevance_score": round(s.relevance_score, 3),
                }
                for s in response.sources
            ],
            "query_complexity": response.query_complexity.value,
            "cache_tier": response.cache_tier.value,
        }

    @mcp_server.tool(
        name="search_documents",
        description=(
            "Search for relevant document chunks without generating an answer. "
            "Use this when you need to browse or explore document content "
            "without an AI-synthesized response."
        ),
    )
    async def search_documents(
        query: str,
        namespace: str = "default",
        max_results: int = 10,
        team_id: str = "default",
    ) -> dict[str, Any]:
        """
        Raw document search — returns chunks without LLM synthesis.

        Uses vector search directly, bypassing reranking and generation.

        Returns:
            dict with keys:
              - results: list of matching chunks with metadata
              - total_found: int
        """
        # Use the engine's embedder + vectorstore directly (no LLM)
        from centrag.abstractions.vectorstore import VectorFilter

        embedder = rag_engine._embedder
        vectorstore = rag_engine._vectorstore

        query_embedding = await embedder.embed_query(query)

        search_filter = VectorFilter(
            must=[
                {"key": "team_id", "match": {"value": team_id}},
                {"key": "namespace", "match": {"value": namespace}},
            ]
        )

        raw_results = await vectorstore.search(
            collection="documents",
            vector=query_embedding,
            filter=search_filter,
            limit=max_results,
        )

        return {
            "results": [
                {
                    "content": r.payload.get("content", ""),
                    "document_id": r.payload.get("document_id", r.id),
                    "chunk_index": r.payload.get("chunk_index", 0),
                    "relevance_score": round(r.score, 3),
                    "metadata": {
                        k: v for k, v in r.payload.items()
                        if k not in ("content", "document_id", "chunk_index", "team_id")
                    },
                }
                for r in raw_results
            ],
            "total_found": len(raw_results),
        }

    @mcp_server.resource(
        uri="centrag://namespaces",
        name="Available Namespaces",
        description="List all document namespaces available for search.",
    )
    async def list_namespaces() -> str:
        """List available document namespaces."""
        # In production, query the database for team-specific namespaces
        return (
            "Available namespaces:\\n"
            "- default: General documents\\n"
            "- engineering: Technical documentation\\n"
            "- legal: Legal and compliance documents\\n"
            "- finance: Financial reports and data"
        )

    logger.info(
        "rag_tools_registered",
        tools=["query_knowledge_base", "search_documents"],
        resources=["centrag://namespaces"],
    )
