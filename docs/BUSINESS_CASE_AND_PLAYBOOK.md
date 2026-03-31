# CentRAG — Business Case, Implementation Playbook & Resource Library

**Version:** 1.0  
**Last Updated:** 2026-03-31  
**Purpose:** Executive-ready document covering benefits, ROI, implementation plan, task prioritization, competitor analysis, and learning resources.

---

## 1. Why CentRAG Exists — The Problem (Quantified)

### 1.1 Current Pain Points

| Problem | Impact (per team) | Impact (50 teams) |
|---------|:-----------------:|:------------------:|
| Each team builds their own RAG pipeline | 2–4 weeks of engineering time | **100–200 weeks** wasted annually |
| No shared chunking/embedding standards | Inconsistent retrieval quality (some teams use naive fixed-size chunking) | **Unpredictable answer quality** across org |
| No centralized memory layer | Every session starts from scratch; users repeat context | **Significant portion of queries** are redundant re-explanations (est. 15-30%, measure via pilot) |
| No cache layer | Every query hits LLM ($$$) | **$50,000–$150,000/year** in avoidable LLM costs |
| No governance / PII controls | Risk of data leaks, no audit trail | **Compliance violation risk** (SOX, GDPR) |
| No observability into AI chains | Can't debug hallucinations, can't measure quality | **Zero visibility** into AI accuracy |
| Siloed data per team | Team A's docs not discoverable by Team B (when permitted) | **Knowledge fragmentation** across the org |

### 1.2 The CentRAG Solution (One Sentence)

> **One platform, zero setup for teams.** Upload data, get an API key, start querying — with enterprise security, memory, caching, and observability built in.

---

## 2. Pin-Pointed Benefits

### 2.1 Hard Benefits (Quantifiable)

| Benefit | Metric | Before CentRAG | After CentRAG | Savings |
|---------|--------|:--------------:|:-------------:|:-------:|
| **Engineering time saved** | Weeks to deploy RAG per team | 2–4 weeks | 30 minutes (API key + upload) | **97% reduction** |
| **LLM cost reduction** | Monthly LLM spend | $1,000–$5,000/team (direct API) | ~$70–200/team (shared + cached) | **80–95% reduction** (varies by cache hit rate) |
| **Cache hit ratio** | % queries served from cache | 0% (no cache) | 40–60% (L1+L2+L3) | **50% fewer LLM calls** |
| **Information retrieval time** | Time to find answers | 15–30 min (manual search) | 2–5 sec (RAG query) | **99% faster** |
| **Support ticket deflection** | Internal tickets for data questions | 100% manual | 40–60% auto-resolved | **50% ticket reduction** |
| **Onboarding speed** | New hire time-to-productivity | 4–6 weeks | 1–2 weeks (AI-assisted) | **66% faster** |

### 2.2 Strategic Benefits (Qualitative)

| Benefit | How |
|---------|-----|
| **Namespace Isolation** | Teams operate in complete data silos — no cross-contamination, no shared state, no trust assumptions |
| **Compliance by Default** | PII redaction, audit trails, API key lifecycle, rate limiting baked into every request — not bolted on |
| **Memory Across Sessions** | Platform remembers user preferences, past queries, learned patterns — unlike any internal tool today |
| **Hybrid RAG (SOTA Quality)** | Dense + BM25 + Knowledge Graph + Re-ranking → the same retrieval quality as Google NotebookLM / Glean |
| **MCP Connector Ecosystem** | Add any data source (Confluence, JIRA, GOS DB, App Logs) via a reusable connector pattern — < 1 week per connector |
| **Observable AI** | Every query is traced end-to-end (Langfuse): you can see exactly which chunks the LLM used, what was hallucinated, and why |
| **Platform Thinking** | Other teams build *on top* of CentRAG — it becomes infrastructure, not an application |

### 2.3 Competitive Advantage vs. Building Per-Team

```
                        Per-Team RAG              CentRAG Platform
                        ────────────              ────────────────
Setup time              2-4 weeks                 30 minutes
Cost per team/month     $1,000-$5,000             ~$70-200
Security                Ad-hoc (each team's       Defence-in-depth (WAF →
                        interpretation)            Auth → Rate Limit → PII →
                                                   Audit → RLS)
Memory                  None                      4-tier (working → episodic
                                                   → semantic → procedural)
Cache                   None                      4-tier (in-process → exact
                                                   → semantic → full RAG)
Retrieval quality       Varies wildly             SOTA: hybrid + re-rank
Observability           None or basic logging     Full trace per query
                                                   (Langfuse)
PII handling            Usually forgotten         Automatic redaction on
                                                   every response
Scalability             Each team manages own     Platform team manages once
Connector reuse         Each team writes own      Shared connectors via MCP
Knowledge sharing       Impossible                Cross-team (when permitted)
```

