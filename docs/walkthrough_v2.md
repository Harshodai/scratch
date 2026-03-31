# CentRAG: Design Patterns & Learning Guide

**Date:** 2026-03-31
**Purpose:** Map every pattern to its code location + learning resources.

---

## 1. SOLID Principles — Where They Live in CentRAG

| Principle | What It Means | Where In CentRAG | File |
|-----------|--------------|-------------------|------|
| **S — Single Responsibility** | Each class does ONE thing | `RetrievalEngine` orchestrates but doesn't embed, search, or generate. Each is a separate protocol. | `retrieval/engine.py` |
| **O — Open/Closed** | Open for extension, closed for modification | Add `OpenAIEmbedder` by implementing `EmbedderProtocol` — zero changes to `engine.py` | `abstractions/embedder.py` |
| **L — Liskov Substitution** | Any implementation of a Protocol works interchangeably | `BedrockLLM` and `OpenAILLM` both satisfy `LLMProtocol`. Swap in config, not in code. | `abstractions/llm.py` |
| **I — Interface Segregation** | Small, focused interfaces | `EmbedderProtocol` only embeds. `RerankerProtocol` only reranks. No "AIService" that does everything. | `abstractions/*.py` |
| **D — Dependency Inversion** | Depend on abstractions, not concretions | `RetrievalEngine.__init__` accepts `EmbedderProtocol`, never `BedrockEmbedder` directly. | `retrieval/engine.py` |

### Study Resources — SOLID
| Resource | Type | URL |
|---------|:----:|-----|
| *Clean Architecture* — Robert C. Martin | 📖 Book | The definitive SOLID book |
| ArjanCodes — "SOLID Principles in Python" | 🎥 YT | Search "ArjanCodes SOLID" |
| Real Python — SOLID Principles | 📝 Blog | https://realpython.com/solid-principles-python/ |
| Python `typing.Protocol` docs | 📄 Docs | https://docs.python.org/3/library/typing.html#typing.Protocol |
| FastAPI Dependency Injection | 📄 Docs | https://fastapi.tiangolo.com/tutorial/dependencies/ |

> [!TIP]
> **Key insight:** In Python, use `typing.Protocol` (structural subtyping) over
> `abc.ABC` (nominal subtyping). Protocol doesn't require explicit inheritance —
> any class that has the right methods automatically satisfies it. This is more
> Pythonic and more flexible for testing with mocks.

---

## 2. Software Design Patterns — Where They Live

### Pattern Map

| Pattern | What It Solves | Where In CentRAG |
|---------|---------------|-------------------|
| **Strategy** | Swappable algorithms at runtime | Embedder, LLM, Reranker, Cache — each has multiple implementations behind one Protocol |
| **Chain of Responsibility** | Pipeline of steps, each can short-circuit | Retrieval pipeline: Cache → Retrieve → Rerank → Validate → Generate. Cache hit skips everything. |
| **Factory** | Create complex objects without exposing construction | `create_app()` in `app.py` builds the FastAPI app with all wiring |
| **Repository** | Abstract data access behind an interface | `VectorStoreProtocol` hides whether you're using Qdrant, Pinecone, or pgvector |
| **Composite** | Treat a group of objects as one | Memory layer combines Redis (working) + PG (episodic) + Neptune (semantic) behind `MemoryProtocol` |
| **Value Object** | Immutable, identity-less data | `RequestContext`, `VectorSearchResult`, `LLMResponse` — all `frozen=True` dataclasses |
| **Builder** | Step-by-step construction of complex objects | `VectorFilter.for_team(id).with_condition("namespace", "x")` — fluent builder for search filters |
| **Observer** | Notify dependents of state changes | Cache invalidation on document re-ingestion (future: event-driven via SQS) |
| **Template Method** | Fixed algorithm skeleton, swappable steps | `RetrievalEngine.retrieve()` has fixed steps, but each step uses a swappable Protocol |
| **Circuit Breaker** | Prevent cascade failures | Per-dependency circuit breakers (future: `tenacity` + custom breaker) |

### Study Resources — Design Patterns
| Resource | Type | URL |
|---------|:----:|-----|
| *Head First Design Patterns* (2nd Ed) | 📖 Book | Best intro — visual, practical |
| *Design Patterns: Elements of Reusable Object-Oriented Software* (GoF) | 📖 Book | The classic reference (dense but definitive) |
| Refactoring Guru — Design Patterns | 📄 Website | https://refactoring.guru/design-patterns |
| Python Design Patterns (Brandon Rhodes) | 📄 Website | https://python-patterns.guide |
| ArjanCodes — "Design Patterns in Python" | 🎥 YT | Full playlist on YT |

