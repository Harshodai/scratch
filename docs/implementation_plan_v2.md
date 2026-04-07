# CentRAG Architectural Overhaul — Implementation Plan (v2, Corrected)

**Confidence: 8/10**

Deductions: -1 for some implementation specifics in Phase 3 (extraction) that depend on your document corpus, -1 for MCP auth choices that depend on your org's IdP.

---

## Goal

Harden CentRAG from a well-designed scaffold into a production-ready platform with:
- Enhanced SOLID abstractions (missing protocols for extraction, chunking, guardrails)
- Enterprise MCP research distilled into actionable docs + incremental hardening
- A real extraction/chunking pipeline (currently missing entirely)
- Unified guardrails (currently duplicated between RAG and MCP, with dead code)
- Cleaner layer boundaries (without premature package explosion)
- Proper cache orchestration and memory implementations
- Thorough documentation including RAG+MCP integration patterns

---

## User Review Required

> [!IMPORTANT]
> **Scope question:** This plan has 7 phases. I recommend Phases 1-4 as the immediate priority (they fix real code issues). Phases 5-7 are documentation and future architecture. Do you want all 7, or should I focus on 1-4 first?

> [!WARNING]
> **Existing bug:** `cachetools` is imported in `centrag/abstractions/cache.py` (line 68) but is **not listed in `pyproject.toml` dependencies**. I'll fix this regardless of phase decisions.

---

## Phase 1: Fix SOLID Gaps — Add Missing Abstractions

### What's Actually Wrong
- No `ExtractorProtocol` or `ChunkerProtocol` — documents have no extraction pipeline at all
- No `GuardrailProtocol` — guardrails are free functions, not composable components
- `GuardrailsConfig` (guardrails.py L328-335) is declared but **never used anywhere**
- `CostTrackerProtocol` (guardrails.py L245-264) is declared but **never implemented**
- `RetrievalEngine.retrieve()` calls guardrail functions inline (SRP violation — orchestration leaks into validation)

### Proposed Changes

#### [NEW] `centrag/abstractions/extractor.py`
- `ExtractorProtocol` with `extract(file_bytes, content_type) → ExtractedDocument`
- `ExtractedDocument` dataclass: `text`, `metadata`, `tables`, `images_count`

#### [NEW] `centrag/abstractions/chunker.py`
- `ChunkerProtocol` with `chunk(text, config) → list[ChunkResult]`
- `ChunkingStrategy` enum: `FIXED`, `RECURSIVE`, `SEMANTIC`, `STRUCTURE_AWARE`
- (Note: `LATE_CHUNKING` is an embedding-level operation, not a chunking strategy — it belongs in `EmbedderProtocol.embed_with_late_chunking()` which already exists)

#### [NEW] `centrag/abstractions/guardrail.py`
- `InputRailProtocol` with `validate(query, context) → ValidatedQuery`
- `OutputRailProtocol` with `validate(response, context) → ValidatedResponse`
- `GuardrailChain` — composite that runs rails in order (Chain of Responsibility)

#### [MODIFY] [abstractions/__init__.py](file:///c:/Users/khars/PycharmProjects/scratch/centrag/abstractions/__init__.py)
- Export new protocols

#### [MODIFY] [centrag/retrieval/engine.py](file:///c:/Users/khars/PycharmProjects/scratch/centrag/retrieval/engine.py)
- Inject `GuardrailChain` as a dependency instead of calling `validate_query`/`validate_response`/`redact_pii` inline
- This fixes the SRP violation: engine orchestrates, guardrails validate

#### [MODIFY] [pyproject.toml](file:///c:/Users/khars/PycharmProjects/scratch/pyproject.toml)
- Add missing `cachetools` dependency

---

## Phase 2: Extraction Layer (Currently Non-Existent)

### Current State
`unstructured[all-docs]` is in `pyproject.toml` but there is **zero extraction code**. Documents go from "upload" in `routes/documents.py` to... nothing. The `Document` model has a `status` field (`pending | processing | ready | failed`) but no code ever transitions it.

### Proposed Changes

