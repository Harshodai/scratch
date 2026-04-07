# RAG + MCP Integration Guide

## Why Combine RAG and MCP?

| RAG Alone | MCP Alone | RAG + MCP |
|---|---|---|
| Searches static documents | Calls live tools/APIs | Searches docs AND queries live data |
| Read-only knowledge | Bidirectional actions | Full-spectrum intelligence |
| Fixed retrieval pipeline | Dynamic tool selection | Adaptive, agentic retrieval |
| Single data source type | Multiple data sources via protocol | Unified access to everything |

**RAG gives you grounded knowledge. MCP gives you live connectivity. Together, they give you an AI system that knows your documents AND your databases.**

---

## Three Integration Patterns

### Pattern 1: RAG-as-MCP-Tool

**Expose your RAG pipeline to AI agents via MCP.**

```
┌──────────────┐      ┌──────────────┐      ┌──────────────────────┐
│  AI Agent    │─────▶│  MCP Client  │─────▶│  RAG MCP Server      │
│  (Claude)    │      │              │      │                      │
│              │◀─────│              │◀─────│  Tools:              │
│  "What does  │      │              │      │  - query_knowledge   │
│   our policy │      └──────────────┘      │  - search_documents  │
│   say about  │                            │  - list_namespaces   │
│   remote     │                            └──────────┬───────────┘
│   work?"     │                                       │
└──────────────┘                                       ▼
                                              ┌──────────────────┐
                                              │  RAG Pipeline     │
                                              │  Embed → Search  │
                                              │  → Rerank → LLM  │
                                              └──────────────────┘
```

**When to use:**
- You want AI agents to access your knowledge base
- You're building a multi-tool agent that needs both knowledge AND action tools
- You want to standardize how multiple AI apps access your docs

**Implementation:** See `centrag/mcp_bridge/rag_as_mcp_tool.py`

```python
from centrag.mcp_bridge.rag_as_mcp_tool import register_rag_tools

mcp_server = FastMCP(name="centrag-knowledge", version="1.0.0")
register_rag_tools(mcp_server, rag_engine)
```

---

### Pattern 2: MCP-as-RAG-Source

**Use MCP tools as live data sources inside the RAG pipeline.**

```
┌──────────────┐      ┌──────────────────┐      ┌──────────────────┐
│  User API    │─────▶│  RAG Engine      │─────▶│  Vector Store    │
│  Request     │      │  (retrieval)     │      │  (static docs)   │
│              │      │                  │      └──────────────────┘
│  "Compare    │      │                  │─────▶┌──────────────────┐
│   Q4 revenue │      │  Combines both   │      │  MCP Client      │
│   with our   │      │  into context    │      │  → query_gosdb   │
│   forecasts" │      │                  │      │  (live DB data)  │
└──────────────┘      └──────────────────┘      └──────────────────┘
                               │
                               ▼
                      ┌──────────────────┐
                      │  LLM generates   │
                      │  answer using    │
                      │  BOTH sources    │
                      └──────────────────┘
```

**When to use:**
- Queries need both document knowledge AND live database data
- You want "compare internal reports with live records"
- Real-time data enrichment of document-based answers

**Implementation:** See `centrag/mcp_bridge/mcp_as_rag_source.py`

```python
from centrag.mcp_bridge.mcp_as_rag_source import MCPDataSource

mcp_source = MCPDataSource(mcp_client=client, default_timeout=10.0)

# During retrieval, fetch live data
live_data = await mcp_source.fetch_context(
    query="Q4 revenue",
    tool_name="query_gosdb",
    params={"query": "SELECT revenue FROM quarterly_reports WHERE q='Q4'"},
)

# Inject into RAG context alongside vector search results
context = vector_results + [chunk.content for chunk in live_data]
```

---

### Pattern 3: Hybrid Orchestrator

**Agentic router that decides the optimal retrieval path.**

```
┌──────────────┐
│  User Query  │
└──────┬───────┘
       │
       ▼
┌──────────────────────────────┐
│  Intent Classifier           │
│  (LLM.classify_complexity)   │
│                              │
│  Routes to:                  │
│  ├─ "simple factual"  ──────┼──────▶ Pure RAG (cached docs)
│  ├─ "needs live data"  ─────┼──────▶ Pure MCP (database query)
│  └─ "complex multi-src" ────┼──────▶ RAG + MCP (combined)
└──────────────────────────────┘
```

