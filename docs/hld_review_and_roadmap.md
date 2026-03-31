# HLD Review — Straight Talk Edition

> **⚠️ CONTEXT:** This is an internal self-review and coaching document from the early
> brainstorming phase. It captures the gap analysis that drove the creation of the
> production-grade `ARCHITECTURE_HLD.md` and `ARCHITECTURE_LLD.md`. Keep for learning
> context; the HLD/LLD are the authoritative architecture docs.

---

## Revised Score: 4/10

I was too generous at 5.5. Here's why I'm dropping it.

Your notes are a **brainstorming session**, not an HLD. An HLD is a document that another engineer — who has never spoken to you — can read and start building from. Your notes require a 2-hour conversation to fill in the blanks. That's the difference.

---

## The Hard Truth

I'm going to be direct because that's what you asked for.

### 1. You have ideas, not architecture.
"Upload Documents" is a feature. Architecture is: "Documents are uploaded via `POST /v1/documents` → validated (type, size, virus scan) → stored in S3 at `raw/{team_id}/{doc_id}` → a message is published to SQS FIFO queue → an ECS Fargate worker dequeues, parses with Unstructured.io, semantically chunks at 512 tokens with 50 token overlap → embeddings generated via Bedrock Titan v2 in batches of 100 → upserted to Qdrant collection `documents` with payload `{team_id, doc_id, namespace_id, chunk_index}` → CHUNKS rows inserted in Aurora PostgreSQL → document status updated to `ready` → SQS message ACK'd."

See the difference? Your version is 3 words. A buildable version is a paragraph.

### 2. Zero security = automatic rejection.
In financial services, submitting an HLD without a security section is like submitting a building blueprint without exits. The reviewer stops reading. You need:
- Auth mechanism (API key hashing, rotation, scoping)
- Namespace isolation (how Team A can't see Team B's data — specific mechanism, not "per usecase")
- SQL injection prevention (what stops the LLM from generating `DROP TABLE`?)
- PII handling (what if GOS DB returns credit card numbers?)
- Rate limiting (what stops a team from burning 100x their fair share?)

### 3. No data flows = reviewers can't evaluate your design.
Your static box diagram tells me **what exists**. It doesn't tell me **how data moves**. I need to trace a request from: user query → API gateway → auth check → cache lookup → vector search → re-rank → LLM generation → PII scrub → response. Without this, I can't find bottlenecks, single points of failure, or latency problems.

### 4. "Memory + RAG Layer" is treated as one thing. They're two.
- **RAG** = retrieving relevant documents to augment an LLM's context for a SINGLE query.
- **Memory** = remembering things ACROSS queries and sessions (user preferences, past conversations, learned facts).

Treating them as one thing shows a conceptual gap.

### 5. No technology decisions with justification.
You list GOS DB and Confluences as data sources (good). But you don't name:
- Which vector DB? (Qdrant? Pinecone? OpenSearch? Why?)
- Which embedding model? (Titan? OpenAI? Local?)
- Which LLM? (Claude? GPT? Self-hosted?)
- Which cache? (Redis? Memcached? In-process?)
- Which queue? (SQS? Kafka? RabbitMQ?)
- Which container orchestrator? (EKS? ECS? Lambda?)

An HLD without technology choices is a wishlist, not a design.

---

## Score Breakdown: What Each Point Means

| Score | Meaning |
|:-----:|---------|
| 1-3 | **Brainstorm stage** — Ideas exist but nothing is buildable |
| 4-5 | **Draft HLD** — Some components identified, major gaps in depth |
| 6-7 | **Reviewable HLD** — Architecture is clear, some gaps in detail |
| 8-9 | **Production-ready HLD** — Complete, buildable, reviewed |
| 10 | **Reference architecture** — Could be published as a best-practice guide |

**You're at 4.** Your instincts and vision are strong (that's rare and valuable). But the document artifact is incomplete.