---

## 3. Agentic Design Patterns — Where They Apply

| Pattern | What It Does | CentRAG Application | Status |
|---------|-------------|---------------------|:------:|
| **ReAct** (Reason + Act) | LLM reasons before acting | Adaptive RAG: classify query complexity → decide retrieval strategy → execute | 🔧 Designed |
| **Reflection** (Self-Correction) | Agent critiques own output | CRAG: after retrieval, validate chunk confidence. If low → rewrite query → retry. | 🔧 Designed |
| **Tool Use** (Function Calling) | LLM calls structured tools | MCP connectors (GOS DB, DynamoDB, Athena) ARE tools. `/v1/retrieve` is also a tool for agents. | ✅ Built |
| **Planning** (Plan-and-Execute) | Decompose complex goals | Complex query → break into sub-queries → retrieve each → merge results (future) | ❌ Phase 5+ |
| **Multi-Agent** | Specialized agents collaborate | Ingestion agent + Retrieval agent + QA agent (future) | ❌ Phase 5+ |
| **Memory** | Persist state across sessions | Temporal memory with versioning. Working (Redis) + Episodic (Qdrant/PG) + Semantic (Neptune). | 🔧 Designed |
| **Governance-as-Code** | Hardwired guardrails | Auth middleware is non-optional. PII redaction is in the pipeline, not afterthought. Rate limits per team. | ✅ Built |

### Study Resources — Agentic Patterns
| Resource | Type | URL |
|---------|:----:|-----|
| Andrew Ng — "Agentic Design Patterns" (4 talks) | 🎥 Video | Search "Andrew Ng agentic design patterns" on YouTube |
| LangGraph Documentation | 📄 Docs | https://langchain-ai.github.io/langgraph/ |
| Anthropic — "Building Effective Agents" | 📝 Blog | https://www.anthropic.com/engineering/building-effective-agents |
| ReAct Paper (Yao et al., 2023) | 📄 Paper | https://arxiv.org/abs/2210.03629 |
| Reflexion Paper (Shinn et al., 2023) | 📄 Paper | https://arxiv.org/abs/2303.11366 |
| CRAG Paper (Yan et al., 2024) | 📄 Paper | https://arxiv.org/abs/2401.15884 |
| SWE-Agent Framework | 💻 Code | https://github.com/princeton-nlp/SWE-agent |

---

## 4. RAG Advancements (2025-2026) — What to Apply to CentRAG

### Current vs SOTA

| Technique | CentRAG Today | SOTA (2026) | Priority | Effort |
|-----------|:-------------:|:-----------:|:--------:|:------:|
| **Naive RAG** (retrieve → generate) | ✅ Scaffolded | Legacy | — | — |
| **Hybrid Search** (dense + BM25 + RRF) | 🔧 Designed | ✅ Standard | **P1** | 3 days |
| **Reranking** (Cohere v3) | 🔧 Designed | ✅ Standard | **P1** | 2 days |
| **Adaptive RAG** (complexity routing) | 🔧 Scaffolded | ✅ Standard | **P2** | 3 days |
| **Corrective RAG (CRAG)** | 🔧 Scaffolded | ✅ Emerging | **P2** | 5 days |
| **Contextual Retrieval** (Anthropic) | ❌ | ✅ Emerging | **P2** | 3 days |
| **Late Chunking** (Jina) | 🔧 Protocol exists | ✅ Emerging | **P3** | 5 days |
| **GraphRAG** (KG-enhanced retrieval) | ❌ (Neptune is P6) | ✅ Emerging | **P4** | 10 days |
| **Agentic RAG** (plan → multi-hop) | ❌ | ✅ Cutting edge | **P5** | 15 days |
| **Context Caching** (LLM-native) | ❌ | ✅ Standard | **P3** | 2 days |

### What Each Advancement Means