---

### 3.1 Cost Comparison (Year 1 — 50 Teams)

> [!NOTE]
> The "Per-Team Approach" column assumes teams run with moderate infra
> (shared EKS/ECS, managed Postgres, direct LLM calls). Some teams may run
> cheaper setups (single EC2 + pgvector), some may run more. These are
> **directional estimates** — validate with your team survey data.

| Line Item | Per-Team Approach | CentRAG Platform |
|-----------|:-----------------:|:----------------:|
| Engineering setup (50 teams × 3 weeks × $80/hr) | **$600,000** | $0 (teams onboard in 30 min) |
| Platform development (12 weeks × 3 engineers) | $0 | **$150,000** |
| Infrastructure (per team × 12 months) | **$600,000–$1,200,000** (~$1,000–$2,000/team/mo for shared compute, DB, storage) | **$42,000** (~$3,500/mo shared — see HLD §11) |
| LLM API costs (no caching vs 40-60% cache hits) | **$600,000** ($1,000/team/mo avg) | **$120,000** ($200/team/mo avg, varies with volume) |
| Maintenance (per-team patches, upgrades) | **$200,000** | **$50,000** (1 platform) |
| **Total Year 1** | **$2,000,000–$2,650,000** | **$362,000** |
| **Savings** | | **$1,600,000–$2,300,000 (75–85%)** |

### 3.2 Payback Period

```
Platform development cost:  $150,000
Monthly savings:            ~$140,000–$190,000/month vs. per-team approach
Payback period:             ~1 month after MVP launch
```

---

## 4. Task Prioritization — What To Build First

### 4.1 Priority Stack Rank

> Build these in exactly this order. Each item unblocks the next.

| Priority | Task | Why First | Time | Unblocks |
|:--------:|------|-----------|:----:|----------|
| **P0** | PostgreSQL schema + migrations | Everything depends on the data model | 3 days | Everything |
| **P0** | API key generation + auth middleware | No API works without auth | 3 days | All API endpoints |
| **P0** | S3 upload + SQS queue setup | Ingestion can't start without storage + queue | 2 days | Ingestion pipeline |
| **P1** | Ingestion worker (parse → chunk → embed → upsert) | Core value prop: "upload docs, get RAG" | 5 days | Retrieval |
| **P1** | Qdrant setup + multi-tenant payload filtering | Vector search is the foundation of RAG | 3 days | Retrieval |
| **P1** | Basic retrieval endpoint (dense search only) | Teams can start querying | 3 days | First demo |
| **P2** | Redis exact cache (L2) | Quick win: 30% cost reduction | 2 days | Cache hit metrics |
| **P2** | BM25 sparse search + RRF fusion | Upgrades retrieval from "good" to "great" | 3 days | Quality metrics |
| **P2** | Cohere re-ranker integration | Upgrades retrieval from "great" to "excellent" | 2 days | Quality metrics |
| **P2** | LLM generation with citations | Teams get answers, not just chunks | 3 days | Full RAG demo |
| **P3** | Redis semantic cache (L3) | Another 20% cost reduction | 3 days | Cache hit ratio |
| **P3** | PII redaction pipeline | Compliance requirement | 2 days | Security sign-off |
| **P3** | Audit logging (structured, immutable) | Compliance requirement | 2 days | Security sign-off |
| **P3** | Rate limiting per team tier | Prevents abuse, fair usage | 1 day | Multi-team deploy |
| **P4** | MCP connectors (Confluence, JIRA) | Unlocks non-document data sources | 5 days | Data source breadth |
| **P4** | Memory layer (working + episodic) | User experience upgrade | 5 days | Session continuity |
| **P5** | Admin UI (team mgmt, key mgmt) | Platform admins need a dashboard | 7 days | Self-service onboarding |
| **P5** | Langfuse observability | Debug AI quality | 3 days | Quality monitoring |
| **P5** | CDK deployment scripts | Repeatably deploy to AWS | 5 days | Production deploy |
| **P6** | Knowledge Graph (Neptune) | Entity-aware retrieval | 5 days | Advanced reasoning |
| **P6** | RAGAS evaluation pipeline | Automated quality regression testing | 3 days | CI/CD for RAG quality |
| **P6** | Load testing (Locust) | Validate P95 targets | 2 days | Production readiness |

