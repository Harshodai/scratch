# Full Docs Audit — All 6 Markdown Files

**Date:** 2026-03-31  
**Scope:** Every `.md` file in `docs/`  
**Categories:** ❌ Mistakes, 🚧 Missing Steps, ⚠️ Unsupported Assumptions, 🎭 Invented Details

---

## File 1: `ARCHITECTURE_HLD.md` (566 lines, 33KB)

### Confidence: 8/10 — Strongest document

| # | Cat | Location | Issue | Severity |
|---|-----|----------|-------|----------|
| 1 | ⚠️ | §10 Deployment | VPC shown with **2 AZs** ("Public Subnets (2 AZs)", "Private App Subnets (2 AZs)"). In `RESILIENCY_LOGS_REQUIREMENTS.md` we explicitly require **3 AZs** and explain why 2 AZs cause quorum failure. | **High** |
| 2 | ⚠️ | §11 Cost | EKS Nodes: "6x r6g.large on-demand ~$550." Actual pricing: r6g.large = $0.1008/hr × 24 × 30 = ~$72.6 each × 6 = **~$436**, not $550. Minor overestimate. | Low |
| 3 | ⚠️ | §11 Cost | Neptune: "$350/month." db.r6g.large Multi-AZ = ~$0.348/hr × 2 (writer+reader) × 24 × 30 = ~$501. **Underestimated by ~$150.** | Medium |
| 4 | 🚧 | §6 Security | No mention of **BYOK / Envelope Encryption**. The privacy framework in `APP_LOGS_PRIVACY_LANGSMITH.md` promises 5-layer cryptographic isolation, but the HLD security section doesn't reference it. A CIO reading just the HLD won't see the strongest privacy guarantee. | **High** |
| 5 | 🚧 | §10 Deployment | No **3rd AZ** in the deployment diagram. Should match the resiliency doc. | Medium |
| 6 | 🚧 | §12 Phases | RBAC and PII are Phase 5 (weeks 10-12), but the business case doc calls PII redaction **P3** and says it should happen before multi-team deploy. Ordering conflict. | Medium |
| 7 | ✅ | Overall | Data flows (§8), C4 diagrams (§3-4), tech decisions table (§9), namespace isolation (§5), API key lifecycle (§6.2), RBAC matrix (§6.3) — all technically correct and well-structured. | — |

---

## File 2: `ARCHITECTURE_LLD.md` (938 lines, 32KB)

### Confidence: 7.5/10 — Good structure, some code-level issues

| # | Cat | Location | Issue | Severity |
|---|-----|----------|-------|----------|
| 1 | ❌ | §1.2 RLS | RLS policies shown but **`FORCE ROW LEVEL SECURITY`** is missing. Without `FORCE`, table owners and superusers bypass RLS. The privacy doc mentions this but the LLD doesn't implement it. | **High** |
| 2 | ❌ | §5.1 Cache | `hash(query)` used for L1 key. Python's built-in `hash()` is NOT deterministic across processes (randomized per PEP 456 since Python 3.3). L1 cache will have misses across pod restarts even for identical queries. Should use `hashlib.sha256()`. | Medium |
| 3 | ⚠️ | §5.1 Cache | `redis.ft_search()` for L3 semantic cache implies RediSearch module is installed. Not called out in HLD's tech decisions or infra requirements. ElastiCache Redis doesn't natively include RediSearch — you'd need **MemoryDB** or self-hosted Redis Stack. | **High** |
| 4 | ⚠️ | §4.2 Worker | Says "Python 3.12 + **Celery**" but HLD §4 says "ECS Fargate, auto-scale" and the ingestion queue is SQS FIFO. Celery doesn't natively support SQS FIFO queues (only standard SQS via `kombu`). If using SQS FIFO, skip Celery and use a direct SQS consumer. Or use Celery with Redis/RabbitMQ as broker. **Contradictory tech choices.** | **High** |
| 5 | 🚧 | §3.2 Base | `BaseConnector.ingest_to_rag()` takes `team_id: str` and `namespace_id: str` but existing built MCP connectors (`gosdb_mcp.py`, `dynamodb_mcp.py`, `athena_mcp.py`) don't implement `BaseConnector`. They're standalone FastMCP tools. Interface exists on paper but not in code. | Medium |
| 6 | 🚧 | §1.1 ER | No `FORCE ROW LEVEL SECURITY` on the `teams` table itself. If a rogue query `SELECT * FROM teams` bypasses RLS, all team names are visible. `teams` table should probably use RLS or be restricted via views. | Medium |
| 7 | ⚠️ | §5.2 | Cache invalidation "Delete all L2 keys matching `cache:{team_id}:*`" uses `KEYS` pattern matching. At scale, `KEYS *` blocks Redis for seconds. Should use `SCAN` with cursor-based iteration, or tag-based invalidation. | Medium |
| 8 | ✅ | Overall | ER diagram, API schemas (req/res), error codes, module tree, testing strategy, CDK stacks — all well-structured and technically sound. | — |

