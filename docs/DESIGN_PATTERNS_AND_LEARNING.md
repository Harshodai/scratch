# CentRAG Design Patterns & RAG Advancements — Master Learning Plan

**Date:** 2026-03-31
**Purpose:** Deep-dive reference for every pattern, advancement, and learning resource.

---

## Part A: SOLID Principles Deep-Dive

### Where Each Principle Lives (Current Scaffold)

| Principle | Code Location | What To Study |
|-----------|--------------|---------------|
| **S — Single Responsibility** | `RetrievalEngine` only orchestrates. `EmbedderProtocol` only embeds. Routes only route. | When a class has >1 reason to change, split it. |
| **O — Open/Closed** | Add `OpenAIEmbedder` implementing `EmbedderProtocol` — zero changes to engine. | Extend via NEW classes, don't modify existing code. |
| **L — Liskov Substitution** | Any `VectorStoreProtocol` impl (Qdrant, Pinecone) works without breaking engine. | If swapping an impl breaks behavior, you violated LSP. |
| **I — Interface Segregation** | 6 separate Protocols: embedder, vectorstore, llm, cache, reranker, memory. | No "GodService". Small, focused contracts. |
| **D — Dependency Inversion** | `engine.py __init__` accepts Protocols, never concrete classes. | High-level modules depend on abstractions. |

### Anti-Patterns to Avoid in CentRAG

| ❌ Anti-Pattern | Example | ✅ What To Do Instead |
|----------------|---------|----------------------|
| **God Class** | `RAGService` that embeds, searches, reranks, generates, caches | Split into separate classes with Protocols |
| **Leaky Abstraction** | `QdrantVectorStore` exposing Qdrant-specific `payload_filter` syntax | Return generic `VectorSearchResult`, hide vendor details |
| **Hard-coded Dependencies** | `engine.py` doing `from centrag.impl.bedrock import BedrockEmbedder` | Accept `EmbedderProtocol` in constructor |
| **Anemic Domain** | All logic in routes, models are just data holders | Put validation/business rules on domain objects |
| **Service Locator** | Global `get_embedder()` function called everywhere | Constructor injection via FastAPI `Depends()` |

### Recommended Reading — SOLID