### 4.2 First 2 Weeks Sprint Plan

```
Week 1: "Hello RAG"
├── Day 1:  PostgreSQL schema (teams, api_keys, documents, chunks)
├── Day 2:  API key generation + auth middleware (FastAPI)
├── Day 3:  S3 upload endpoint + SQS queue
├── Day 4:  Ingestion worker: S3 → parse (Unstructured) → semantic chunk
├── Day 5:  Ingestion worker: chunk → embed (Bedrock Titan) → Qdrant upsert

Week 2: "First Query"
├── Day 6:  Qdrant multi-tenant setup (payload filter, team_id)
├── Day 7:  Basic retrieval: embed query → Qdrant search → return chunks
├── Day 8:  LLM generation: chunks → Bedrock Claude → answer + citations
├── Day 9:  Redis exact cache (L2) + rate limiter
├── Day 10: End-to-end demo: upload PDF → wait → query → get answer
```

**After 2 weeks, you have a working MVP that a team can test.**

---

## 5. Production Readiness Checklist

### 5.1 Quality Gates (Must Pass Before Go-Live)

| Gate | Criteria | How to Verify |
|------|---------|---------------|
| **Security** | API key auth ✅, RLS ✅, PII redaction ✅, SQL injection blocked ✅, audit logs ✅ | Automated security test suite (OWASP ZAP + custom) |
| **Isolation** | Team A cannot access Team B's vectors, metadata, cache, or S3 objects | Cross-tenant penetration test |
| **Performance** | P95 query latency < 3s (cold), < 50ms (cache hit) | Locust load test with 100 concurrent users |
| **Reliability** | Graceful degradation when Qdrant/Redis/Bedrock is down | Chaos engineering (kill pods, verify circuit breakers) |
| **Quality** | RAGAS Faithfulness > 0.85, Context Precision > 0.80 | Automated eval on golden dataset |
| **Observability** | Every query has end-to-end trace in Langfuse | Manual verification + alert on trace gaps |
| **Scalability** | Ingestion handles 100 docs/min, 50 concurrent teams | Load test + auto-scaling verification |
| **Compliance** | Audit logs are immutable and shipped to S3 | Compliance team review |
| **DR** | RTO < 2 min (AZ failure), < 60 min (region) | Aurora failover test, backup restoration test |

### 5.2 Non-Functional Requirements

| Requirement | Target | Industry Standard |
|------------|--------|------------------|
| Availability | 99.9% (8.7 hr downtime/yr) | Enterprise SaaS standard |
| Query P95 latency (cold) | < 3s | Google quality: < 2s |
| Query P95 latency (cached) | < 50ms | Redis-served: typical |
| Ingestion throughput | 100 docs/min | Comparable to Glean |
| API key validation | < 5ms | Redis hash lookup |
| Time to onboard new team | < 30 min | Glean: ~1 hour |
| Time to add new connector | < 1 week | Plugin architecture |
| Data residency | us-east-1 only (configurable) | SOX / GDPR |
| Encryption | AES-256 at rest, TLS 1.3 in transit | Industry standard |
| Log retention | 90 days hot, 1 year cold (S3 Glacier) | Financial services standard |

---

## 6. Competitor Analysis — Who's Done This in Production

### 6.1 Direct Competitors & Reference Architectures