| Dimension | Score | Why |
|-----------|:-----:|-----|
| Vision / Problem | **9/10** | CentRAG concept, Agent Studio gap analysis — excellent |
| Component ID | **6/10** | 5 MCP connectors right, but missing cache/memory/reranker/embedding |
| Data Flows | **1/10** | Zero sequence diagrams |
| Namespace Isolation | **2/10** | "Per usecase" without mechanism |
| Security | **0/10** | Not mentioned at all |
| API Design | **0/10** | No endpoints, no payloads |
| Memory Layer | **2/10** | Mentioned as a concept, no types/storage breakdown |
| Cache Layer | **0/10** | Not mentioned |
| Tech Choices | **3/10** | GOS DB/Confluence named, nothing else |
| Deployment | **0/10** | No AWS services, no infra |
| Observability | **4/10** | "Log traceability" shows awareness, no specifics |
| Scalability | **0/10** | Not addressed |
| **Weighted Average** | **4/10** | |

---

## Before / After: Rewriting One Section Properly

Here's how to take ONE item from your notes and make it HLD-quality.

### ❌ What You Wrote
```
3. MCP for GOS DB Connectivity
```

### ✅ What It Should Say

```markdown
### 3.3 GOS DB MCP Connector

**Purpose:** Provide AI agents with read-only, guardrailed access to JPMC's
internal GOS DB (Oracle-compatible) for structured data retrieval.

**Technology:** python-oracledb (thin mode), FastMCP Python SDK

**Tools Exposed:**
| Tool               | Description                                      |
|---------------------|--------------------------------------------------|
| query_gosdb         | Execute parameterized SELECT queries             |
| list_schemas        | List whitelisted schemas                         |
| list_tables         | List tables in a schema                          |
| describe_table      | Get column names, types, nullability             |

**Security:**
- Schema whitelisting: Only APP_DATA, ANALYTICS, REPORTING accessible
- SQL keyword blocking: DROP, TRUNCATE, ALTER, CREATE, DELETE rejected
- Parameterized queries only (`:name` bind syntax)
- PII redaction on all results (SSN, credit card, email patterns)
- Rate limiting: 20 queries/minute per caller
- Full audit log: caller_id, query, duration, success/failure

**Connection:**
- Async connection pool: min=2, max=10, increment=1
- Query timeout: 30 seconds (kills long-running queries)
- mTLS via Oracle Wallet (production) or password auth (dev)

**Data Flow:**
Agent → MCP Client → FastMCP Server → Guardrails Pipeline
→ validate_sql() → check_rate_limit() → execute_query()
→ redact_pii() → cap_result_size() → audit_log() → return
```

**That's the difference between 3/10 and 8/10 for a single component.**

---

## Complete Resource Library (100+ Resources)

> Updated 2026-03-31 after deep-dive competitive research on Supermemory, HydraDB,
> Zep/Graphiti, Mem0, NotebookLM, Glean, Bifrost, GPTCache, and others.

### Track 1: System Design Foundations (Non-Negotiable Starting Point)

#### 📖 Books
| Book | Author | Why Read It | Priority |
|------|--------|------------|:--------:|
| *Designing Data-Intensive Applications* | Martin Kleppmann | THE bible. Replication, partitioning, consistency, batch/stream. Chapters 1–9 will transform how you reason about systems. | **#1** |
| *System Design Interview Vol 1 & 2* | Alex Xu | Teaches the HLD framework: requirements → estimation → API → data model → scale. Each chapter = 1 design. | **#2** |
| *Fundamentals of Software Architecture* | Richards & Ford | Architecture patterns, trade-off analysis, decision frameworks. Best for transitioning to architect role. | **#3** |
| *Building Microservices* (2nd Ed) | Sam Newman | Service decomposition, integration patterns, deployment. Directly applicable to CentRAG. | **#4** |
| *Release It!* (2nd Ed) | Michael Nygard | THE book on stability patterns: circuit breakers, bulkheads, timeouts, steady-state. **Directly applicable to our resiliency architecture.** | **#5** |
| *Understanding Distributed Systems* | Roberto Vitillo | Shorter, more approachable intro to distributed systems than DDIA. Good warmup. | **#6** |
| *Staff Engineer* | Will Larson | How to operate as a senior IC / architect: influence without authority, technical strategy, decision-making at scale. | **#7** |