---

## File 3: `BUSINESS_CASE_AND_PLAYBOOK.md` (353 lines, 24KB)

### Confidence: 6.5/10 — Good framing, soft numbers

| # | Cat | Location | Issue | Severity |
|---|-----|----------|-------|----------|
| 1 | 🎭 | §1.1 | "**25% of queries** are redundant re-explanations" — this is a made-up statistic. No source, no measurement basis. May be directionally true but presenting it as fact is misleading for an exec audience. | **High** |
| 2 | 🎭 | §2.1 | "LLM cost: $3,000–$10,000/team before, ~**$62/team** after" — the $62 figure comes from the HLD's $3,100/mo ÷ 50 teams. But that $3,100 estimate excludes LLM API costs at scale. The HLD shows $60/mo for Bedrock Claude (5M input tokens). If 50 teams each make 100 queries/day at 3K tokens each, that's 50×100×3000 = 15M tokens/day × 30 = 450M tokens/month × $3/1M = **$1,350/month** for input alone plus output tokens. Real LLM cost is likely **$100-200/team**, not $62. | **High** |
| 3 | 🎭 | §3.1 ROI | "Per-Team Infrastructure: $3,000/team/mo" — this assumes every team runs their own EKS cluster + Aurora + Redis. In practice, teams might share infra or use simpler setups (a single EC2 + pgvector). The $3M "before" number is therefore inflated, making the ROI model look better than reality. | Medium |
| 4 | 🎭 | §3.2 | "Payback period: < 1 month" — derived from the inflated $250K/month savings. If real savings are half that (still significant), payback is ~1-2 months. Still fast, but "<1 month" is optimistic. | Medium |
| 5 | ⚠️ | §2.1 | "Cache hit ratio: 40-60% (L1+L2+L3)" — this is a reasonable industry benchmark for semantic caching but not measured for CentRAG. State as target, not fact. | Low |
| 6 | ⚠️ | §6.1 | Star counts for OSS repos (e.g., "Onyx 15K+", "Mem0 25K+") are point-in-time. They will become stale. Minor but worth noting if this doc is presented externally. | Low |
| 7 | 🚧 | §5.1 | DR gate says "RTO < 30 min" but the resiliency doc says RTO < 2 min for AZ failure and < 60 min for region failure. Inconsistent. | Medium |
| 8 | ✅ | Overall | Task prioritization (§4), sprint plan, production checklist, competitor analysis — all well-structured and useful. | — |

---

## File 4: `hld_review_and_roadmap.md` (319 lines, 17KB)

### Confidence: 8.5/10 — Strongest pedagogical document

| # | Cat | Location | Issue | Severity |
|---|-----|----------|-------|----------|
| 1 | ⚠️ | §Score | "Revised Score: 4/10" then "Weighted Average: 4/10" — but the weighted average of the sub-scores (9+6+1+2+0+0+2+0+3+0+4+0 = 27/12 = 2.25) doesn't equal 4. The text score and dimension scores are inconsistent. If final score is 4, some dimensions must be weighted higher (which would be valid but isn't stated). | Low |
| 2 | ✅ | Overall | The review feedback itself is excellent: precise, actionable, with specific before/after examples. Resource library is comprehensive (60+ items, all real URLs at time of writing). Study plan is structured. No invented resources. | — |

---

## File 5: `APP_LOGS_PRIVACY_LANGSMITH.md` (622 lines, 36KB)

### Confidence: 7/10 — Strong on privacy, already-corrected log pipeline

| # | Cat | Location | Issue | Severity |
|---|-----|----------|-------|----------|
| 1 | ❌ | §A.3 | The log ingestion worker (Steps 1-9) still shows "Generate embeddings" and "Upsert to Qdrant" as if we embed every log line. The correction banner references the resiliency doc, but the pipeline diagram itself hasn't been rewritten. A reader scanning the diagram will form the wrong mental model. | **High** (mitigated by banner) |
| 2 | ⚠️ | §B.6 | "LangSmith: Self-hosted ❌ (SaaS only)" — LangSmith actually launched a self-hosted option (LangSmith Enterprise) in late 2024. This comparison row is outdated/incorrect. | Medium |
| 3 | ⚠️ | §B.6 | "LangSmith: Auto-evaluation (RAGAS) ❌ (manual)" — LangSmith has built-in auto-evaluation with custom evaluators. Calling it "manual" is misleading. | Medium |
| 4 | ⚠️ | §C.3 | "Plaintext DEK exists IN MEMORY ONLY for < 1 second" — the 1-second claim is plausible for simple encrypt-and-wipe operations, but during a retrieval query where we need to decrypt multiple chunks sequentially, the DEK may need to live in memory for the duration of the request (potentially seconds). More accurate: "DEK is wiped after request completion, never persisted to disk." | Medium |
| 5 | 🚧 | §C.3 | BYOK envelope encryption for **embeddings** is mentioned ("Encrypted before upsert") but the HLD doesn't design for this. If embeddings are encrypted at rest in Qdrant, you can't do vector similarity search on encrypted vectors — Qdrant needs plaintext vectors to compute distances. This is a **fundamental conflict**: either embeddings are searchable (plaintext in Qdrant) or encrypted (unsearchable). The correct statement: embeddings are encrypted **at rest** via Qdrant's disk encryption with team CMKs, but are plaintext in Qdrant's memory during search. | **High** |
| 6 | 🚧 | §B.4 | AI trace tables have RLS but no `FORCE ROW LEVEL SECURITY`, same issue as LLD §1.2. | Medium |
| 7 | ✅ | §C.7-C.9 | Leadership messaging (CIO, Directors, POs, Compliance) is excellent. FAQ answers are precise and defensible. Trust framework is the strongest section. | — |

