# AGENTS.md — CentRAG AI Agent Collaboration Guide

## Project Overview

**CentRAG** (Central Retrieval-Augmented Generation) is a production-grade, multi-tenant RAG platform built with FastAPI, designed for enterprise teams that need secure, observable, and extensible document intelligence.

This file serves as context for AI coding agents (Copilot, Cursor, Antigravity, Claude Code) working in this repository.

---

## Architecture Philosophy

### SOLID Principles (Strictly Enforced)

| Principle | How We Apply It |
|-----------|----------------|
| **Single Responsibility** | Each module does ONE thing. `engine.py` orchestrates, `models.py` defines schema, `pii.py` detects PII. |
| **Open/Closed** | Add new LLM providers by creating a new file in `implementations/` — never modify existing ones. |
| **Liskov Substitution** | Any `EmbedderProtocol` implementation (NoOp, Bedrock, OpenAI) is a drop-in replacement for another. |
| **Interface Segregation** | Separate protocols for Embedding, VectorStore, LLM, Reranking, Memory, Caching, Guardrails, Observability. |
| **Dependency Inversion** | The engine depends on `Protocols`, never on concrete classes. Wiring happens in `wiring.py`. |

### Design Patterns Used

| Pattern | Where | Why |
|---------|-------|-----|
| Strategy | `centrag/abstractions/*.py` | Swap implementations without changing callers |
| Composition Root | `centrag/wiring.py` | Single place to configure all dependencies |
| Repository | `centrag/models.py` | Entities define shape; repositories define access |
| Decorator | `centrag/observability/` | Wrap any operation with tracing/metrics |
| Tiered Cache | `centrag/cache/` | L1 (in-process) → L2 (Redis) fallthrough |
| Advisor Loop | `centrag/retrieval/engine.py` | CRAG pattern — corrective validation of context |
| Temporal Versioning | `centrag/memory/` | Facts are never overwritten, only superseded |

---

## Project Structure