#### 🎓 Courses & Platforms
| Resource | Format | URL | Cost |
|---------|--------|-----|------|
| **ByteByteGo** | Video + articles | https://bytebytego.com | $79/yr |
| **Grokking System Design** | Interactive text | Educative.io → "Grokking" | ~$60 |
| **MIT 6.824 Distributed Systems** | Lectures + labs | https://pdos.csail.mit.edu/6.824/ | Free |
| **Exponent System Design** | Mock interviews | https://www.tryexponent.com | $99/mo |

#### 🎥 YouTube (Free)
| Channel | Best Playlist | Why |
|---------|-------------|-----|
| **ByteByteGo** | "System Design Interview" | Visual, concise, covers top 20 designs |
| **Gaurav Sen** | "System Design" | Deep dives on individual components |
| **Hussein Nasser** | "Backend Engineering" | Thorough on protocols, DBs, networking |
| **Jordan Has No Life** | All | Deep, unfiltered system design |
| **ArjanCodes** | "Software Architecture" | Practical Python architecture patterns |

---

### Track 2: Architecture Diagramming & Decision Documentation

#### The C4 Model (Learn This)
| Resource | URL |
|---------|-----|
| C4 Model Official | https://c4model.com |
| Simon Brown's Talk (1hr) | YouTube: "Visualising software architecture with the C4 model" |
| Structurizr DSL (diagrams-as-code) | https://structurizr.com/dsl |
| IcePanel (interactive C4) | https://icepanel.io |

#### Architecture Decision Records (ADRs)

> [!IMPORTANT]
> **ADRs are the single fastest way to develop architect-level thinking.**
> They force you to articulate WHY, consider alternatives, and name trade-offs.
> Architects are not people who make better decisions — they're people who
> **document and defend** their decisions.

| Resource | Type | URL |
|---------|:----:|-----|
| Martin Fowler — ADR Overview | 📄 Blog | https://martinfowler.com/articles/architectureDecisions.html |
| ADR Templates (GitHub collection) | 💻 Template | https://github.com/joelparkerhenderson/architecture-decision-record |
| Michael Nygard's ADR Template | 📄 Template | Search "Nygard ADR template" |
| Spotify Engineering — How We Use ADRs | 📝 Blog | Search "Spotify architecture decision records" |
| AWS Prescriptive Guidance — ADRs | 📄 Docs | https://docs.aws.amazon.com/prescriptive-guidance/latest/architectural-decision-records/ |

**Do this NOW for CentRAG:** Create `docs/adr/` and write your first 5 ADRs:

```
docs/adr/
├── ADR-001-qdrant-over-opensearch.md        # Why Qdrant: payload filtering + tiered sharding
├── ADR-002-sqs-fifo-over-celery.md          # Why SQS FIFO: message groups per team, no Celery+FIFO
├── ADR-003-qdrant-semantic-cache.md         # Why Qdrant for L3 (ElastiCache lacks RediSearch)
├── ADR-004-temporal-memory-versioning.md    # Why version facts (Zep/HydraDB pattern)
├── ADR-005-three-az-deployment.md           # Why 3 AZ (quorum for Qdrant/Redis/etcd)
```

Each ADR follows this format:
```markdown
# ADR-001: Use Qdrant over OpenSearch for Vector Database

**Status:** Accepted
**Date:** 2026-03-31
**Deciders:** [your name]

## Context
CentRAG requires a vector database that supports per-team data isolation,
multi-tenant filtering at query time, and horizontal scaling.

## Decision
We will use Qdrant with payload-based filtering (team_id in payload).

## Alternatives Considered
1. **OpenSearch (k-NN)** — Rejected: No native payload filtering. Requires
   separate index per team or post-query filtering.
2. **Pinecone** — Rejected: Managed SaaS only. Cannot self-host in private VPC.
3. **pgvector** — Rejected: Good for small scale, but HNSW index doesn't scale
   well beyond ~5M vectors with filtered search.

## Consequences
- ✅ Single collection, all teams, payload-filtered search (<15ms)
- ✅ Self-hosted in private subnet (no data leaving VPC)
- ⚠️ Must manage Qdrant cluster ourselves (3 nodes, persistent volumes)
- ⚠️ Smaller community than Pinecone/Weaviate
```

#### Diagramming Tools
| Tool | Best For | URL |
|------|---------|-----|
| **Excalidraw** | Quick whiteboard diagrams | https://excalidraw.com |
| **draw.io (diagrams.net)** | Detailed architecture diagrams | https://app.diagrams.net |
| **Mermaid.js** | Diagrams in markdown | https://mermaid.js.org |