#### Contextual Retrieval (Anthropic, 2024)
**Problem:** Chunks lose context when split from documents.
**Solution:** For each chunk, use an LLM to generate a 1-2 sentence context summary that connects it to the full document. Prepend this to the chunk before embedding.
**Impact:** +49% retrieval accuracy (Anthropic's benchmark).
**CentRAG implementation:** Add to ingestion pipeline between chunking and embedding.

```python
# Future: centrag/ingestion/contextualizer.py
async def contextualize_chunk(chunk: str, full_doc: str, llm: LLMProtocol) -> str:
    context = await llm.generate(
        prompt=f"Given this document, write a concise context for this chunk:\n\nChunk: {chunk}",
        context=[full_doc[:8000]],  # First 8K tokens of doc
        max_tokens=100,
    )
    return f"{context.content}\n\n{chunk}"  # Prepend context
```

#### Late Chunking (Jina AI, 2024)
**Problem:** Traditional chunking embeds each chunk independently → loses cross-chunk references.
**Solution:** Pass the FULL document through the embedding model first (get token-level embeddings), THEN chunk and mean-pool per chunk.
**Impact:** Each chunk's embedding is aware of the entire document context.
**CentRAG implementation:** Already in `EmbedderProtocol.embed_with_late_chunking()`.

#### Adaptive RAG (2025)
**Problem:** Using the same expensive pipeline for "What's 2+2?" and "Compare our Q3 vs Q4 revenue across all regions."
**Solution:** Classify query complexity → route to appropriate pipeline.
**CentRAG implementation:** Already in `LLMProtocol.classify_complexity()` + `RetrievalEngine`.

#### Corrective RAG — CRAG (2024)
**Problem:** Retrieved chunks might be irrelevant or misleading.
**Solution:** After retrieval + reranking, check confidence scores. If below threshold → rewrite the query → try different data source → or flag as "low confidence."
**CentRAG implementation:** Already scaffolded in `RetrievalEngine` (Step 5: CRAG validation).

### Study Resources — RAG Advancements
| Resource | Type | URL |
|---------|:----:|-----|
| Anthropic — "Contextual Retrieval" | 📝 Blog | https://www.anthropic.com/news/contextual-retrieval |
| Jina AI — Late Chunking Paper | 📄 Paper | https://arxiv.org/abs/2409.04701 |
| CRAG Paper (Yan et al., 2024) | 📄 Paper | https://arxiv.org/abs/2401.15884 |
| Adaptive RAG Paper (Jeong et al., 2024) | 📄 Paper | https://arxiv.org/abs/2403.14403 |
| Microsoft GraphRAG | 💻 Code | https://github.com/microsoft/graphrag |
| Eugene Yan — LLM Patterns | 📝 Blog | https://eugeneyan.com/writing/llm-patterns/ |
| LangChain — Corrective RAG Tutorial | 📄 Docs | https://python.langchain.com/docs/tutorials/rag/ |
| ColBERT v2 Paper | 📄 Paper | https://arxiv.org/abs/2112.01488 |

---

## 5. Project Structure — Pattern Annotations

```
centrag/
├── __init__.py
├── app.py                      ← FACTORY PATTERN (create_app)
├── config.py                   ← CONFIGURATION PATTERN (Pydantic Settings)
│
├── abstractions/               ← DIP + ISP (Protocol interfaces)
│   ├── embedder.py             ← STRATEGY (Bedrock/OpenAI/Local)
│   ├── vectorstore.py          ← REPOSITORY (Qdrant/Pinecone/pgvector)
│   ├── llm.py                  ← STRATEGY + ADAPTIVE RAG
│   ├── cache.py                ← STRATEGY (each tier is a strategy)
│   ├── reranker.py             ← STRATEGY + CRAG confidence gate
│   └── memory.py               ← COMPOSITE + TEMPORAL VERSIONING
│
├── middleware/
│   ├── __init__.py             ← VALUE OBJECT (RequestContext, frozen)
│   └── auth.py                 ← CHAIN OF RESPONSIBILITY (auth link)
│
├── models.py                   ← REPOSITORY entities + RLS security
│
├── retrieval/
│   └── engine.py               ← CHAIN OF RESPONSIBILITY + TEMPLATE METHOD
│                                  + ADAPTIVE RAG + CRAG
│
├── routes/
│   ├── health.py               ← SRP (only health)
│   ├── documents.py            ← SRP (only document CRUD)
│   └── retrieve.py             ← TOOL USE (agent-callable endpoint)
│
├── [FUTURE] ingestion/
│   ├── worker.py               ← PIPELINE PATTERN
│   ├── parser.py               ← STRATEGY (Unstructured/custom)
│   ├── chunker.py              ← STRATEGY (semantic/fixed/late)
│   └── contextualizer.py       ← CONTEXTUAL RETRIEVAL (Anthropic)
│
├── [FUTURE] cache/
│   └── tiered.py               ← CHAIN OF RESPONSIBILITY (L1→L2→L3)
│
├── [FUTURE] memory/
│   └── engine.py               ← COMPOSITE + TEMPORAL VERSIONING
│
└── [FUTURE] security/
    ├── pii.py                  ← CHAIN OF RESPONSIBILITY (redaction step)
    └── audit.py                ← OBSERVER (log every access)

mcp_enterprise_server/          ← TOOL USE PATTERN (MCP connectors)
├── gosdb_mcp.py                ← STRATEGY (Oracle connector)
├── dynamodb_mcp.py             ← STRATEGY (DynamoDB connector)
├── athena_mcp.py               ← STRATEGY (Athena connector)
└── guardrails.py               ← CHAIN OF RESPONSIBILITY (validation chain)
```

---

## 6. Learning Priority — What to Study When

### Week 1-2: Foundations (While Building P0)
| Topic | Resource | Time |
|-------|---------|:----:|
| SOLID in Python | ArjanCodes YT playlist | 2 hrs |
| `typing.Protocol` | Python docs + Real Python article | 1 hr |
| FastAPI Dependency Injection | FastAPI docs — Dependencies section | 2 hrs |
| SQLAlchemy 2.0 Async | SQLAlchemy async tutorial | 3 hrs |
| Strategy + Repository patterns | Refactoring.guru | 2 hrs |

### Week 3-4: RAG Engineering (While Building P1)
| Topic | Resource | Time |
|-------|---------|:----:|
| Anthropic Contextual Retrieval blog | Read + experiment | 2 hrs |
| Late Chunking paper | Read abstract + implementation | 3 hrs |
| Hybrid search (BM25 + dense + RRF) | Weaviate docs + Pinecone blog | 2 hrs |
| Cohere Rerank v3 API | Cohere docs + hands-on | 1 hr |
| Chain of Responsibility pattern | Refactoring.guru + apply to retrieval | 2 hrs |

### Week 5-6: Agentic + Advanced (While Building P2-P3)
| Topic | Resource | Time |
|-------|---------|:----:|
| Andrew Ng "Agentic Patterns" (4 talks) | YouTube | 4 hrs |
| CRAG paper | Read + implement validation loop | 3 hrs |
| Adaptive RAG paper | Read + implement complexity router | 3 hrs |
| Zep Graphiti temporal model | Read paper + study code | 4 hrs |
| Circuit Breaker pattern (*Release It!*) | Read chapters 4-5 | 3 hrs |

### Week 7+: Production (While Building P3+)
| Topic | Resource | Time |
|-------|---------|:----:|
| RAGAS evaluation framework | Docs + golden dataset creation | 4 hrs |
| Langfuse tracing integration | Docs + instrument retrieval engine | 3 hrs |
| AWS CDK (Python) | CDK Workshop | 4 hrs |
| Load testing with Locust | Docs + write CentRAG load test | 2 hrs |
| Chaos engineering | AWS FIS docs + plan tests | 2 hrs |

---

## 7. What Makes CentRAG Ahead of the Game

| Advancement | Most RAG Systems | CentRAG (After Full Build) |
|-------------|-----------------|---------------------------|
| Chunking | Fixed 512 tokens | **Contextual Retrieval** (Anthropic) + **Late Chunking** (Jina) protocol ready |
| Retrieval | Single dense search | **Hybrid** (dense + BM25 + RRF) + **Adaptive** (route by complexity) |
| Validation | None — trust whatever was retrieved | **CRAG** — confidence gating, query rewriting on low confidence |
| Memory | None or simple KV | **Temporal versioning** (Zep-inspired) — facts version-chained, never overwritten |
| Cache | None or basic TTL | **3-tier** (L1 in-process → L2 Redis exact → L3 Qdrant semantic) |
| Security | API key only | **6-layer isolation** (API key → RLS → payload filter → S3 path → KMS → Redis prefix) |
| Observability | Logs only | **Langfuse traces** per query + **RAGAS** automated quality eval |

> [!IMPORTANT]
> The combination of these advancements is what creates the moat.
> No single competitor has ALL of: temporal memory + CRAG + adaptive routing
> + 6-layer isolation + semantic cache + MCP connectors.