#### [NEW] `centrag/extraction/` package
```
centrag/extraction/
├── __init__.py
├── pipeline.py          # ExtractionPipeline orchestrator
├── parsers/
│   ├── __init__.py
│   ├── base.py          # ParserProtocol
│   ├── pdf.py           # PDF via unstructured
│   ├── docx.py          # DOCX via unstructured
│   ├── html.py          # HTML → clean text
│   ├── text.py          # Plaintext passthrough
│   └── csv_excel.py     # Tabular → structured text
└── chunkers/
    ├── __init__.py
    ├── base.py           # ChunkerProtocol (re-exports from abstractions)
    ├── fixed.py          # Fixed-size with overlap (baseline)
    ├── recursive.py      # Recursive text splitting (LangChain-style)
    ├── semantic.py       # Embedding-similarity boundary detection
    └── structure_aware.py # Header/section-aware splitting
```

#### Key Design Decisions
- **Strategy Pattern**: Chunker is selected via config, not hardcoded
- **Context-Enriched Chunks**: Every chunk gets metadata prepended: `[Document: {title}] [Section: {header}]` — this is proven to improve retrieval quality
- **No Late Chunking module**: Late chunking is an *embedding* operation — the existing `EmbedderProtocol.embed_with_late_chunking()` already handles it. The chunker just provides `chunk_boundaries` to the embedder.
- **Extraction Metrics**: Track char count, table count, images found per document

> [!IMPORTANT]
> **Dependency weight**: `unstructured[all-docs]` is heavy (~2GB with tesseract/poppler). If you want lightweight, I can use `unstructured[pdf,docx]` instead (covers 90% of use cases). Which do you prefer?

---

## Phase 3: Guardrails Hardening

### What's Actually Wrong
1. **PII patterns duplicated** — identical regex dict in `centrag/guardrails.py` (L184-192) and `mcp_enterprise_server/guardrails.py` (L203-208), except the RAG version has 3 extra patterns (IP, AWS keys). This will drift.
2. **`GuardrailsConfig`** (L328-335) — declared but never composed into anything. Dead code.
3. **`CostTrackerProtocol`** (L245-264) — declared with `RedisBackedCostTracker` mentioned in docstring but never implemented.
4. **`BUDGET_LIMITS`** dict (L268-272) — declared but never referenced.
5. **No composite guardrail** — there's no way to run all guardrails as a pipeline. The engine calls them individually.

### Proposed Changes

#### [MODIFY] [centrag/guardrails.py](file:///c:/Users/khars/PycharmProjects/scratch/centrag/guardrails.py) → Promote to `centrag/guardrails/` package

```
centrag/guardrails/
├── __init__.py          # Exports GuardrailEngine + all configs
├── engine.py            # GuardrailEngine — composite chain
├── input_rails.py       # validate_query + prompt injection + namespace check
├── output_rails.py      # validate_response + confidence gate
├── pii.py               # SINGLE SOURCE OF TRUTH for PII patterns
│                        # (MCP guardrails import from here)
├── cost_tracker.py      # InMemoryCostTracker implementation
│                        # (fulfills the existing CostTrackerProtocol)
├── audit.py             # audit_retrieval (moved from guardrails.py)
└── config.py            # GuardrailsConfig (wired into GuardrailEngine)
```

#### `GuardrailEngine` Design
```python
class GuardrailEngine:
    """Composite — runs configured rails in order."""
    
    def __init__(self, config: GuardrailsConfig):
        self._input_rails: list[InputRailProtocol] = []
        self._output_rails: list[OutputRailProtocol] = []
        self._cost_tracker: CostTrackerProtocol | None = None
        # Build rails from config (enable/disable per rail)
    
    async def run_input(self, query, ctx) -> ValidatedQuery:
        """Run all input rails. Raises on violation."""
    
    async def run_output(self, response, sources, ctx) -> ValidatedResponse:
        """Run all output rails. Returns cleaned response."""
```

#### [MODIFY] [mcp_enterprise_server/guardrails.py](file:///c:/Users/khars/PycharmProjects/scratch/mcp_enterprise_server/guardrails.py)
- Import PII patterns from `centrag.guardrails.pii` instead of defining its own copy
- Keep MCP-specific guards (SQL injection, schema access, table access) — those are correctly domain-specific
- Keep `TokenBucketRateLimiter` and `guardrailed` decorator — those are MCP-specific middleware

#### Concrete Implementation: `InMemoryCostTracker`
- Fulfills the existing `CostTrackerProtocol` that was declared but never implemented
- Uses `BUDGET_LIMITS` dict that was declared but never referenced
- In-process dict for development; Redis-backed version is documented as future TODO

---

## Phase 4: Cache & Memory Layer Improvements