---

### Track 3: Security Architecture

| Resource | Type | URL |
|---------|:----:|-----|
| OWASP LLM Top 10 | 📄 Guide | https://owasp.org/www-project-top-10-for-large-language-model-applications/ |
| OWASP API Security Top 10 | 📄 Guide | https://owasp.org/API-Security/ |
| AWS Well-Architected Security Pillar | 📄 Docs | https://docs.aws.amazon.com/wellarchitected/latest/security-pillar/ |
| AWS SaaS Tenant Isolation Strategies | 📄 Whitepaper | https://docs.aws.amazon.com/whitepapers/latest/saas-tenant-isolation-strategies/ |
| PostgreSQL Row-Level Security | 📄 Docs | https://www.postgresql.org/docs/current/ddl-rowsecurity.html |
| AWS KMS Envelope Encryption | 📄 Docs | https://docs.aws.amazon.com/kms/latest/developerguide/concepts.html |
| AWS IAM Best Practices | 📄 Docs | https://docs.aws.amazon.com/IAM/latest/UserGuide/best-practices.html |
| NeMo Guardrails | 💻 Code | https://github.com/NVIDIA/NeMo-Guardrails |
| Guardrails AI | 💻 Code | https://www.guardrailsai.com/ |
| HashiCorp Vault Tutorial | 🎓 Tutorial | https://developer.hashicorp.com/vault/tutorials |

---

### Track 4: RAG Engineering

| Resource | Type | What You'll Learn |
|---------|:----:|-------------------|
| RAG Survey Paper | 📄 Paper | https://arxiv.org/abs/2312.10997 — Comprehensive survey: naive → advanced → modular → agentic |
| DeepLearning.AI — Building & Evaluating Advanced RAG | 🎓 Course | https://www.deeplearning.ai/short-courses/building-evaluating-advanced-rag/ |
| DeepLearning.AI — Agentic RAG with LlamaIndex | 🎓 Course | Search deeplearning.ai |
| Patterns for Building LLM-Based Systems (Eugene Yan) | 📝 Blog | https://eugeneyan.com/writing/llm-patterns/ — Best single blog post on LLM engineering |
| Deconstructing RAG (LangChain) | 📝 Blog | https://blog.langchain.dev/deconstructing-rag/ |
| 12 RAG Pain Points & Solutions | 📝 Blog | Search "12 RAG pain points" on Towards Data Science |
| LlamaIndex Docs — Retrieval Strategies | 📄 Docs | https://docs.llamaindex.ai |
| LangChain RAG Tutorial | 📄 Docs | https://python.langchain.com/docs/tutorials/rag/ |
| RAGAS Evaluation Framework | 💻 Code | https://docs.ragas.io |
| Cohere Rerank v3 | 📄 Docs | https://docs.cohere.com/docs/reranking |
| Unstructured.io (Document Parsing) | 💻 Code | https://docs.unstructured.io |
| Pinecone Chunking Strategies Guide | 📝 Blog | https://www.pinecone.io/learn/chunking-strategies/ |
| Reciprocal Rank Fusion Explained | 📝 Blog | Search "RRF retrieval RAG" on Medium |

---

### Track 5: Vector DBs & Caching

| Resource | Type | What You'll Learn |
|---------|:----:|-------------------|
| Qdrant Multi-Tenancy Guide | 📄 Docs | https://qdrant.tech/documentation/guides/multiple-partitions/ |
| Qdrant Tiered Multi-Tenancy (v1.16+) | 📄 Docs | https://qdrant.tech/documentation/guides/tiered-multitenancy/ |
| Qdrant Quantization (cost optimization) | 📄 Docs | https://qdrant.tech/documentation/guides/quantization/ |
| Redis University (Free) | 🎓 Course | https://university.redis.io |
| Redis Semantic Caching for LLMs | 📝 Blog | https://redis.io/blog/semantic-caching-llms/ |
| pgvector Tutorial | 📄 Docs | https://github.com/pgvector/pgvector |
| HNSW Algorithm Paper | 📄 Paper | Search "Efficient HNSW graphs" |
| Matryoshka Embeddings (dimension reduction) | 📄 Paper | https://arxiv.org/abs/2205.13147 |
| **Bifrost AI Gateway** (Go-based, cache-native) | 💻 Code | Search "Bifrost AI gateway" on GitHub |
| **LiteLLM Proxy** (LLM gateway + caching) | 📄 Docs | https://docs.litellm.ai |
| **GPTCache** (reference semantic cache) | 💻 Code | https://github.com/zilliztech/GPTCache |