| # | Resource | Type | Time | Priority |
|:-:|---------|:----:|:----:|:--------:|
| 1 | *Clean Architecture* — Robert C. Martin, Part III (Design Principles) | 📖 Book | 4 hrs | **Must** |
| 2 | ArjanCodes — ["SOLID Principles in Python"](https://www.youtube.com/watch?v=pTB30aXS77U) | 🎥 YT | 30 min | **Must** |
| 3 | [Real Python — SOLID Principles](https://realpython.com/solid-principles-python/) | 📝 Blog | 1 hr | **Must** |
| 4 | [Python `typing.Protocol` PEP 544](https://peps.python.org/pep-0544/) | 📄 PEP | 30 min | Recommended |
| 5 | ArjanCodes — ["Dependency Injection in Python"](https://www.youtube.com/watch?v=J1f5b4vcxCQ) | 🎥 YT | 20 min | Recommended |

---

## Part B: Software Design Patterns — Comprehensive Map

### Patterns Ranked by Priority for CentRAG

#### Tier 1: You Need These NOW (Week 1-4)

| Pattern | Category | CentRAG Application | Key Insight |
|---------|:--------:|---------------------|-------------|
| **Strategy** | Behavioral | Swap embedders, LLMs, rerankers, cache backends at runtime | Each Protocol is a strategy interface. Config decides which impl is used. |
| **Chain of Responsibility** | Behavioral | middleware pipeline, retrieval pipeline, cache tier chain | Each handler either processes the request or passes it along. Cache hit = short-circuit. |
| **Repository** | Structural | `VectorStoreProtocol` abstracts data access | Business logic never knows if it's Qdrant or Pinecone. Testable with in-memory fakes. |
| **Factory** | Creational | `create_app()` builds FastAPI app with all wiring | Centralized object creation. Different configs → different app configurations. |
| **Value Object** | DDD | `RequestContext`, `VectorSearchResult`, `LLMResponse` (frozen dataclasses) | Immutable. No side effects. Can be passed between threads safely. |

#### Tier 2: You Need These Soon (Week 5-8)

| Pattern | Category | CentRAG Application | Key Insight |
|---------|:--------:|---------------------|-------------|
| **Builder** | Creational | `VectorFilter.for_team(id).with_condition("ns", "x")` — fluent filter construction | Step-by-step construction of complex objects. Each step returns self. |
| **Template Method** | Behavioral | `RetrievalEngine.retrieve()` — fixed skeleton, swappable steps | Algorithm structure is fixed, but specific steps are delegated to injected Protocols. |
| **Composite** | Structural | Memory layer combines Redis + PG + Neptune behind one `MemoryProtocol` | Treat a group of objects as single object. Client doesn't know it's talking to 3 stores. |
| **Observer / Pub-Sub** | Behavioral | Cache invalidation when documents re-ingested, audit logging | When document status changes → notify cache to invalidate. Use SQS for async events. |
| **Circuit Breaker** | Resilience | Per-dependency breakers: Qdrant, Redis, Bedrock, Cohere | After N failures → open circuit → fail fast → periodically half-open to test recovery. |

#### Tier 3: Add These for Production (Week 9-12)

| Pattern | Category | CentRAG Application | Key Insight |
|---------|:--------:|---------------------|-------------|
| **Decorator** | Structural | Wrap any Protocol impl with logging, metrics, retry, circuit breaker | `TracingEmbedder(BedrockEmbedder())` — adds Langfuse tracing without changing embedder code. |
| **Proxy** | Structural | Rate-limited access to Bedrock API, caching proxy for embeddings | Controls access to an object. Rate limiter = protective proxy. |
| **Adapter** | Structural | Convert Qdrant's response format to CentRAG's `VectorSearchResult` | Translate vendor-specific interfaces to your Protocol. |
| **Saga** | Distributed | Document ingestion: S3 upload → SQS → parse → embed → upsert — compensate on failure | Long-running distributed transaction. If embedding fails → delete chunks → mark doc failed. |
| **Bulkhead** | Resilience | Semaphore-per-team: limit concurrent Bedrock calls per team | Isolate resources. One team's heavy usage can't starve others. |

### Recommended Reading — Design Patterns

| # | Resource | Type | What It Covers | Time |
|:-:|---------|:----:|---------------|:----:|
| 1 | [Refactoring Guru — Design Patterns](https://refactoring.guru/design-patterns) | 📄 Web | All 23 GoF patterns with visual diagrams + Python examples | 8 hrs |
| 2 | *Head First Design Patterns* (2nd Ed) — Freeman & Robson | 📖 Book | Visual, practical intro (Java but concepts transfer) | 15 hrs |
| 3 | [Python Design Patterns — Brandon Rhodes](https://python-patterns.guide) | 📄 Web | Pythonic implementations (not ports from Java) | 4 hrs |
| 4 | ArjanCodes — "Design Patterns in Python" playlist | 🎥 YT | Strategy, Observer, Factory, Builder, Decorator in Python | 3 hrs |
| 5 | *Patterns of Enterprise Application Architecture* — Martin Fowler | 📖 Book | Repository, Unit of Work, Domain Model, Service Layer | 20 hrs (reference, not cover-to-cover) |

---

## Part C: Agentic AI Design Patterns

### The 6 Core Patterns (2025-2026 State of the Art)

| Pattern | Maturity | CentRAG Status | How It Applies |
|---------|:--------:|:--------------:|---------------|
| **ReAct** (Reason + Act) | ✅ Mature | 🔧 Designed | Adaptive RAG: reason about complexity → decide strategy → execute retrieval |
| **Reflection** (Self-Correction) | ✅ Mature | ✅ Built | CRAG: evaluate retrieved chunks → if low confidence → rewrite query → retry (`engine.py` advisor loop) |
| **Tool Use** (Function Calling) | ✅ Mature | ✅ Built | MCP connectors are tools. `/v1/retrieve` is also a tool for agents. |
| **Planning** (Plan & Execute) | ⚠️ Emerging | ❌ P5 | Complex queries → decompose into sub-queries → execute each → merge answers |
| **Multi-Agent** | ⚠️ Emerging | ❌ P5+ | Ingestion Agent + Retrieval Agent + QA Agent collaborate on complex tasks |
| **Memory** | ✅ Mature | 🔧 Designed | Temporal memory (Zep-inspired) across sessions. Working + Episodic + Semantic + Procedural. |
| **Token Budget Compression** | ✅ Mature | ✅ Built | Dynamically compress/truncate context before LLM call to prevent API truncation. `TokenBudgetManager` in `engine.py`. Inspired by `claude-code/tokenBudget.ts`. |
| **Adaptive Thinking (CoT Separation)** | ✅ Mature | ✅ Built | Format prompts with explicit `<search_strategy>` and `<evaluation>` blocks to force chain-of-thought reasoning before generating answers. Reduces hallucinations. Inspired by `claude-code/thinking.ts`. |

### Advanced Patterns Emerging in 2026

| Pattern | What It Is | CentRAG Relevance |
|---------|-----------|-------------------|
| **Governance-as-Code** | Guardrails, permissions, approval logic hardwired into agent stack | ✅ Already core to CentRAG (auth middleware, PII redaction, rate limiting) |
| **Human-in-the-Loop** | Agent escalates to human when confidence is low or risk is high | Phase 5 — add "low confidence" flag to RetrievalResponse |
| **Orchestration Graphs** | Workflows as traversable DAGs (not linear chains) | LangGraph-style. Our pipeline is linear now; evolve to conditional graph. |
| **Task Horizon Expansion** | Agents working on tasks spanning hours/days with persistent state | Requires robust memory + checkpointing. Our temporal memory is the foundation. |

### Recommended Reading — Agentic Patterns

| # | Resource | Type | Time | Priority |
|:-:|---------|:----:|:----:|:--------:|
| 1 | Andrew Ng — "Agentic Design Patterns" (4 talks) | 🎥 YT | 2 hrs | **Must** |
| 2 | [Anthropic — "Building Effective Agents"](https://www.anthropic.com/engineering/building-effective-agents) | 📝 Blog | 45 min | **Must** |
| 3 | [ReAct Paper — Yao et al., 2023](https://arxiv.org/abs/2210.03629) | 📄 Paper | 2 hrs | **Must** |
| 4 | [Reflexion Paper — Shinn et al., 2023](https://arxiv.org/abs/2303.11366) | 📄 Paper | 2 hrs | Recommended |
| 5 | [LangGraph Documentation](https://langchain-ai.github.io/langgraph/) | 📄 Docs | 3 hrs | Recommended |
| 6 | [SWE-Agent Framework](https://github.com/princeton-nlp/SWE-agent) | 💻 Code | 4 hrs | Study for architecture |
| 7 | [SWE-AF Multi-Agent Framework](https://github.com/princeton-nlp/SWE-agent) | 💻 Code | 3 hrs | Study inner/middle/outer loop |

---

## Part D: RAG Advancements (2024-2026) — Complete Taxonomy

### Evolution Timeline

```
2023: Naive RAG (retrieve → generate) ← You are here in scaffold
  ↓
2024: Advanced RAG
  ├── Hybrid Search (dense + BM25 + RRF)
  ├── Reranking (Cohere, cross-encoder)
  ├── Contextual Retrieval (Anthropic)
  ├── Corrective RAG / CRAG
  └── Late Chunking (Jina)
  ↓
2025: Modular RAG
  ├── Adaptive RAG (complexity routing)
  ├── Self-RAG (reflection tokens)
  ├── Speculative RAG (multi-draft)
  ├── GraphRAG (knowledge graph enhanced)
  └── Context Caching (LLM-native)
  ↓
2026: Agentic RAG
  ├── Planning + Multi-hop Reasoning
  ├── Multi-Agent Retrieval
  ├── Orchestration Graphs (LangGraph)
  └── Evaluation-Driven Development
```

### Full Advancement Matrix

| # | Technique | Paper/Source | CentRAG Status | Priority | Implementation Effort |
|:-:|-----------|-------------|:--------------:|:--------:|:--------------------:|
| 1 | **Hybrid Search** (dense + BM25 + RRF) | Industry standard | 🔧 Designed | **P1** | 3 days |
| 2 | **Reranking** (Cohere v3) | [Cohere Docs](https://docs.cohere.com/docs/rerank-2) | 🔧 Protocol ready | **P1** | 2 days |
| 3 | **Contextual Retrieval** | [Anthropic Blog](https://www.anthropic.com/news/contextual-retrieval) | ❌ | **P2** | 3 days |
| 4 | **Adaptive RAG** (complexity routing) | [Jeong et al., 2024](https://arxiv.org/abs/2403.14403) | 🔧 Scaffolded | **P2** | 3 days |
| 5 | **Corrective RAG (CRAG)** | [Yan et al., 2024](https://arxiv.org/abs/2401.15884) | 🔧 Scaffolded | **P2** | 5 days |
| 6 | **Late Chunking** | [Jina, 2024](https://arxiv.org/abs/2409.04701) | 🔧 Protocol exists | **P3** | 5 days |
| 7 | **Self-RAG** (reflection tokens) | [Asai et al., 2023](https://arxiv.org/abs/2310.11511) | ❌ | **P3** | 7 days |
| 8 | **Context Caching** (LLM-native) | Bedrock/Claude prompt caching | ❌ | **P3** | 2 days |
| 9 | **Speculative RAG** (multi-draft) | [Wang et al., 2024](https://arxiv.org/abs/2407.08223) — ICLR 2025 | ❌ | **P4** | 10 days |
| 10 | **GraphRAG** (KG-enhanced) | [Microsoft, 2024](https://github.com/microsoft/graphrag) | Neptune is P6 | **P4** | 10 days |
| 11 | **Modular RAG** (pipeline orchestration) | [Gao et al., 2024](https://arxiv.org/abs/2407.21059) | Partially | **P3** | 5 days |
| 12 | **Agentic RAG** (plan + multi-hop) | Multiple sources | ❌ | **P5** | 15 days |

### What Each Means for CentRAG

#### P1: Must Have for MVP

**Hybrid Search (Dense + BM25 + RRF)**
```
Current:  query → embed → Qdrant dense search → results
Target:   query → embed → [Qdrant dense, BM25 sparse] → RRF fusion → results
```
- **Why:** Dense search misses exact keyword matches. "Error code ABC-123" returns nothing because embeddings don't preserve exact strings. BM25 catches this.
- **RRF (Reciprocal Rank Fusion):** `score = Σ 1/(k + rank_i)` — merges two ranked lists.
- **Qdrant has built-in sparse vectors** — no extra infra needed.

#### P2: Differentiators

**Contextual Retrieval (Anthropic, 2024)**
- For each chunk during ingestion, ask Claude: *"Given this document, write a concise context for this chunk."*
- Prepend the context to the chunk before embedding.
- **Result:** +49% retrieval accuracy (Anthropic benchmark). Especially for chunks with pronouns, abbreviations, or implicit references.
- **Cost concern:** LLM call per chunk at ingestion. Mitigate with prompt caching.

**Corrective RAG (CRAG)**
- After reranking, check: Are ANY chunks above a confidence threshold?
- If **yes** → proceed to generation.
- If **no** → trigger corrective action:
  1. Rewrite the query (more specific, different angle)
  2. Try a different data source (switch namespace, try web search)
  3. Flag response as "low confidence" (honest uncertainty)
- **CentRAG status:** Scaffolded in `engine.py` Step 5 (confidence gate exists, correction loop is TODO).

#### P3: Cutting Edge

**Self-RAG (Asai et al., 2023)**
- Model generates special "reflection tokens" during output:
  - `[Retrieve]` — "I need to look something up"
  - `[Relevant]` / `[Irrelevant]` — critique of retrieved content
  - `[Supported]` / `[Unsupported]` — self-check of generated claims
- **CentRAG implementation:** Could be added as a post-generation validation step that uses a separate small model to critique the main model's output.

**Speculative RAG (Wang et al., 2024 — ICLR 2025)**
- Use a SMALL model (Haiku) to generate 3-5 draft answers from different document subsets, in PARALLEL.
- Use a LARGE model (Sonnet) to VERIFY and pick the best draft.
- **Why it matters:** Faster than sequential generation + higher accuracy from diverse perspectives.
- **CentRAG implementation:** Fits naturally into Adaptive RAG — route to speculative pipeline for complex queries.

---

## Part E: Architectural Patterns Beyond GoF

### Patterns Relevant to CentRAG at Scale

| Pattern | What It Solves | CentRAG Applicability | Priority |
|---------|---------------|:---------------------:|:--------:|
| **Hexagonal Architecture** (Ports & Adapters) | Decouple business logic from infra | ✅ Already following (Protocols = Ports, Impls = Adapters) | Now |
| **CQRS** (Command Query Responsibility Segregation) | Separate read/write paths for different optimization | ⚠️ Consider: writes (ingestion) go through SQS, reads go through cache+Qdrant | P3 |
| **Event Sourcing** | Append-only event log as source of truth | ⚠️ Audit log is already append-only. Temporal memory is append-only. Could formalize. | P4 |
| **Saga Pattern** | Distributed transaction compensation | 🔧 Ingestion pipeline: if embedding fails → delete chunks → mark doc failed | P2 |
| **Strangler Fig** | Gradually replace legacy systems | If CentRAG replaces existing search → route % of traffic gradually | P5 |
| **Sidecar Pattern** | Cross-cutting concerns as separate process | Langfuse agent, PII scanner, audit logger as sidecar containers | P3 |

### CentRAG Already Maps to Hexagonal Architecture

```
┌─────────────────────────────────────────────────┐
│                 CORE DOMAIN                      │
│  (Business rules, retrieval logic, memory logic) │
│  centrag/retrieval/engine.py                     │
│  centrag/abstractions/*.py (Ports)               │
└──────────────┬──────────────┬────────────────────┘
               │              │
    ┌──────────▼──┐    ┌──────▼──────────┐
    │ INPUT       │    │ OUTPUT          │
    │ ADAPTERS    │    │ ADAPTERS        │
    │ (Drivers)   │    │ (Driven)        │
    │             │    │                 │
    │ routes/     │    │ impl/qdrant.py  │
    │ MCP tools   │    │ impl/bedrock.py │
    │ CLI         │    │ impl/redis.py   │
    └─────────────┘    └─────────────────┘
```

### Resilience Patterns — Implementation Guide

| Pattern | Library | CentRAG Target | Config |
|---------|---------|---------------|--------|
| **Retry + Backoff** | `tenacity` | All external calls | `wait_exponential(min=1, max=30) + retry_if_exception_type(ConnectionError)` |
| **Circuit Breaker** | `pybreaker` or custom | Per-dependency (Qdrant, Redis, Bedrock, Cohere) | `fail_max=5, reset_timeout=30s` |
| **Bulkhead** | `asyncio.Semaphore` | Per-team concurrent Bedrock calls | `Semaphore(max_concurrent_per_team)` |
| **Timeout** | `asyncio.wait_for` | All external calls | Qdrant: 5s, Redis: 2s, Bedrock: 30s |
| **Fallback** | Custom | Cache fallback when Qdrant is down | Circuit open → return cached result or "service degraded" |

### Recommended Reading — Architecture

| # | Resource | Type | What It Covers | Time |
|:-:|---------|:----:|---------------|:----:|
| 1 | *Clean Architecture* — Robert C. Martin | 📖 Book | Hexagonal/Clean arch, dependency rule, use cases | 12 hrs |
| 2 | *Release It!* (2nd Ed) — Michael Nygard | 📖 Book | Circuit breakers, bulkheads, stability patterns | 10 hrs |
| 3 | [Alistair Cockburn — Hexagonal Architecture](https://alistair.cockburn.us/hexagonal-architecture/) | 📝 Blog | Original Ports & Adapters description | 1 hr |
| 4 | Martin Fowler — [CQRS](https://martinfowler.com/bliki/CQRS.html) | 📝 Blog | When (and when NOT) to use CQRS | 30 min |
| 5 | AWS Well-Architected — [Reliability Pillar](https://docs.aws.amazon.com/wellarchitected/latest/reliability-pillar/welcome.html) | 📄 Docs | Resilience patterns at scale | 3 hrs |
| 6 | *Designing Data-Intensive Applications* — Kleppmann | 📖 Book | Event sourcing, stream processing, consistency | 20 hrs |

---

## Part F: RAG Evaluation — Know If Your System Is Actually Good

### The Evaluation Stack

| Layer | What | Tool | When |
|-------|------|------|------|
| **Component** | Is retrieval finding the right chunks? | RAGAS (context precision/recall) | Every PR |
| **Pipeline** | Is the full answer correct and grounded? | DeepEval (faithfulness, relevance, hallucination) | Every PR |
| **Production** | Are real users getting good answers? | Langfuse (traces + user feedback) | Real-time |
| **Regression** | Did this change make things worse? | DeepEval CI gate | CI/CD |

### Key Metrics

| Metric | What It Measures | Target | How |
|--------|-----------------|:------:|-----|
| **Faithfulness** | Is the answer supported by retrieved context? No hallucination. | > 0.85 | RAGAS / DeepEval |
| **Answer Relevancy** | Does the answer actually address the question? | > 0.80 | RAGAS |
| **Context Precision** | Are retrieved chunks actually relevant? | > 0.80 | RAGAS |
| **Context Recall** | Did we find ALL relevant chunks? | > 0.75 | RAGAS |
| **Hallucination Rate** | % of claims not supported by sources | < 5% | DeepEval |
| **P95 Latency** | 95th percentile query response time | < 3s (cold), < 50ms (cache) | Langfuse / Locust |

### Recommended Reading — Evaluation

| # | Resource | Type | Time |
|:-:|---------|:----:|:----:|
| 1 | [RAGAS Documentation](https://docs.ragas.io/) | 📄 Docs | 2 hrs |
| 2 | [DeepEval Documentation](https://docs.confident-ai.com/) | 📄 Docs | 2 hrs |
| 3 | [Langfuse Documentation](https://langfuse.com/docs) | 📄 Docs | 2 hrs |
| 4 | [Arize Phoenix — LLM Observability](https://docs.arize.com/phoenix) | 📄 Docs | 1 hr |

---

## Part G: The 16-Week Learning Plan

> [!IMPORTANT]
> Each week has 3 parts: **Read** (theory), **Build** (CentRAG code), **Write** (ADR or doc).
> Budget ~10 hrs/week: 3 hrs reading, 5 hrs building, 2 hrs writing.

### Phase 1: Foundations (Weeks 1-4)

| Week | Read | Build | Write |
|:----:|------|-------|-------|
| **1** | DDIA Ch 1-3. Refactoring Guru: Strategy, Repository. | `docker compose up`. First Alembic migration. RLS policies. | ADR-001: Why Qdrant over OpenSearch |
| **2** | DDIA Ch 5-6. Clean Architecture Part III (SOLID). | Auth middleware: `X-API-Key` → `RequestContext`. Unit tests. | ADR-002: Why SQS FIFO over Celery |
| **3** | C4 Model (all 4 levels). FastAPI DI docs. ArjanCodes SOLID. | S3 upload → SQS FIFO → ingestion worker stub. | ADR-003: Why Qdrant L3 cache |
| **4** | Unstructured.io docs. Jina Late Chunking paper. Pinecone chunking guide. | Ingestion: parse → semantic chunk → embed (Bedrock Titan) → Qdrant upsert. | ADR-004: Chunking strategy (semantic + contextual) |

### Phase 2: Core RAG (Weeks 5-8)

| Week | Read | Build | Write |
|:----:|------|-------|-------|
| **5** | Qdrant multi-tenancy docs. Refactoring Guru: Chain of Responsibility. | Retrieval: embed query → Qdrant search (team_id filter) → return chunks. | ADR-005: Multi-tenancy isolation model |
| **6** | Cohere Rerank docs. Anthropic Contextual Retrieval blog. | Add reranking. Add BM25 (Qdrant sparse). Implement RRF fusion. | Update HLD with hybrid search diagram |
| **7** | Andrew Ng agentic talks (4 videos). CRAG Paper (Yan et al.). | CRAG validation loop: check confidence → rewrite query on low confidence. | ADR-006: Corrective retrieval design |
| **8** | Redis caching patterns. GPTCache code study. | Build L1 (LRU) + L2 (Redis) + L3 (Qdrant semantic) cache. Wire to retrieval engine. | Cache metrics dashboard spec |

### Phase 3: Memory & Differentiation (Weeks 9-12)

| Week | Read | Build | Write |
|:----:|------|-------|-------|
| **9** | Mem0 architecture docs. Zep Graphiti paper. Supermemory code. | Memory engine: extract facts → temporal versioning → `valid_from`/`valid_to`. | ADR-007: Temporal memory design |
| **10** | Self-RAG paper (Asai et al.). Adaptive RAG paper (Jeong et al.). | Adaptive RAG: classify query complexity → route to appropriate pipeline. | ADR-008: Adaptive retrieval strategy |
| **11** | Glean security whitepaper. AWS tenant isolation whitepaper. | PII redaction. Audit logging. Rate limiter. Cross-tenant penetration test. | Security test report |
| **12** | RAGAS docs. DeepEval docs. Langfuse tracing docs. | Integrate Langfuse. Build RAGAS evaluation on golden test set. DeepEval CI gate. | Quality metrics baseline doc |

### Phase 4: Production & Resilience (Weeks 13-16)

| Week | Read | Build | Write |
|:----:|------|-------|-------|
| **13** | *Release It!* Ch 4-5 (Stability Patterns). PyBreaker docs. | Circuit breakers per dependency. Bulkhead (Semaphore per team). Timeout on all calls. | ADR-009: Resilience strategy |
| **14** | CDK Workshop. AWS Well-Architected Reliability Pillar. | CDK stacks: VPC (3 AZs), Aurora, Redis, EKS, SQS. Deploy to dev account. | Infrastructure-as-Code walkthrough |
| **15** | AWS FIS docs. Locust docs. Speculative RAG paper (Wang et al.). | Load test (Locust: 50 teams, 100 concurrent). Chaos test: kill Qdrant pod. Fix P95. | Load test results + remediation |
| **16** | Re-read all CentRAG ADRs. Prepare architecture presentation. | Final polish. Write remaining ADRs. Record 10-minute architecture demo. | **10-minute architecture pitch deck** |

---

## Part H: Paper Reading List (Prioritized)

### Must Read (Before Week 8)

| Paper | Year | Key Idea | arxiv |
|-------|:----:|----------|-------|
| **CRAG — Corrective RAG** | 2024 | Validate retrieval confidence, correct on failure | [2401.15884](https://arxiv.org/abs/2401.15884) |
| **Adaptive RAG** | 2024 | Route queries by complexity to right pipeline | [2403.14403](https://arxiv.org/abs/2403.14403) |
| **Late Chunking** | 2024 | Embed full doc first, chunk token embeddings later | [2409.04701](https://arxiv.org/abs/2409.04701) |
| **Contextual Retrieval** | 2024 | LLM-generated context prepended to each chunk | [Anthropic Blog](https://www.anthropic.com/news/contextual-retrieval) |

### Should Read (Weeks 8-12)

| Paper | Year | Key Idea | arxiv |
|-------|:----:|----------|-------|
| **Self-RAG** | 2023 | Self-reflection tokens for retrieval/generation quality | [2310.11511](https://arxiv.org/abs/2310.11511) |
| **ReAct** | 2023 | Reason + Act loop for grounded LLM behavior | [2210.03629](https://arxiv.org/abs/2210.03629) |
| **Zep Graphiti** | 2025 | Temporal knowledge graph for agent memory | [2501.13987](https://arxiv.org/abs/2501.13987) |
| **Matryoshka Embeddings** | 2022 | Truncatable embeddings for flexible dimension | [2205.13147](https://arxiv.org/abs/2205.13147) |

### Stretch (Weeks 12+)

| Paper | Year | Key Idea | arxiv |
|-------|:----:|----------|-------|
| **Speculative RAG** | 2024 | Multi-draft generation + verification | [2407.08223](https://arxiv.org/abs/2407.08223) |
| **GraphRAG** | 2024 | Knowledge graph communities for summarization | [Microsoft GitHub](https://github.com/microsoft/graphrag) |
| **Modular RAG Survey** | 2024 | Taxonomy of all RAG patterns | [2407.21059](https://arxiv.org/abs/2407.21059) |
| **Reflexion** | 2023 | Self-reflection for agent improvement | [2303.11366](https://arxiv.org/abs/2303.11366) |

---

## Part I: Quick Reference Card

### Pattern → Code File Map

```
SOLID
├── SRP     → Every file (1 class = 1 responsibility)
├── OCP     → abstractions/*.py (extend via new impls)
├── LSP     → Any Protocol impl is swappable
├── ISP     → 6 small Protocols (not 1 big interface)
└── DIP     → engine.py depends on Protocols, not concretions

GoF Patterns
├── Strategy          → abstractions/*.py
├── Chain of Resp.    → retrieval/engine.py, middleware chain
├── Factory           → app.py (create_app)
├── Repository        → abstractions/vectorstore.py
├── Builder           → VectorFilter.for_team().with_condition()
├── Template Method   → RetrievalEngine.retrieve()
├── Composite         → MemoryProtocol (combines 3 stores)
├── Proxy / Lazy      → ✅ engine.py (Callable[[], Protocol] → @property)
├── Decorator         → [FUTURE] TracingEmbedder(BedrockEmbedder())
├── Observer          → [FUTURE] cache invalidation events
└── Adapter           → [FUTURE] QdrantAdapter → VectorStoreProtocol

Resilience
├── Circuit Breaker   → [FUTURE] pybreaker/custom per dependency
├── Bulkhead          → [FUTURE] asyncio.Semaphore per team
├── Retry + Backoff   → [FUTURE] tenacity on all external calls
├── Timeout           → [FUTURE] asyncio.wait_for
├── Fallback          → [FUTURE] cached result when circuit open
└── Graceful Shutdown → 🔧 Designed (tiered drain → flush → close → exit)

Agentic
├── ReAct             → Adaptive RAG (classify → act → observe)
├── Reflection/CRAG   → ✅ engine.py (advisor loop, context validation)
├── Tool Use          → MCP connectors + /v1/retrieve
├── Memory            → abstractions/memory.py (temporal versioning)
├── Governance        → middleware/auth.py (non-optional auth)
├── Token Budgeting   → ✅ engine.py (TokenBudgetManager, context compression)
├── Adaptive Thinking → ✅ engine.py (<search_strategy> CoT prompt separation)
├── Hierarchical Cancel → ✅ engine.py (asyncio.CancelledError propagation)
└── Planning          → [FUTURE] multi-hop decomposition

RAG 2025-2026
├── Hybrid Search     → [P1] Qdrant dense + sparse + RRF
├── Reranking         → [P1] CohereReranker impl
├── Contextual Retr.  → [P2] ingestion/contextualizer.py
├── Adaptive RAG      → [P2] LLMProtocol.classify_complexity()
├── CRAG              → ✅ engine.py advisor loop (confidence gate + query rewrite)
├── Late Chunking     → [P3] EmbedderProtocol.embed_with_late_chunking()
├── Self-RAG          → [P3] post-generation reflection
├── Context Caching   → [P3] Bedrock prompt caching
├── Speculative RAG   → [P4] multi-draft with small+large model
└── GraphRAG          → [P4] Neptune knowledge graph

Performance Engineering (claude-code inspired)
├── Parallel Startup  → ✅ app.py (asyncio.gather for PG/Redis/Qdrant)
├── Feature Flags     → ✅ config.py (enable_*_routes dynamic route inclusion)
├── Byte-bounded LRU  → ✅ cache.py (cachetools.LRUCache, getsizeof)
├── In-flight Dedup   → ✅ cache.py (asyncio.Task tracking, no thundering herd)
├── Stale-While-Reval → ✅ cache.py (SWR background refresh)
├── Slow Op Logger    → ✅ middleware/slow_logger.py (budget-based WARNING)
├── Session Cost Track → 🔧 Designed (per-session TokenUsage persistence)
└── Session Recovery  → 🔲 Phase 5 (conversation checkpointing)
```

> [!TIP]
> **How to use this document:** Don't try to learn everything at once.
> Follow the 16-week plan. Each week focuses on 1-2 patterns + 1 RAG advancement.
> By week 16, you'll have both the theoretical knowledge AND the working CentRAG code
> to prove it.