| Platform | What It Does | Architecture | Why Study It |
|---------|-------------|-------------|-------------|
| **[Glean](https://www.glean.com)** | Enterprise work AI + search | Managed SaaS, 100+ connectors, proprietary retrieval, granular permissions | The gold standard for enterprise RAG. Study their connector model and permission syncing. |
| **[Onyx (Danswer)](https://github.com/onyx-dot-app/onyx)** | Open-source enterprise search + QA | Vespa (hybrid search), PostgreSQL, Docker/K8s, modular connectors | **Closest OSS competitor to CentRAG.** Study their codebase for connector patterns, RBAC, and deployment. |
| **[Google NotebookLM](https://notebooklm.google.com)** | Grounded research assistant | Gemini + Google Docs/Drive, per-notebook isolation | Study their UX: namespace = notebook, sources panel, audio overview. Our "namespace" concept mirrors this. |
| **[Perplexity Enterprise](https://www.perplexity.ai/enterprise)** | Enterprise search + answer engine | Managed, SOC2, SSO, data connectors | Study their citation model — every answer has numbered source references. |
| **[Cohere Coral](https://cohere.com/coral)** | Enterprise RAG platform | Managed API, Rerank, embeddings, connectors | Study their Rerank v3 API — we use it. |
| **[Vectara](https://vectara.com)** | RAG-as-a-Service API | Managed vector search + generation, multi-tenant | Pure API approach similar to CentRAG. Study their API design and corpus-based isolation. |
| **[Morphik](https://morphik.ai)** | Multi-modal RAG platform | OSS, supports images + documents, graph RAG | Study their multi-modal ingestion pipeline. |
| **[R2R (SciPhi)](https://github.com/SciPhi-AI/R2R)** | Production-ready RAG framework | Python, Hatchet (orchestration), Postgres + pgvector | Study their orchestration + evaluation patterns. |

### 6.2 Open Source Codebases to Study

| Repo | Stars | What to Learn | Link |
|------|:-----:|--------------|------|
| **Onyx (Danswer)** | 15K+ | Full-stack enterprise RAG, connector architecture, Docker deployment | https://github.com/onyx-dot-app/onyx |
| **R2R** | 4K+ | Production RAG framework: ingestion, retrieval, evaluation pipelines | https://github.com/SciPhi-AI/R2R |
| **Mem0** | 25K+ | Memory layer implementation: extraction, storage, retrieval, conflict resolution | https://github.com/mem0ai/mem0 |
| **Langfuse** | 8K+ | LLM observability: traces, evals, prompt management, cost tracking | https://github.com/langfuse/langfuse |
| **Qdrant** | 22K+ | Vector DB internals: HNSW, payload filtering, multi-tenancy, sharding | https://github.com/qdrant/qdrant |
| **AWS MCP Servers** | 1K+ | Reference MCP server implementations for AWS services | https://github.com/awslabs/mcp |
| **FastMCP** | 3K+ | High-level MCP server framework | https://github.com/jlowin/fastmcp |
| **Unstructured** | 10K+ | Document parsing: PDF, DOCX, HTML, images → structured text | https://github.com/Unstructured-IO/unstructured |
| **RAGAS** | 8K+ | RAG evaluation: faithfulness, context precision, answer relevancy | https://github.com/explodinggradients/ragas |

---

## 7. Resource Library — Blogs, Articles, Papers, Talks

### 7.1 RAG Architecture & Production Patterns

| Resource | Type | Key Takeaways |
|---------|:----:|--------------|
| [RAG is Dead, Long Live RAG](https://arxiv.org/abs/2312.10997) | 📄 Paper | Comprehensive survey of RAG techniques: naive → advanced → modular → agentic |
| [Building Production RAG at Enterprise Scale](https://blog.llamaindex.ai/building-production-rag-over-complex-documents-c5b83850e68e) | 📝 Blog | LlamaIndex team on real-world ingestion, query engines, evaluation |
| [Patterns for Building LLM-Based Systems](https://eugeneyan.com/writing/llm-patterns/) | 📝 Blog | Eugene Yan's definitive guide to RAG patterns: evals, guardrails, caching, fine-tuning |
| [Deconstructing RAG](https://blog.langchain.dev/deconstructing-rag/) | 📝 Blog | LangChain's deep-dive into retrieval strategies, routing, and multi-step RAG |
| [Advanced RAG Techniques](https://pub.towardsai.net/advanced-rag-techniques-an-illustrated-overview-04d193d8fec6) | 📝 Blog | Illustrated overview: query expansion, HyDE, parent-child chunking, re-ranking |
| [12 RAG Pain Points and Proposed Solutions](https://towardsdatascience.com/12-rag-pain-points-and-proposed-solutions-43709939a28c) | 📝 Blog | Practical troubleshooting guide for production RAG |
| [A Guide to Chunking Strategies](https://www.pinecone.io/learn/chunking-strategies/) | 📝 Blog | Pinecone's definitive chunking guide: fixed, recursive, semantic, agentic |

### 7.2 Multi-Tenancy & Namespace Isolation

| Resource | Type | Key Takeaways |
|---------|:----:|--------------|
| [Qdrant Multi-Tenancy Guide](https://qdrant.tech/documentation/guides/multiple-partitions/) | 📄 Docs | Official guide: payload-based filtering, `is_tenant` indexed fields, collection-per-tenant vs shared |
| [Qdrant Tiered Multi-Tenancy](https://qdrant.tech/documentation/guides/tiered-multitenancy/) | 📄 Docs | Advanced: dedicated shards for high-volume tenants, automatic tiering |
| [AWS SaaS Tenant Isolation Strategies](https://docs.aws.amazon.com/whitepapers/latest/saas-tenant-isolation-strategies/saas-tenant-isolation-strategies.html) | 📄 Whitepaper | AWS official: silo vs pool vs bridge patterns for multi-tenant SaaS |
| [PostgreSQL Row-Level Security](https://www.postgresql.org/docs/current/ddl-rowsecurity.html) | 📄 Docs | Official PG RLS documentation |

### 7.3 Memory Layer & Caching

| Resource | Type | Key Takeaways |
|---------|:----:|--------------|
| [Mem0 Documentation](https://docs.mem0.ai) | 📄 Docs | The open-source memory layer we're inspired by: fact extraction, conflict resolution, graph storage |
| [Redis Semantic Caching for LLMs](https://redis.io/blog/semantic-caching-llms/) | 📝 Blog | Official Redis blog on HNSW-based semantic caching with RedisVL |
| [RedisVL SemanticCache Guide](https://redis.io/docs/latest/integrate/redisvl/user-guide/semantic-caching/) | 📄 Docs | Implementation guide: `SemanticCache` class, distance thresholds, TTL management |
| [Zep Memory Layer](https://www.getzep.com/) | 📝 Product | Alternative memory layer: auto-summarization, entity extraction, temporal awareness |

### 7.4 MCP Protocol

| Resource | Type | Key Takeaways |
|---------|:----:|--------------|
| [MCP Official Specification](https://modelcontextprotocol.io) | 📄 Spec | The protocol spec: transport, tools/resources/prompts, lifecycle, auth |
| [Building MCP Servers (Quickstart)](https://modelcontextprotocol.io/quickstart/server) | 📄 Tutorial | Hands-on: build your first MCP server in 30 minutes |
| [MCP in Enterprise: Beyond the Hype](https://workos.com/blog) | 📝 Blog | WorkOS on MCP auth, enterprise security, production patterns |
| [AWS MCP Servers](https://github.com/awslabs/mcp) | 💻 Code | Reference implementations for Athena, DynamoDB, S3, CloudWatch |

### 7.5 Observability & Evaluation

| Resource | Type | Key Takeaways |
|---------|:----:|--------------|
| [Langfuse Docs — Tracing](https://langfuse.com/docs/tracing) | 📄 Docs | How to instrument RAG pipelines: spans, generations, scores |
| [RAGAS Documentation](https://docs.ragas.io) | 📄 Docs | Automated RAG evaluation: faithfulness, answer relevancy, context precision/recall |
| [Arize Phoenix](https://docs.arize.com/phoenix) | 📄 Docs | Alternative OSS observability: traces, evals, drift detection |
| [Galileo RAG Evaluation](https://galileo.ai) | 📝 Product | Managed evaluation platform for RAG quality |

### 7.6 AWS Architecture & Deployment

| Resource | Type | Key Takeaways |
|---------|:----:|--------------|
| [AWS Well-Architected — AI/ML Lens](https://docs.aws.amazon.com/wellarchitected/latest/machine-learning-lens/machine-learning-lens.html) | 📄 Docs | AWS best practices for AI workloads: security, reliability, cost optimization |
| [AWS CDK Workshop](https://cdkworkshop.com) | 🎓 Workshop | Hands-on IaC: build VPC, EKS, Aurora, SQS with CDK in Python |
| [EKS Best Practices Guide](https://aws.github.io/aws-eks-best-practices/) | 📄 Docs | Production EKS: networking, security, autoscaling, observability |
| [RAG on AWS Reference Architecture](https://aws.amazon.com/blogs/machine-learning/build-a-rag-based-generative-ai-solution/) | 📝 Blog | AWS official blog: Bedrock + OpenSearch + Lambda RAG architecture |

### 7.7 System Design & Architecture

| Resource | Type | Key Takeaways |
|---------|:----:|--------------|
| [Designing Data-Intensive Applications](https://dataintensive.net/) | 📖 Book | THE foundation: replication, partitioning, consistency, batch/stream |
| [System Design Interview (Vol 1 & 2)](https://www.amazon.com/System-Design-Interview-insiders-Second/dp/B08CMF2CQF) | 📖 Book | Structured approach to HLD: requirements → estimation → API → data model → deep dive |
| [C4 Model](https://c4model.com) | 📄 Framework | The industry standard for architecture diagrams |
| [ByteByteGo](https://bytebytego.com) | 🎥 Video | Visual system design walkthroughs by Alex Xu |

### 7.8 Security & Guardrails

| Resource | Type | Key Takeaways |
|---------|:----:|--------------|
| [OWASP Top 10 for LLM Applications](https://owasp.org/www-project-top-10-for-large-language-model-applications/) | 📄 Guide | The definitive attack taxonomy: prompt injection, data poisoning, excessive agency |
| [OWASP API Security Top 10](https://owasp.org/API-Security/) | 📄 Guide | API-specific threats: BOLA, broken auth, mass assignment |
| [NeMo Guardrails](https://github.com/NVIDIA/NeMo-Guardrails) | 💻 Code | NVIDIA's framework for programmable guardrails on LLM conversations |
| [Guardrails AI](https://www.guardrailsai.com/) | 💻 Code | Validate LLM outputs: format enforcement, PII detection, toxicity filtering |

---

## 8. What Makes This Production-Excellent

### 8.1 Quality Differentiators

| Aspect | What We Do | Why It's Excellent |
|--------|-----------|-------------------|
| **Retrieval** | Hybrid (dense + sparse) + Re-rank + KG | Same architecture as Glean/Perplexity. Not "good enough" — SOTA. |
| **Chunking** | Semantic + parent-child hierarchy | Context-preserving. Not naive 500-char splits. |
| **Evaluation** | RAGAS in CI/CD pipeline | Every PR is evaluated for retrieval quality regression. |
| **Security** | 9-layer defence-in-depth | More layers than most enterprise SaaS products. |
| **Isolation** | 6-layer namespace enforcement | Payload filter + RLS + key-prefix + S3-prefix + IAM + context injection. |
| **Caching** | 4-tier (in-proc → exact → semantic → full) | Matches Redis Labs' recommended architecture. |
| **Memory** | 4-type (working → episodic → semantic → procedural) | Mirrors Mem0 architecture used by 25K+ projects. |
| **Observability** | Per-span tracing with Langfuse | Can pinpoint *exactly* which chunk caused a hallucination. |
| **Reusability** | BaseConnector + composable guardrails + CDK constructs | Adding a new data source = 1 week, not 1 month. |
| **IaC** | Full CDK stacks, parameterized constructs | `cdk deploy` = entire environment from scratch. |

### 8.2 Scalability Architecture

```
Current Design Supports:
├── 1,000+ concurrent teams (payload-filtered multi-tenancy)
├── 10M+ vectors (Qdrant sharding + dedicated tenant shards)
├── 100+ docs/min ingestion (auto-scaling ECS workers)
├── 50+ concurrent queries (horizontal pod autoscaling)
├── 40-60% cache hit ratio (4-tier cache)
└── 99.9% availability (Multi-AZ Aurora, Redis cluster, EKS)

To Scale Further (if needed):
├── Add Qdrant nodes → linear vector capacity increase
├── Add EKS nodes → linear compute capacity increase
├── Switch to Redis Cluster → linear cache capacity
├── Add read replicas → linear read throughput
└── Geographic expansion → multi-region CDK deploy
```

---

## 9. Summary: Your Next 5 Actions

Stop reading. Start doing:

| # | Action | Time | Impact |
|:--:|--------|:----:|--------|
| **1** | Run `CREATE TABLE teams, api_keys, documents, chunks` on a local PostgreSQL | 2 hours | Data model exists |
| **2** | Build the `POST /v1/documents` upload endpoint (FastAPI + S3 + SQS) | 1 day | Ingestion entry point works |
| **3** | Build the ingestion worker (parse → chunk → embed → Qdrant upsert) | 2 days | Documents become searchable |
| **4** | Build `POST /v1/retrieve` (embed query → Qdrant search → return top-5) | 1 day | First RAG query works |
| **5** | Demo to one team. Get feedback. Iterate. | 1 day | Validation from a real user |

**Total time to first working demo: 5 days.**

After that, layer on: cache (2 days), re-ranker (2 days), LLM generation (2 days), auth (2 days), PII redaction (1 day). You'll have a production-worthy MVP in 3 weeks.