---

### Track 6: Memory Layers — Your SME Domain

> [!IMPORTANT]
> **This is where CentRAG differentiates from every competitor.**
> No competitor combines multi-tenant memory with temporal versioning, semantic cache,
> and log-to-RAG in one platform. OWN this space. Study ALL of these deeply.

| Resource | Type | What You'll Learn |
|---------|:----:|-------------------|
| **Mem0 Documentation** | 📄 Docs | https://docs.mem0.ai — Memory extraction, conflict resolution, graph storage |
| **Mem0 GitHub** | 💻 Code | https://github.com/mem0ai/mem0 — Study the extraction pipeline and composite store |
| **Supermemory** | 💻 Code | https://github.com/supermemory/supermemory — Vector-Graph hybrid, hot/deep tiering, MCP support, smart forgetting |
| **Zep Graphiti** (Temporal Knowledge Graph) | 💻 Code | https://github.com/getzep/graphiti — Bi-temporal model, episode/entity/community subgraphs |
| **Zep Graphiti Paper** | 📄 Paper | https://arxiv.org/abs/2501.13987 — Temporal knowledge graph architecture, validity intervals |
| **HydraDB Blog** | 📝 Blog | https://hydradb.com/blog — Why vector DBs aren't enough, append-only versioning, relational mapping |
| **Zep Documentation** | 📄 Docs | https://www.getzep.com — Production TKG engine, custom ontologies via Pydantic |
| **MemGPT (Letta) Paper** | 📄 Paper | https://arxiv.org/abs/2310.08560 — OS-inspired memory management for LLMs |
| Mem0 vs Zep vs Supermemory | 📝 Blog | Search "Mem0 vs Zep comparison 2025" on dev.to |

**What to study in each:**
| Product | Focus On |
|---------|---------|
| **Mem0** | How `add()` and `search()` APIs work, fact extraction prompts, composite store (KV + vector + graph) |
| **Supermemory** | Hot/deep tiered architecture, decay scoring, Memory Router (zero-code integration) |
| **Zep/Graphiti** | `valid_from`/`valid_to` on every fact, contradiction resolution, episode subgraphs |
| **HydraDB** | Why "similarity ≠ relevance", relational mapping, append-only versioning (git-like) |

---

### Track 7: Competitor Codebases — Study Production Systems

> [!TIP]
> **Don't just star these repos.** For each one: (1) Clone & run locally, (2) Read
> the connector/plugin interface, (3) Read how they handle multi-tenancy, (4) Write
> a 1-page note: "What they do better / What CentRAG does better."

| Codebase | What It Is | What to Study | Link |
|----------|-----------|---------------|------|
| **Onyx (Danswer)** | Enterprise RAG platform | Connector architecture, RBAC, Docker deploy, 30+ connectors | https://github.com/onyx-dot-app/onyx |
| **R2R (SciPhi)** | Production RAG framework | Ingestion pipeline, evaluation, API design | https://github.com/SciPhi-AI/R2R |
| **Langfuse** | LLM observability | Trace model, evaluation framework, prompt management | https://github.com/langfuse/langfuse |
| **Qdrant** | Vector DB | HNSW internals, payload filtering, sharding, multi-tenant | https://github.com/qdrant/qdrant |
| **Unstructured** | Document parsing | PDF/DOCX/HTML parsing pipeline, chunking strategies | https://github.com/Unstructured-IO/unstructured |
| **RAGAS** | RAG evaluation | Faithfulness, context precision, answer relevancy metrics | https://github.com/explodinggradients/ragas |
| **AWS MCP Servers** | Reference MCP implementations | How AWS designs MCP tool interfaces | https://github.com/awslabs/mcp |