### Cache — What Needs Fixing
The current `centrag/abstractions/cache.py` mixes **protocol definitions** with **implementation code** (the `memoize_with_ttl_async` decorator, `SWR_CacheEntry`, the LRU logic). This violates the package's own stated principle: "Abstractions package — The heart of SOLID."

#### Proposed Changes

#### [MODIFY] [centrag/abstractions/cache.py](file:///c:/Users/khars/PycharmProjects/scratch/centrag/abstractions/cache.py)
- Keep ONLY: `CacheTier`, `CacheResult`, `CacheProtocol` (lines 1-61)
- Move everything from line 63 onward (implementations) to:

#### [NEW] `centrag/cache/` package
```
centrag/cache/
├── __init__.py
├── swr.py              # memoize_with_ttl_async + SWR_CacheEntry (moved from abstractions)
├── l1_memory.py        # In-process LRU cache (implements CacheProtocol)
├── l2_redis.py         # Redis exact-match cache (stub — implements CacheProtocol)
├── l3_semantic.py      # Qdrant semantic cache (stub — implements CacheProtocol)
└── orchestrator.py     # TieredCacheOrchestrator — chains L1→L2→L3
```

The `TieredCacheOrchestrator` is the concrete class that implements `CacheProtocol` and is injected into `RetrievalEngine`. On `get()`, it tries L1 → L2 → L3 → MISS. On `set()`, it writes to all tiers.

### Memory — What Needs Fixing
The `MemoryProtocol` is well-designed. What's missing is any implementation.

#### [NEW] `centrag/memory/` package
```
centrag/memory/
├── __init__.py
├── in_memory_store.py  # Dict-based implementation for dev/testing
└── temporal_store.py   # PostgreSQL-backed implementation
    # Uses the existing MemoryEntry SQLAlchemy model
    # Implements temporal versioning (valid_from/valid_to)
    # Implements decay scoring
```

> [!NOTE]
> I'm **not** proposing a graph memory (Neptune/Neo4j) module. The `memory.py` abstraction mentions "Neptune KG" in a comment, but there's no dependency, no schema, and no clear need for it now. If you want graph memory later, the `MemoryProtocol` is already flexible enough to support it.

---

## Phase 5: MCP Enterprise Research Documentation

This phase is **documentation-only**, not code changes. Based on the deep research I conducted.

#### [NEW] `docs/MCP_ENTERPRISE_RESEARCH.md`
Comprehensive reference document covering:

**1. Enterprise Architecture Patterns**
- MCP Gateway / Agent Router pattern (centralized entry point)
- Bounded Context Micro-Servers (domain-specific tool sets)
- Hierarchical Agent Orchestration (orchestrator → specialist agents)

**2. Triple-Gate Security Architecture**
- Gate 1: AI Gateway (prompt analysis before LLM)
- Gate 2: MCP Gateway (identity, RBAC, rate limiting, audit)
- Gate 3: API Gateway (network segmentation, least-privilege DB access)

**3. Production Readiness Checklist**
| Category | Current State | Recommended |
|---|---|---|
| Auth | None | OAuth 2.1 (when ready for prod) |
| Transport | stdio + streamable-http | Streamable HTTP + TLS 1.3 |
| Rate Limiting | In-process token bucket | Redis-backed (when scaling) |
| Secrets | `SecretStr` in pydantic | Vault/SSM (when in prod) |
| Observability | structlog | + OpenTelemetry + Langfuse |
| Tool Registry | Hardcoded | Dynamic catalog (future) |

**4. OAuth 2.1 Integration Roadmap**
- NOT implemented now (premature for scaffold stage)
- Documented as a concrete future phase with IdP options

**5. What Your MCP Server Already Does Well**
- SQL injection prevention ✓
- Schema/table whitelisting ✓  
- Permission level enforcement ✓
- Query timeout + cancellation ✓
- PII redaction ✓
- Structured audit logging ✓
- Rate limiting ✓

#### [MODIFY] [docs/MCP_DEPLOYMENT_GUIDE.md](file:///c:/Users/khars/PycharmProjects/scratch/docs/MCP_DEPLOYMENT_GUIDE.md)
- Add Triple-Gate security section
- Add production readiness checklist
- Add OAuth roadmap (as a documented future phase)

---

## Phase 6: RAG + MCP Integration Guide & Bridge Code

### How RAG + MCP Work Together — 3 Patterns

