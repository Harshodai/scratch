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
| Decorator | `centrag/implementations/llm_gateway.py` | Wrap LLM with circuit breaker, cost tracking, latency |
| Tiered Cache | `centrag/cache/` | L1 (in-process) → L2 (Redis) fallthrough |
| Advisor Loop | `centrag/retrieval/engine.py` | CRAG pattern — corrective validation of context |
| Temporal Versioning | `centrag/memory/` | Facts are never overwritten, only superseded |
| Circuit Breaker | `centrag/implementations/llm_gateway.py` | Prevent cascading failures when LLM provider is down |
| Parent-Child | `centrag/extraction/chunkers/parent_child.py` | Small chunks for search, parent chunks for LLM context |

---

## Project Structure

```
centrag/                    # Core RAG platform
├── .github/                # Enterprise CI/CD pipelines (Tests, Linters, Security, Evals)
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
│   ├── qdrant_vectorstore.py # Production Qdrant client (lazy-loading)
│   ├── pageindex_tree.py   # VectifyAI PageIndex tree builder
│   ├── llm_gateway.py      # LLM proxy: circuit breaker + cost + latency
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
│   │   ├── base.py         # ParserRegistry (strategy pattern)
│   │   ├── pdf.py          # PDF extraction (PyMuPDF)
│   │   ├── text.py         # Plain text / markdown / HTML parser
│   │   └── csv_parser.py   # CSV/TSV with pandas-style streaming
│   └── chunkers/           # Text chunking strategies
│       ├── fixed.py        # Fixed-size token chunks
│       ├── recursive.py    # Recursive character text splitter
│       ├── semantic.py     # Embedding-based semantic chunking
│       ├── structure_aware.py  # Heading/section-aware chunking
│       └── parent_child.py # Parent (512t) + child (128t) indexing
│
├── guardrails/             # Input/output safety rails
│   ├── engine.py           # GuardrailEngine with composable rails
│   ├── pii.py              # PII detection + redaction (14 patterns)
│   └── cost_tracker.py     # LLM cost tracking and budget gating
│
├── memory/                 # Cross-session memory (Zep/Graphiti-inspired)
│   └── in_memory_store.py  # Dict-based temporal memory (dev/test)
│
├── middleware/             # FastAPI middleware
│   ├── auth.py             # API key authentication + team resolution
│   ├── slow_logger.py      # Slow request logging
│   └── rate_limiter.py     # Enterprise DDOS protection and tenant throttling
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
│   ├── engine.py           # RetrievalEngine: embed → search → rerank → CRAG → generate
│   ├── pageindex_retriever.py # VECTORLESS: LLM navigates tree index
│   ├── query_router.py     # Auto: pageindex vs vector vs hybrid
│   ├── hybrid.py           # Reciprocal Rank Fusion (k=60)
│   └── session.py          # Multi-turn conversation history
│
├── evaluation/             # Quality measurement
│   ├── dataset.py          # Golden test cases (TestCase + GoldenDataset)
│   ├── judges.py           # Faithfulness / Relevance / Coverage judges
│   ├── metrics.py          # Aggregate scoring + EvaluationReport
│   └── comparator.py       # Side-by-side path comparison
│
├── ingestion/              # Document upload pipeline
│   ├── service.py          # IngestionService (parse → clean → index)
│   ├── cleaner.py          # 5-stage PII scrubbing pipeline
│   └── worker.py           # Async background processor with retry
│
├── storage/                # Filesystem storage
│   └── document_store.py   # Unified doc store (both paths)
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
└── adr/                    # Architecture Decision Records (ADRs)
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

### Master Orchestrator Framework
- This repository utilizes an **Agent Orchestrator** framework. When handling complex or multi-step requests, you MUST use the `agent-orchestrator` skill (`.agents/skills/agent-orchestrator/SKILL.md`).
- The Orchestrator safely routes your workloads across a fleet of 38 specialized local skills covering domains like planning, "Senior" specialized execution, architecture design, QA looping, and robust debugging.
- ALWAYS decompose large, ambiguous tasks using this orchestrator routing strategy before initiating code changes.

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

---

## ⚠️ MANDATORY: Post-Change Maintenance Checklist

**Every AI agent working on this repo MUST perform the following steps after ANY code change.** This is not optional. The user should never need to ask for documentation updates — agents must take this responsibility automatically.

### 1. Rebuild code-review-graph

After adding, deleting, or renaming any file, class, or function:

```bash
python -m code_review_graph build --repo .
```

This updates `.code-review-graph/graph.db` (715+ nodes, 3529+ edges). Without this, blast-radius analysis and dependency queries will be stale.

**When to rebuild:**
- Added or deleted a `.py` file
- Renamed a class or function
- Changed import structure
- Added new Protocol implementations
- Refactored any module

### 2. Update `docs/CODE_FLOW.md`

After any change to the code flow, architecture, or component structure:

- **New class/file?** → Add it to the [File Map](docs/CODE_FLOW.md#file-map) with class name, file path, and purpose
- **New protocol implementation?** → Add to the [Protocols table](docs/CODE_FLOW.md#protocols-contracts) 
- **Changed ingestion pipeline?** → Update [Uploading a Document](docs/CODE_FLOW.md#uploading-a-document-ingestion) step-by-step trace
- **Changed retrieval pipeline?** → Update [Asking a Question](docs/CODE_FLOW.md#asking-a-question-retrieval) step-by-step trace
- **New guardrail?** → Add to [Guardrails table](docs/CODE_FLOW.md#guardrails)
- **New PII pattern?** → Add to [PII Patterns table](docs/CODE_FLOW.md#pii-patterns-14-total)
- **New chunker?** → Add to [ChunkResult Schema](docs/CODE_FLOW.md#chunkresult-schema) and File Map

**CODE_FLOW.md must always reflect actual class names, method signatures, file paths, and line numbers from the source code.**

### 3. Update `AGENTS.md` (this file)

After any structural change:

- **New file in the tree?** → Update the [Project Structure](AGENTS.md#project-structure) tree
- **New design pattern?** → Add to [Design Patterns Used](AGENTS.md#design-patterns-used) table
- **New implementation convention?** → Add to [Key Conventions](AGENTS.md#key-conventions)
- **New environment variable?** → Add to [Configuration](AGENTS.md#configuration)

### 4. Update `README.md`

After any user-facing change:

- **New feature?** → Add to [Key Features](README.md#key-features) table with doc link
- **New doc file?** → Add to [Documentation Index](README.md#-complete-documentation-index) tables
- **New env var?** → Add to [Environment Variables](README.md#environment-variables)
- **Test count changed?** → Update test count badge and text
- **New dependency?** → Add to [Install Dependencies](README.md#install-dependencies) section

### 5. Update relevant `docs/` files

If your change affects a specific doc topic:

| Change type | Docs to update |
|-------------|---------------|
| New Protocol or abstraction | `ARCHITECTURE_LLD.md` |
| System topology change | `ARCHITECTURE_HLD.md` |
| New design pattern | `DESIGN_PATTERNS_AND_LEARNING.md` |
| Security-related change | `AUDIT_REPORT.md` |
| New MCP tool | `MCP_IMPLEMENTATION_GUIDE.md` |
| Deployment change | `MCP_DEPLOYMENT_GUIDE.md` |
| New PII pattern or guardrail | `CODE_FLOW.md` (PII section) |

### 6. Run tests

```bash
pytest tests/ -v
```

Every change must maintain the current pass rate (202+ tests). If you add a new component, add corresponding tests.

### Quick Reference: The 6-Step Post-Change Ritual

```
1. ✅ Code change complete
2. 🔄 python -m code_review_graph build --repo .
3. 📄 Update docs/CODE_FLOW.md (class names, file paths, flow diagrams)
4. 📄 Update AGENTS.md (project structure tree, patterns table)
5. 📄 Update README.md (features table, doc index, test count)
6. 🧪 pytest tests/ -v (must pass)
```

**If you skip any step, the next agent working on this repo will have stale context and may introduce bugs.**