#### Enterprise RAG Products to Study (Understand the Market)
| Product | What to Learn From Them |
|---------|------------------------|
| **Glean** | Permission-aware retrieval (syncs RBAC from source apps), Enterprise Graph, single-tenant isolation |
| **NotebookLM** | Source grounding with inline citations, long-context models (1M+ tokens), "full_context" mode for small doc sets |
| **Vectara** | RAG-as-a-Service API design, corpus isolation, Boomerang re-ranking |
| **Cohere** | Rerank v3 API, embed v3 with Matryoshka dimensions, enterprise search patterns |

---

### Track 8: MCP Protocol

| Resource | Type | URL |
|---------|:----:|-----|
| MCP Official Specification | 📄 Spec | https://modelcontextprotocol.io |
| MCP Python SDK | 💻 Code | https://github.com/modelcontextprotocol/python-sdk |
| FastMCP Guide | 📄 Docs | https://gofastmcp.com |
| AWS MCP Servers | 💻 Code | https://github.com/awslabs/mcp |
| MCP Inspector (Testing) | 💻 Tool | `npx -y @modelcontextprotocol/inspector` |
| Awesome MCP Servers | 📄 List | https://github.com/punkpeye/awesome-mcp-servers |

---

### Track 9: AWS Architecture & Certifications

| Resource | Type | URL |
|---------|:----:|-----|
| AWS Well-Architected Framework | 📄 Docs | https://aws.amazon.com/architecture/well-architected/ |
| AWS Well-Architected — AI/ML Lens | 📄 Docs | https://docs.aws.amazon.com/wellarchitected/latest/machine-learning-lens/ |
| AWS Well-Architected — Reliability Pillar | 📄 Docs | https://docs.aws.amazon.com/wellarchitected/latest/reliability-pillar/ |
| AWS CDK Workshop (Python) | 🎓 Workshop | https://cdkworkshop.com |
| EKS Best Practices Guide | 📄 Docs | https://aws.github.io/aws-eks-best-practices/ |
| RAG on AWS Reference Architecture | 📝 Blog | https://aws.amazon.com/blogs/machine-learning/build-a-rag-based-generative-ai-solution/ |
| Amazon Bedrock Developer Guide | 📄 Docs | https://docs.aws.amazon.com/bedrock/ |
| AWS Fault Injection Simulator | 📄 Docs | https://docs.aws.amazon.com/fis/ (chaos testing) |
| AWS Skill Builder | 🎓 Labs | https://skillbuilder.aws |

#### 🏆 Certification Path (SME credibility signal)

| Cert | What It Proves | Study Time | When |
|------|---------------|:----------:|:----:|
| **AWS Solutions Architect — Associate (SAA-C03)** | You can design secure, scalable, cost-optimized AWS architectures | ~4 weeks | **Month 1-2** ← Start here |
| **AWS Solutions Architect — Professional (SAP-C02)** | You can design multi-account, multi-region, complex AWS systems. THE architect cert. | ~8 weeks | **Month 4-6** |
| **AWS Machine Learning Engineer — Associate (MLA-C01)** | Production ML/AI on AWS: Bedrock, SageMaker, MLOps pipelines. Replaced the retired MLS-C01. | ~6 weeks | **Month 8+** |
| **AWS AI Practitioner (AIF-C01)** | Foundational AI/ML concepts on AWS. Easy win for credibility. | ~2 weeks | **Anytime** |

> [!TIP]
> **Highest ROI action for credibility: Get SAA-C03.** It takes ~4 weeks of focused study
> and immediately signals to leadership, CIOs, and hiring managers that you can
> design on AWS at a professional level. Do this FIRST, before the Professional cert.

---

### Track 10: Observability & LLMOps

| Resource | Type | What You'll Learn |
|---------|:----:|-------------------|
| Langfuse Docs — Tracing | 📄 Docs | https://langfuse.com/docs/tracing |
| RAGAS Documentation | 📄 Docs | https://docs.ragas.io |
| Arize Phoenix | 📄 Docs | https://docs.arize.com/phoenix |
| OpenTelemetry Python | 📄 Docs | https://opentelemetry.io/docs/languages/python/ |
| LangSmith Documentation | 📄 Docs | https://docs.smith.langchain.com |
| DeepEval (LLM testing) | 💻 Code | https://github.com/confident-ai/deepeval |
| Litmus Chaos (K8s chaos testing) | 💻 Code | https://litmuschaos.io |
| `circuitbreaker` Python lib | 💻 Code | https://github.com/fabfuel/circuitbreaker |