---

## File 6: `RESILIENCY_LOGS_REQUIREMENTS.md` (550 lines, 33KB)

### Confidence: 7.5/10 — Already audited and corrected in previous pass

| # | Cat | Location | Issue | Severity |
|---|-----|----------|-------|----------|
| 1 | ✅ | All | Previously identified issues (cost math, Fluent Bit pseudocode, bulkhead mechanism, RTO scope) have been **corrected**. | — |
| 2 | ⚠️ | §1.4 | Fluent Bit pseudoconfig: now labeled as pseudocode (good), but "SAMPLE: INFO at 5%" implies Fluent Bit can do probabilistic sampling. Real Fluent Bit doesn't have a native "sample at X%" filter — you'd need a Lua filter with `math.random()`. | Low |
| 3 | 🚧 | §3.1 FR-2 | FR-2.2 says "System SHALL perform hybrid retrieval (dense + sparse + KG)". Neptune (KG) is listed as P6 in the business case and as an open question in HLD §14. Making it a SHALL (mandatory) conflicts with it being a maybe. Should be "System SHOULD" or scope KG as Phase 2. | Medium |
| 4 | ✅ | §2, §3, §4 | Resiliency patterns, FR/NFR tables, architect/developer split — all solid. | — |

---

## Cross-Document Inconsistencies

| Issue | Doc A | Doc B | Resolution Needed |
|-------|-------|-------|-------------------|
| **AZ count** | HLD: 2 AZs in deployment diagram | Resiliency: 3 AZs required, 2 AZs cause quorum failure | Update HLD to 3 AZs |
| **RTO target** | Business Case: < 30 min | Resiliency: < 2 min (AZ), < 60 min (region) | Align to resiliency doc's scoped targets |
| **LLM cost/team** | Business Case: ~$62/team | HLD: $3,100 total / 50 = $62 | Both are wrong; Bedrock LLM cost underestimated (see audit item) |
| **PII timing** | Business Case: P3, before multi-team | HLD Phase 5: weeks 10-12 | Align — PII should be earlier |
| **Celery vs SQS** | LLD: "Celery" for ingestion worker | HLD: "SQS FIFO" as queue | Pick one: SQS FIFO → direct consumer, or Celery → Redis/RabbitMQ broker |
| **RLS FORCE** | Privacy doc: mentions `FORCE ROW LEVEL SECURITY` | LLD: omits it | Add FORCE to LLD |
| **BYOK + embeddings** | Privacy doc: "embeddings encrypted before upsert" | Reality: can't search encrypted vectors | Clarify: disk-level encryption, plaintext in memory for search |
| **Neptune priority** | Business Case: P6 (optional) | Resiliency FR: "SHALL" (mandatory) | Align to P6 / SHOULD |
| **LangSmith comparison** | Logs doc: "SaaS only, no self-hosted" | Reality: LangSmith Enterprise self-hosted exists | Correct comparison table |

---

## Overall Confidence Rating

| Document | Score | Verdict |
|----------|:-----:|---------|
| `hld_review_and_roadmap.md` | **8.5/10** | Pedagogically excellent. Minor score arithmetic issue. |
| `ARCHITECTURE_HLD.md` | **8/10** | Best technical doc. Missing BYOK mention and AZ count issue. |
| `ARCHITECTURE_LLD.md` | **7.5/10** | Good structure. Celery/SQS conflict and RLS FORCE gap. |
| `RESILIENCY_LOGS_REQUIREMENTS.md` | **7.5/10** | Already corrected. FR/NFR solid. Minor alignment issues. |
| `APP_LOGS_PRIVACY_LANGSMITH.md` | **7/10** | Strong privacy section. Embedding encryption conflict is fundamental. LangSmith comparison stale. |
| `BUSINESS_CASE_AND_PLAYBOOK.md` | **6.5/10** | Good framing but several invented statistics and inflated ROI numbers. |

### **Aggregate: 7.5/10**

**What's genuinely strong:** Architecture patterns, security model, namespace isolation, API design, module structure, reusability framework, and the privacy trust framework.

**What needs fixing before presenting:** Cost numbers need honest rebasing, AZ count alignment, Celery/SQS decision, `FORCE ROW LEVEL SECURITY`, and the embedding encryption claim.
