# Competitive Deep-Dive: Memory, Cache & Retrieval Layers

**Date:** 2026-03-31
**Purpose:** Validate CentRAG architecture against real production systems.
**Products Researched:** Supermemory, HydraDB, Zep/Graphiti, Mem0, NotebookLM, Glean, GPTCache/Bifrost/Redis LangCache

---

## 1. Memory Layer Landscape (2026)

### The Players

| Product | Architecture | Key Innovation | Self-Hosted | Best For |
|---------|-------------|---------------|:-----------:|---------|
| **Mem0** | KV + Vector + Graph | Plug-and-play memory middleware with framework integrations | ✅ OSS | General personalization, rapid integration |
| **Zep (Graphiti)** | Temporal Knowledge Graph | Bi-temporal model (event time + ingestion time), contradiction resolution | Partial (Graphiti OSS, platform cloud) | Enterprise compliance, audit trails, time-sensitive reasoning |
| **Supermemory** | Vector-Graph Hybrid | Hot/deep tiered memory, smart forgetting/decay, MCP support | ✅ OSS | Fast semantic retrieval, model-agnostic memory hub |
| **HydraDB** | Append-only Temporal Graph + Vector | Git-like version history, relational mapping, <200ms in-memory | ❌ Managed SaaS | Stateful agents that need decision history and relationship evolution |

### What CentRAG Has vs What We're Missing

| Capability | CentRAG (Current Design) | Supermemory | Zep/Graphiti | HydraDB | Gap? |
|-----------|--------------------------|-------------|-------------|---------|------|
| Working memory (session) | ✅ Redis TTL | ✅ Hot tier | ✅ Episode subgraph | ✅ In-memory | No |
| Episodic memory (past conversations) | ✅ Qdrant + PG | ✅ Vector search | ✅ Episode subgraph + semantic | ✅ Append-only | No |
| Semantic memory (knowledge graph) | ✅ Neptune | ✅ Knowledge graph | ✅ Community subgraph | ✅ Relational graph | No |
| Procedural memory (learned workflows) | ⚠️ Mentioned, not designed | ❌ | ❌ | ⚠️ Decision history | **Yes — low priority** |
| **Temporal tracking** (when facts change) | ❌ Not designed | ✅ Smart forgetting | ✅ **Bi-temporal model** | ✅ Git-like versioning | **🔴 YES — Medium gap** |
| **Contradiction resolution** | ⚠️ "LLM resolves conflict" | ✅ Temporal decay | ✅ **Validity intervals, invalidation** | ✅ Append + invalidate | **🔴 YES — Medium gap** |
| **Smart forgetting / decay** | ❌ No TTL-based relevance decay | ✅ Intelligent decay | ✅ Valid_to timestamps | ❌ Append-only (no decay) | **🟡 Minor gap** |
| Memory per team (isolation) | ✅ team_id RLS + payload | ❌ Not multi-tenant | ❌ Not multi-tenant | ❌ Not multi-tenant | **CentRAG wins** |
| MCP integration | ✅ Built | ✅ Built | ❌ | ❌ | CentRAG + Supermemory lead |

### 🔑 Key Insight: Temporal Memory is the Biggest Gap

Our memory layer currently overwrites or "LLM-resolves" conflicting facts. But in an enterprise setting:
- A user might say "Our primary database is Postgres" in January, then "We migrated to CockroachDB" in March
- Our current design would either keep the old fact or replace it — neither tracks the timeline
- **Zep's bi-temporal model and HydraDB's append-only versioning** both solve this properly

> [!IMPORTANT]
> **Recommendation:** Add a `valid_from` / `valid_to` timestamp pair to `MEMORY_ENTRIES` table.
> When a new fact conflicts with an existing one, set `valid_to = NOW()` on the old fact
> and `valid_from = NOW()` on the new one. This gives us temporal tracking without
> adopting a full TKG like Graphiti. Add this to Phase 3 (memory layer).

---

## 2. Cache Layer Landscape (2026)

### The Shift: Library → Gateway-Native

| Approach | Example | Pattern | Latency Overhead | Production Maturity |
|----------|---------|---------|:----------------:|:-------------------:|
| **AI Gateway** (2026 standard) | Bifrost (Go), Kong AI Plugin, LiteLLM | Cache as middleware plugin in proxy | μs–low ms | **High** |
| **Managed Service** | Redis LangCache, Upstash | Hosted semantic cache API | ~5ms | High |
| **Custom Infra** (our approach) | Redis + Qdrant | Build your own tiered cache | ~5-15ms | Medium (depends on implementation) |
| **Library** | GPTCache (Python) | In-process semantic cache | ~10-50ms | Low (scaling issues) |