---

## 12-Week SME Architect Roadmap

> [!IMPORTANT]
> This isn't a reading plan. It's a **build plan**. Every week produces a concrete
> CentRAG deliverable. By week 12, you've built real components AND have
> the architectural knowledge to defend them in any review.

### Phase 1: Foundations (Weeks 1-3) — "I Understand the Landscape"

| Week | Study | Build (CentRAG) | Deliverable |
|:----:|-------|-----------------|-------------|
| **1** | DDIA chapters 1-3 (Data Models, Storage, Encoding). Watch 5 ByteByteGo videos. | Set up PostgreSQL locally. Create all CentRAG tables. Apply RLS + `FORCE`. | Working schema with RLS that blocks cross-tenant access |
| **2** | DDIA chapters 4-6 (Replication, Partitioning, Transactions). Alex Xu Vol 1 ch 1-4. | Build API key generation + auth middleware (FastAPI). Wire to PostgreSQL. | Auth middleware: `X-API-Key` → `team_id` resolution in <5ms |
| **3** | C4 Model (all 4 levels). OWASP LLM Top 10. Martin Fowler's ADR blog. | Re-draw CentRAG HLD in Excalidraw (Context, Container, Component). Write first 5 ADRs. | Professional C4 diagrams + 5 documented decisions with rationale |

### Phase 2: Core RAG (Weeks 4-6) — "I Can Build a RAG Pipeline"

| Week | Study | Build (CentRAG) | Deliverable |
|:----:|-------|-----------------|-------------|
| **4** | DeepLearning.AI Advanced RAG. Pinecone chunking guide. Unstructured.io docs. | S3 upload → SQS FIFO → ingestion worker (parse → semantic chunk → embed → Qdrant upsert). | Upload a PDF → it's searchable in Qdrant (namespace-isolated) |
| **5** | Qdrant multi-tenancy docs. Cohere rerank docs. Clone + study Onyx connector code. | Retrieval endpoint: embed query → Qdrant search (team_id filter) → Cohere rerank → return top-5. | `POST /v1/retrieve` returns ranked chunks from YOUR uploaded doc |
| **6** | Redis caching patterns. Study GPTCache code. Study Bifrost gateway architecture. | Build L1 (LRU) + L2 (Redis exact) + L3 (Qdrant semantic) cache. Wire LLM generation with Bedrock Claude. | Full RAG query with cache — 2nd identical query returns in <50ms |

### Phase 3: Memory & Differentiation (Weeks 7-9) — "I Build What Nobody Else Has"

| Week | Study | Build (CentRAG) | Deliverable |
|:----:|-------|-----------------|-------------|
| **7** | Clone + run Mem0 locally. Read Supermemory hot/deep code. Read Zep Graphiti paper. | Memory engine: extract facts → store with `valid_from`/`valid_to` → temporal versioning. | Memory layer that versions facts + decay scoring (not overwrite) |
| **8** | Glean security whitepaper. AWS tenant isolation whitepaper. HydraDB blog. | PII redaction + audit logging + rate limiter. Integrate into retrieval flow. | End-to-end query with auth → rate → RAG → PII → audit → response |
| **9** | RAGAS docs. Langfuse tracing. Start AWS SAA-C03 prep. | Integrate Langfuse (per-span tracing). Build RAGAS evaluation on golden test set. | Dashboard: per-query traces + weekly quality scores |

### Phase 4: Production Readiness (Weeks 10-12) — "I'm Ready for Architecture Review"

| Week | Study | Build (CentRAG) | Deliverable |
|:----:|-------|-----------------|-------------|
| **10** | AWS WA Reliability + Security. Read *Release It!* stability chapters. | Implement circuit breakers (per dependency). Bulkhead (Semaphore per team). Chaos test: kill Qdrant pod. | Graceful degradation: Qdrant down → cached results, not crash |
| **11** | CDK workshop. EKS best practices. AWS FIS docs. | CDK stacks: VPC (3 AZs), Aurora, Redis, EKS, SQS. Deploy to dev. | `cdk deploy` creates full CentRAG infra from scratch |
| **12** | Prepare architecture presentation. Re-read all CentRAG docs + ADRs. | Load test (Locust: 50 teams, 100 concurrent queries). Fix P95 violations. Write final ADRs. Present to team. | **10-minute architecture presentation** with live demo + metrics |