**Pattern 1: RAG-as-MCP-Tool** (expose your RAG pipeline to AI agents via MCP)
```
AI Agent → MCP Client → [RAG MCP Server] → query_knowledge_base tool → RAG Engine → answer
```
- The agent calls `query_knowledge_base(query, namespace)` as an MCP tool
- The MCP server internally runs the full RAG pipeline
- Agent gets grounded answers with source citations

**Pattern 2: MCP-as-RAG-Source** (use MCP tools as data sources in RAG)
```
User API → RAG Engine → [MCP Client] → query_gosdb tool → GOS DB → live data → RAG context
```
- During retrieval, the engine can call MCP tools to fetch live data
- Results are injected into the LLM context alongside vector search results
- Enables "compare our internal docs with live database records"

**Pattern 3: Hybrid Orchestrator** (agentic router decides path)
```
Query → Intent Classifier → Pure RAG | Pure MCP | RAG+MCP combined
```
- Uses `classify_complexity()` (already in LLMProtocol) to route
- Simple factual → cached RAG
- Live data → MCP tool call
- Complex multi-source → both

### Proposed Changes

#### [NEW] `centrag/mcp_bridge/` package
```
centrag/mcp_bridge/
├── __init__.py
├── rag_as_mcp_tool.py    # Register RAG pipeline as MCP tools
└── mcp_as_rag_source.py  # Wrap MCP tool results as SourceChunks
```

#### [NEW] `docs/RAG_MCP_INTEGRATION_GUIDE.md`
- Full documentation of the 3 patterns with diagrams
- When to use which pattern
- Code examples for each
- Limitations and trade-offs

---

## Phase 7: Comprehensive Documentation

#### [NEW] `docs/ARCHITECTURE_V2.md`
- Updated architecture reflecting phases 1-4 changes
- Data flow diagrams for extraction → chunking → embedding → retrieval
- Layer dependency graph

#### [NEW] `docs/EXTRACTION_GUIDE.md`
- Supported formats and parser configuration
- Chunking strategy selection guide (when to use which)
- Quality metrics and evaluation recommendations

#### [NEW] `docs/GUARDRAILS_REFERENCE.md`
- All rails documented with config options
- OWASP LLM Top 10 mapping (which rails cover which risks)
- Configuration examples for different risk profiles

#### [MODIFY] [docs/LEARNING_AND_ROADMAP.md](file:///c:/Users/khars/PycharmProjects/scratch/docs/LEARNING_AND_ROADMAP.md)
- Update with completed phases
- Add MCP enterprise research references

---

## What I Am NOT Proposing (Corrected from v1)

1. **~~Massive package restructure~~** — The current flat `centrag/` structure is appropriate for the scaffold stage. I'm adding new sub-packages (`extraction/`, `guardrails/`, `cache/`, `memory/`, `mcp_bridge/`) within the existing structure, not reorganizing everything.

2. **~~OAuth 2.1 implementation~~** — Documented as research, not implemented now. Premature for development stage.

3. **~~ML prompt injection classifier~~** — The regex approach in `guardrails.py` is fine for now. Enhanced regex (more patterns) is the right next step.

4. **~~Neptune/Neo4j graph memory~~** — No concrete need identified. The `MemoryProtocol` will support it if needed later.

5. **~~Moving `app.py`, `config.py`, `models.py` into `centrag/backend/`~~** — They're fine where they are.

---

## Open Questions

> [!IMPORTANT]
> **Q1**: For the extraction layer, do you want full `unstructured[all-docs]` (heavy, ~2GB) or selective `unstructured[pdf,docx]` (lighter, covers most use cases)?

> [!IMPORTANT]
> **Q2**: Should I implement the `InMemoryCostTracker` with a real Redis-backed version too, or is in-memory sufficient for now?

> [!IMPORTANT]
> **Q3**: For the `mcp_bridge` — do you want working code that calls the existing `mcp_enterprise_server`, or documented stubs showing the integration pattern?

---

## Verification Plan

### Automated Tests
```bash
# Fix missing dependency first
pip install cachetools

# Lint + type check all new/modified code
ruff check centrag/ mcp_enterprise_server/
mypy centrag/ mcp_enterprise_server/

# Run tests (will create test files in phases)
pytest tests/ -v --cov=centrag
```

### Manual Verification
- Import all new modules successfully
- Verify `GuardrailEngine` composes and runs rails in order
- Verify extraction pipeline processes a sample PDF → chunks
- Verify PII patterns are imported from single source in MCP guardrails
- Verify cache orchestrator chains L1 → L2 → MISS