### What CentRAG Has vs Industry Best Practice (2026)

| Capability | CentRAG | Industry 2026 Best Practice | Gap? |
|-----------|---------|------------------------------|------|
| L1: In-process exact match | ✅ LRU | ✅ Same | No |
| L2: Redis exact match | ✅ SHA256 key | ✅ Same | No |
| L3: Semantic similarity | ⚠️ Requires RediSearch (not in ElastiCache) | Gateway-native or Qdrant-backed | **🔴 YES** |
| Dual-layer hash bypass | ❌ Every L3 miss generates an embedding | ✅ Hash check first, embed only on L2 miss | **🟡 Minor** |
| Per-request threshold tuning | ❌ Global 0.95 threshold | ✅ Per-category or per-request via header | **🟡 Minor** |
| Event-based invalidation | ❌ TTL only | ✅ Document re-ingestion triggers invalidation | **🔴 YES** (designed but not event-driven) |
| Cache freshness checks | ❌ | ⚠️ Emerging (periodic re-validation) | 🟡 Future |
| Per-team cache metrics | ⚠️ Mentioned in NFR | ✅ Per-user, per-model, per-feature granularity | **🟡 Minor** |

### 🔑 Key Insight: L3 Backend Decision

Our audit already flagged that ElastiCache Redis doesn't include RediSearch.

**Options:**
1. ~~RediSearch~~ → Requires Redis Stack or MemoryDB (cost increase)
2. **Use Qdrant as L3 backend** → We already run it. Create a `cache_vectors` collection.
   - Pro: No new infra. Qdrant already handles vector search with payload filtering.
   - Con: Slightly higher latency than Redis (15ms vs 5ms). Acceptable.
3. **Skip L3 for MVP** → Use L1+L2 only. Add L3 later.

> [!TIP]
> **Recommendation:** Use Qdrant as the L3 semantic cache backend.
> Create a `cache_responses` collection with payload `{team_id, query_hash, ttl, response}`.
> This avoids introducing RediSearch/MemoryDB and leverages existing infrastructure.

---

## 3. Retrieval & Grounding: What NotebookLM and Glean Teach Us

### NotebookLM Architecture Takeaways

| NotebookLM Feature | What They Do | CentRAG Equivalent | Gap? |
|--------------------|-------------|---------------------|------|
| **Source grounding** | Every answer MUST cite specific source passages | ✅ `sources[]` in response with `chunk_index` + `relevance_score` | No |
| **Inline citations** | Source ID tokens embedded in generation output | ⚠️ We return sources separately, not inline | **🟡 Minor UX gap** |
| **Long-context models** | 1M+ token context → less aggressive chunking | ❌ We use 512-token chunks | **🟡 Worth exploring** |
| **Privacy-first** | User data never trains general models | ✅ BYOK + VPC isolation | No |
| **Multimodal** | Images, audio, video transcription | ❌ Text-only currently | **Phase 5+ feature** |
| **Audio overviews** | Auto-generated podcast-style summaries | ❌ | **Differentiator for later** |

> [!NOTE]
> **Interesting opportunity:** As Bedrock adds longer-context models (Claude 3.5 supports 200K),
> we could offer a "deep analysis" mode: instead of chunking + RAG, send the entire
> document to the LLM for small documents (<50 pages). This mirrors NotebookLM's approach
> and would produce higher-quality answers for focused document sets.
> Add as a P3 feature toggle: `mode: "rag" | "full_context"`.

### Glean Architecture Takeaways

| Glean Feature | What They Do | CentRAG Equivalent | Gap? |
|--------------|-------------|---------------------|------|
| **Single-tenant isolation** | Each customer gets isolated infra | ⚠️ Shared infra with payload filtering (by design, for cost) | Different approach — both valid |
| **Permission-aware retrieval** | Syncs RBAC from source apps (Slack, Drive, Jira) | ⚠️ We have team-level isolation, not source-level RBAC | **🟡 Phase 4+** |
| **100+ native connectors** | Pre-built connectors for SaaS apps | 3 built (GOS DB, DynamoDB, Athena) + 5 planned | **Expected — we're earlier stage** |
| **Enterprise Graph** | People ↔ Content ↔ Interactions | ⚠️ Neptune KG is P6 | **Future differentiator** |
| **Agentic RAG** | Agents dynamically route queries | ❌ Single retrieval path | **Phase 5+ feature** |
| **MCP support** | Using MCP for tool orchestration | ✅ Already built | CentRAG leads here |
| **Customer-hosted** | Can deploy in customer's VPC | ✅ CDK-based deployment | Parity |