---

## After 12 Weeks You'll Have

- ✅ A **working CentRAG MVP** (not just docs)
- ✅ Professional **C4 diagrams** in Excalidraw
- ✅ **10+ ADRs** documenting every design decision with rationale
- ✅ **Langfuse dashboard** showing per-query quality metrics
- ✅ **RAGAS evaluation** proving retrieval quality
- ✅ **Chaos test results** proving resiliency
- ✅ **AWS SAA-C03** certification (or in progress)
- ✅ A **10-minute architecture pitch** you can deliver to any CIO

**That's not a developer's portfolio. That's an architect's portfolio.**

---

## What Makes an SME vs an Engineer

| Dimension | Engineer | SME / Architect |
|-----------|---------|-----------------|
| **Knowledge** | Knows HOW to build | Knows WHY to build THIS WAY (and what alternatives were rejected) |
| **Decisions** | Follows documented architecture | Creates and DOCUMENTS architecture decisions (ADRs) |
| **Trade-offs** | Picks the popular tool | Evaluates 3+ options, quantifies trade-offs, picks the right one |
| **Communication** | Explains code | Explains SYSTEM BEHAVIOR to non-technical stakeholders |
| **Failures** | Debugs incidents | DESIGNS FOR FAILURE before it happens |
| **Scope** | Owns a service | Owns the INTERACTIONS between services |
| **Evaluation** | Writes unit tests | Defines QUALITY METRICS for the entire system |
| **Competitors** | Uses a library | Studies HOW it works and WHERE to differentiate |

### Your CentRAG SME Evidence Checklist

When someone asks "Are you an SME in this?", you should be able to show:

- [ ] **HLD + LLD** with C4 diagrams, data flows, and tech decisions ← you have these
- [ ] **10+ ADRs** for design decisions ← write these now
- [ ] **Competitor analysis** — "We chose X over Y because Z" ← you have this
- [ ] **Working code** — end-to-end retrieval with auth, cache, PII ← build this
- [ ] **Quality metrics** — RAGAS scores, P95 latency, cache hit ratio ← measure this
- [ ] **Resiliency proof** — chaos test showing graceful degradation ← test this
- [ ] **Cost model** — honest, benchmarked, per-team breakdown ← you have this
- [ ] **Presentation** — 10-min pitch a CIO can follow ← prepare this
- [ ] **Certification** — AWS SAA-C03 at minimum ← get this

---

## The One Thing That Will Level You Up Fastest

> [!IMPORTANT]
> **Read *Designing Data-Intensive Applications* chapters 1-9.**
>
> This single book will fix your gaps in: data flow thinking, scalability reasoning,
> consistency trade-offs, partitioning strategies, and failure mode analysis.
> Everything else builds on top of this foundation.
>
> If you only do ONE thing from this entire document, do this.

## The Second Thing

> [!TIP]
> **Write ADRs for every decision you've already made.**
>
> You've already made 10+ architectural decisions on CentRAG (Qdrant over OpenSearch,
> SQS FIFO over Celery, temporal memory versioning, 3 AZs, Qdrant for L3 cache, etc.).
> Document each one as an ADR. This is the fastest way to develop architect-level
> thinking because it forces you to articulate WHY, consider alternatives, and name trade-offs.
>
> Architects are not people who make better decisions.
> They're people who **document and defend** their decisions.

---

## Final Word

You have something most engineers don't: **the right instincts**. You identified the correct problem (teams wasting time on RAG), the right connector technology (MCP), the right isolation concept (per-team namespacing), and you're now asking the right questions about memory, resiliency, competitive positioning, and how to become an SME.

The gap between where you are and SME/architect level is not knowledge — it's **evidence**. Build the system. Document the decisions. Measure the results. Present to stakeholders.

Stop brainstorming. Start specifying. Start building. Start measuring.