**Decision Logic:**

| Query Type | Example | Path |
|---|---|---|
| **Simple factual** | "What is our refund policy?" | RAG only (vector search) |
| **Live data** | "What is current inventory count?" | MCP only (query_dynamodb) |
| **Comparative** | "Compare policy with actual practice" | RAG + MCP combined |
| **Analytical** | "Trend analysis of Q1-Q4 revenue" | MCP (query_athena) |

**This pattern uses the existing `classify_complexity()` method** in `LLMProtocol` to route queries. The `RetrievalEngine` already supports this — Pattern 3 extends it to include MCP routing.

---

## Complete Example: Wiring Everything Together

```python
"""
Full example: CentRAG with MCP bridge integration.
"""
from mcp.server.fastmcp import FastMCP
from centrag.retrieval.engine import RetrievalEngine
from centrag.guardrails.engine import GuardrailEngine, GuardrailsConfig
from centrag.cache.orchestrator import TieredCacheOrchestrator
from centrag.cache.l1_memory import L1InMemoryCache
from centrag.mcp_bridge.rag_as_mcp_tool import register_rag_tools


# 1. Build guardrails
guardrails = GuardrailEngine(GuardrailsConfig(
    enable_prompt_injection_detection=True,
    enable_output_pii_redaction=True,
))

# 2. Build cache
cache = TieredCacheOrchestrator(tiers=[
    L1InMemoryCache(maxsize=512, ttl_seconds=300),
])

# 3. Build RAG engine with guardrails injected
engine = RetrievalEngine(
    embedder_factory=lambda: my_embedder,
    vectorstore_factory=lambda: my_vectorstore,
    reranker_factory=lambda: my_reranker,
    llm_factory=lambda: my_llm,
    cache=cache,
    input_rails=guardrails.input_rails,
    output_rails=guardrails.output_rails,
)

# 4. Expose as MCP tools
mcp_server = FastMCP(
    name="centrag-knowledge",
    version="1.0.0",
    description="CentRAG knowledge base — search internal documents.",
)
register_rag_tools(mcp_server, engine)

# 5. Run
mcp_server.run()
```

---

## Data Flow Diagram

```
User Query
    │
    ▼
┌───────────────────────────────────────────────────────────────┐
│                     CentRAG Platform                          │
│                                                               │
│  ┌─────────────┐   ┌──────────────┐   ┌──────────────────┐  │
│  │ Input Rails  │──▶│ RAG Engine   │──▶│ Output Rails     │  │
│  │ (guardrails) │   │              │   │ (PII, confidence)│  │
│  └─────────────┘   │  ┌────────┐  │   └──────────────────┘  │
│                     │  │ Cache  │  │                          │
│                     │  │L1→L2→L3│  │                          │
│                     │  └────────┘  │                          │
│                     │              │                          │
│                     │  ┌────────┐  │                          │
│                     │  │ Vector │  │   ┌──────────────────┐  │
│                     │  │ Search │  │   │  MCP Bridge      │  │
│                     │  └────────┘  │   │                  │  │
│                     │              │──▶│ Pattern 2: Live   │  │
│                     │  ┌────────┐  │   │ data from MCP    │  │
│                     │  │ Memory │  │   │ servers           │  │
│                     │  └────────┘  │   └──────────────────┘  │
│                     └──────────────┘                          │
│                                                               │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  MCP Server Layer (Pattern 1: RAG as MCP tools)       │  │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌─────────┐  │  │
│  │  │ query_kb │ │search_doc│ │ list_ns  │ │ GOS DB  │  │  │
│  │  └──────────┘ └──────────┘ └──────────┘ └─────────┘  │  │
│  └────────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────────┘
```

---

## Key Takeaways

1. **RAG + MCP are complementary, not competing** — RAG handles static knowledge, MCP handles live connectivity
2. **Start with Pattern 1** (RAG-as-MCP-Tool) — it's the simplest and immediately useful
3. **Pattern 2** (MCP-as-RAG-Source) enables powerful hybrid queries
4. **Pattern 3** (Hybrid Orchestrator) is the highest-value pattern for enterprise use
5. **Guardrails apply to both** — input validation, PII redaction, and audit logging must cover both RAG and MCP data paths