> [!IMPORTANT]
> **Key Glean insight:** Their biggest moat is **permission syncing from source apps**.
> When they index Slack/Drive/Jira, they also index the RBAC rules.
> At query time, results are filtered by what the querying user can see.
>
> For CentRAG Phase 4 (Confluence/JIRA connectors), we should sync
> source-level permissions into our namespace model. This is a game-changer
> for enterprise adoption.

---

## 4. Updated Architecture Recommendations

### Memory Layer Changes (Phase 3)

```diff
  MEMORY_ENTRIES table:
    uuid id PK
    uuid team_id FK
    string user_context
    text memory_content
    string memory_type "fact|preference|event|relation"
    float relevance_score
    jsonb temporal_metadata
    string vector_id
+   timestamp valid_from DEFAULT NOW()
+   timestamp valid_to   -- NULL = currently valid
+   uuid superseded_by   -- FK to the newer memory that replaced this one
    timestamp created_at
    timestamp last_accessed
+   float decay_score DEFAULT 1.0  -- Decreases over time if not accessed
```

**Conflict resolution algorithm (inspired by Zep/HydraDB):**
```python
async def add_memory(self, fact, team_id):
    # 1. Search for existing similar memories
    existing = await self._search_similar(fact.content, team_id, threshold=0.9)

    if existing:
        # 2. DON'T overwrite — create a timeline
        await self._pg.execute("""
            UPDATE memory_entries
            SET valid_to = NOW(), superseded_by = :new_id
            WHERE id = :old_id AND valid_to IS NULL
        """, old_id=existing.id, new_id=new_memory_id)

    # 3. Insert new fact with valid_from = NOW()
    await self._pg.insert(
        memory_content=fact.content,
        valid_from=datetime.utcnow(),
        valid_to=None,  # Currently valid
        ...
    )
```

### Cache Layer Changes (Phase 2)

```diff
  Cache Tier Strategy:
    L1: In-process LRU (unchanged)
    L2: Redis exact match (unchanged)
-   L3: Redis semantic cache (RediSearch — NOT available in ElastiCache)
+   L3: Qdrant semantic cache (new collection: "cache_responses")
+       - payload: {team_id, query_hash, response, created_at}
+       - TTL: 1 hour (enforced via Qdrant point expiry or cron cleanup)
+       - Threshold: 0.95 cosine similarity (configurable per team tier)
    L4: Full RAG pipeline (unchanged)
```

### Retrieval Enhancement (Phase 2-3)

```diff
  POST /v1/retrieve request body:
    query: string
    namespace: string
    max_results: int
    include_sources: bool
    include_memory: bool
    temperature: float
+   mode: "rag" | "full_context"  // P3: for small doc sets, skip chunking
+   citation_style: "separate" | "inline"  // P3: inline = NotebookLM-style
```

---

## 5. Competitor Feature Matrix (Full)

| Feature | CentRAG | Glean | NotebookLM | Onyx (Danswer) | Vectara | Mem0 |
|---------|:-------:|:-----:|:----------:|:--------------:|:-------:|:----:|
| Multi-tenant namespace isolation | ✅ ✅ | ✅ (single-tenant) | ❌ (personal) | ⚠️ | ✅ | ❌ |
| Hybrid retrieval (dense+sparse) | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ |
| Re-ranking | ✅ Cohere | ✅ Proprietary | ✅ BGE | ✅ | ✅ Built-in | ❌ |
| Knowledge Graph | ✅ Neptune | ✅ Enterprise Graph | ❌ | ❌ | ❌ | ⚠️ |
| Memory layer | ✅ 4-tier | ❌ | ❌ | ❌ | ❌ | ✅ ✅ |
| Temporal memory | ❌ → **🔧 Planned** | ❌ | ❌ | ❌ | ❌ | ⚠️ |
| Semantic cache | ✅ 4-tier | Unknown | ❌ | ❌ | ❌ | ❌ |
| Source citations | ✅ | ✅ | ✅ ✅ (inline) | ✅ | ✅ | ❌ |
| MCP connectors | ✅ 3 built | ✅ 100+ | ❌ | ✅ 30+ | ❌ | ❌ |
| Self-hosted | ✅ CDK | ✅ (Enterprise) | ❌ | ✅ Docker | ✅ (Enterprise, Helm/TF) | ✅ |
| BYOK encryption | ✅ (disk-level) | Unknown | ❌ | ❌ | ❌ | ❌ |
| PII redaction | ✅ Auto | Unknown | ❌ | ❌ | ❌ | ❌ |
| AI observability | ✅ Langfuse | Unknown | ❌ | ❌ | ❌ | ❌ |
| Log-to-RAG pipeline | ✅ 4-stage | ❌ | ❌ | ❌ | ❌ | ❌ |
| Multimodal | ❌ | ✅ | ✅ ✅ | ⚠️ | ✅ | ❌ |
| Permission syncing from sources | ❌ → **Phase 4** | ✅ ✅ | ❌ | ✅ | ❌ | ❌ |