```
centrag/                    # Core RAG platform
├── abstractions/           # Protocol definitions (contracts)
│   ├── cache.py            # CacheTier enum, CacheResult, CacheProtocol
│   ├── chunker.py          # ChunkerProtocol for text segmentation
│   ├── embedder.py         # EmbedderProtocol (embed_query, embed_documents)
│   ├── extractor.py        # ExtractorProtocol for document parsing
│   ├── guardrail.py        # InputRail, OutputRail, RailContext, GuardrailViolation
│   ├── llm.py              # LLMProtocol, LLMResponse, QueryComplexity
│   ├── memory.py           # MemoryProtocol, MemoryEntry, MemoryType
│   ├── reranker.py         # RerankerProtocol, RerankResult
│   └── vectorstore.py      # VectorStoreProtocol, VectorFilter, VectorResult
│
├── implementations/        # Concrete protocol implementations
│   ├── noop_embedder.py    # Hash-based deterministic embedder (dev/test)
│   ├── noop_vectorstore.py # In-memory vector store (dev/test)
│   ├── noop_llm.py         # Template-based LLM (dev/test)
│   ├── noop_reranker.py    # Keyword-overlap reranker (dev/test)
│   ├── bedrock_embedder.py # AWS Bedrock Titan V2 embeddings (production)
│   └── openai_embedder.py  # OpenAI text-embedding-3 (production)
│
├── cache/                  # Tiered caching subsystem
│   ├── l1_memory.py        # L1: In-process TTLCache with team-scoped invalidation
│   ├── l2_redis.py         # L2: Redis-backed distributed cache
│   ├── orchestrator.py     # TieredCacheOrchestrator (L1 → L2 fallthrough)
│   └── swr.py              # Stale-While-Revalidate async pattern
│
├── extraction/             # Document ingestion pipeline
│   ├── pipeline.py         # Orchestrates parse → chunk → embed → store
│   ├── parsers/            # Document format parsers
│   │   ├── base.py         # Base parser with common utilities
│   │   ├── pdf.py          # PDF extraction (PyMuPDF)
│   │   └── text.py         # Plain text / markdown parser
│   └── chunkers/           # Text chunking strategies
│       ├── fixed.py        # Fixed-size token chunks
│       ├── recursive.py    # Recursive character text splitter
│       ├── semantic.py     # Embedding-based semantic chunking
│       └── structure_aware.py  # Heading/section-aware chunking
│
├── guardrails/             # Input/output safety rails
│   ├── engine.py           # GuardrailEngine with composable rails
│   ├── pii.py              # PII detection and redaction (regex-based)
│   └── cost_tracker.py     # LLM cost tracking and budget gating
│
├── memory/                 # Cross-session memory (Zep/Graphiti-inspired)
│   └── in_memory_store.py  # Dict-based temporal memory (dev/test)
│
├── middleware/             # FastAPI middleware
│   ├── auth.py             # API key authentication + team resolution
│   └── slow_logger.py      # Slow request logging
│
├── mcp_bridge/             # Model Context Protocol integration
│   ├── rag_as_mcp_tool.py  # Expose CentRAG as an MCP tool
│   └── mcp_as_rag_source.py # Consume external MCP servers as RAG sources
│
├── observability/          # Metrics, tracing, cost tracking
│   ├── __init__.py         # Protocols: TracingProtocol, MetricsProtocol, CostTrackingProtocol
│   ├── console.py          # Zero-dependency console observers (dev)
│   └── otel_provider.py    # OpenTelemetry + Prometheus + Grafana (production, free)
│
├── retrieval/              # Core RAG pipeline
│   └── engine.py           # RetrievalEngine: embed → search → rerank → CRAG → generate
│
├── routes/                 # FastAPI route handlers
│   ├── documents.py        # Document upload/management endpoints
│   ├── health.py           # Health check and readiness probes
│   └── retrieve.py         # /v1/retrieve — main query endpoint
│
├── app.py                  # FastAPI application factory + lifespan
├── config.py               # Pydantic Settings (CENTRAG_ prefix)
├── models.py               # SQLAlchemy async models with RLS
└── wiring.py               # Composition Root — dependency injection

alembic/                    # Database migrations
├── env.py                  # Async migration environment
└── versions/
    └── 001_initial_schema.py  # Initial 6-table schema + RLS policies

mcp_enterprise_server/      # Standalone MCP server for enterprise tools
tests/                      # Unit tests (pytest + pytest-asyncio)
docs/                       # Architecture docs, audits, walkthroughs
```

---

## Key Conventions

### Adding a New Implementation

1. Create `centrag/implementations/your_provider.py`
2. Implement the relevant Protocol from `centrag/abstractions/`
3. Export from `centrag/implementations/__init__.py`
4. Wire in `centrag/wiring.py` (guarded by config flag)
5. Add tests in `tests/test_implementations.py`

### Configuration

All config uses Pydantic Settings with `CENTRAG_` prefix:
```bash
CENTRAG_DATABASE_URL=postgresql+asyncpg://...
CENTRAG_REDIS_URL=redis://localhost:6379/0
CENTRAG_QDRANT_URL=http://localhost:6333
CENTRAG_AWS_REGION=us-east-1
OPENAI_API_KEY=sk-...  # Read by openai SDK directly
```

### Error Handling

- **GuardrailViolation**: Raised by input/output rails, caught by the engine → 422 response
- **Infrastructure errors**: Caught in lifespan with graceful degradation
- **LLM errors**: Wrapped in LLMResponse with error metadata

### Testing

```bash
pip install pytest pytest-asyncio
pytest tests/ -v
```

All NoOp implementations are **deterministic** — same input always produces the same output. No mocking needed.

---

## Agent-Specific Notes

### For Copilot / Cursor
- Always check `centrag/abstractions/` before implementing anything
- Never add business logic to `models.py`
- Use `structlog` for logging, never `print()` or stdlib `logging`

### For Antigravity / Claude Code
- The composition root is `wiring.py` — change implementations there
- Free observability stack: Console → OTel+Prometheus+Grafana
- All cache operations must be team-scoped (never global invalidation)

### For Code Review Agents
- Verify new implementations satisfy their Protocol (runtime_checkable)
- Check for proper team isolation in any data access path
- Ensure frozen dataclasses have `to_dict()`/`from_dict()` if cached