---

## 6. Resources: Where to Study These Systems

### Memory Layer

| Resource | Type | What You'll Learn |
|---------|:----:|-------------------|
| [Supermemory GitHub](https://github.com/supermemory/supermemory) | 💻 OSS | Vector-Graph hybrid, MCP integration, hot/deep tiering |
| [Zep Graphiti Paper](https://arxiv.org/abs/2501.13987) | 📄 Paper | Temporal knowledge graph architecture, bi-temporal model |
| [Graphiti GitHub](https://github.com/getzep/graphiti) | 💻 OSS | Production TKG engine: episodes, entities, communities |
| [Mem0 Architecture Docs](https://docs.mem0.ai/overview) | 📄 Docs | Memory types, extraction pipeline, conflict resolution |
| [HydraDB Blog](https://hydradb.com/blog) | 📝 Blog | Why vector DBs aren't enough for agent memory |
| [Zep vs Mem0 Comparison (dev.to)](https://dev.to) | 📝 Blog | Side-by-side feature/architecture comparison |

### Cache Layer

| Resource | Type | What You'll Learn |
|---------|:----:|-------------------|
| [Redis LangCache](https://redis.io/solutions/ai/) | 📄 Docs | Managed semantic caching for LLMs |
| [Bifrost AI Gateway](https://github.com/maximhq/bifrost) | 💻 OSS | Go-based AI proxy with built-in semantic cache |
| [LiteLLM Proxy](https://docs.litellm.ai) | 📄 Docs | LLM gateway with caching, routing, cost tracking |
| [GPTCache (Zilliz)](https://github.com/zilliztech/GPTCache) | 💻 OSS | Python semantic cache library (reference architecture) |

### Retrieval & Grounding

| Resource | Type | What You'll Learn |
|---------|:----:|-------------------|
| [Glean Security Whitepaper](https://www.glean.com/security) | 📄 Whitepaper | Permission-aware retrieval, single-tenant isolation |
| [Glean Connector Architecture](https://developers.glean.com) | 📄 Docs | How 100+ connectors sync content + permissions |
| [NotebookLM Design Deep-Dive (Medium)](https://medium.com) | 📝 Blog | Source grounding, inline citations, long-context strategy |
| [Onyx (Danswer) GitHub](https://github.com/onyx-dot-app/onyx) | 💻 OSS | Full-stack enterprise RAG with connector framework |
| [Vectara RAG API](https://docs.vectara.com) | 📄 Docs | RAG-as-a-Service API design, corpus isolation |

---

## 7. Impact on Confidence Rating

| Area | Before Research | After Research | Change |
|------|:--------------:|:--------------:|--------|
| Memory layer design | 7/10 | 8/10 | ↑ Temporal tracking gap identified, solution designed |
| Cache layer design | 7/10 | 8.5/10 | ↑ L3 backend decision made (Qdrant), industry patterns confirmed |
| Retrieval architecture | 8/10 | 8.5/10 | ↑ NotebookLM full-context mode opportunity, Glean permission insight |
| Competitive positioning | 7/10 | 8/10 | ↑ Unique feature combination confirmed, but comparing design-on-paper to shipped products |
| **Overall** | **7.5/10** | **8/10** | **↑ Research validated architecture, identified 3 actionable gaps** |

### CentRAG's Unique Position (What No Single Competitor Has)

> [!IMPORTANT]
> No competitor has ALL of these together:
> 1. **Multi-tenant namespace isolation** (6-layer) — Glean has single-tenant, others have none
> 2. **Memory layer** (Mem0-inspired + temporal) — Glean/NotebookLM/Vectara have none
> 3. **Semantic cache** (4-tier) — No competitor has this
> 4. **Log-to-RAG pipeline** (4-stage smart filtering) — Unique to CentRAG
> 5. **MCP connector ecosystem** — Only Glean has comparable connector breadth
> 6. **AI observability** (Langfuse traces) — No competitor bundles this
> 7. **BYOK encryption** — No OSS competitor offers this
>
> CentRAG's moat is the **intersection** of these capabilities, not any single one.
