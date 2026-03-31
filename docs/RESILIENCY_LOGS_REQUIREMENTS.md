# CentRAG — Resiliency Standards, Smart Log Storage & Requirements Specification

**Version:** 1.0  
**Last Updated:** 2026-03-31  
**Audience:** Architects, Engineering Leads, Developers  
**Standards Reference:** ISO 25010, AWS Well-Architected (Reliability Pillar), IEEE 29148

---

## Part 1: The Log Storage Problem (Corrected)

### 1.1 The Mistake in Our Previous Design

The previous architecture implied: "Ingest every log line → embed it → store in Qdrant."

**That's wrong.** Here's why:

| Metric | Raw Logs | After Smart Filtering |
|--------|:--------:|:---------------------:|
| Daily log volume (50 teams, EKS+ECS+Airflow) | **~500 GB/day** | **~5 GB/day** |
| Vectors stored per day (1024-dim, float32) | **~50M vectors** | **~50K vectors** |
| Qdrant storage needed per month | **~60 TB** | **~60 GB** |
| Embedding API cost per day (Titan v2) | **~$5,000/day** | **~$5/day** |
| Query relevance | Poor (noise drowns signal) | High (only meaningful events) |

**The problem isn't just cost — it's quality.** If you dump INFO-level heartbeat logs alongside ERROR stack traces, semantic search returns noise. The ERROR you need is buried under 10,000 "Health check OK" messages.

### 1.2 Corrected Architecture: 4-Stage Log Intelligence Pipeline

```
                    STAGE 1: FILTER (99% reduction)
                    ──────────────────────────────────
Raw Logs            Fluent Bit / OTel Collector
500 GB/day          ├── DROP: Health checks, heartbeats, debug noise
                    ├── DROP: Duplicate lines (dedup by content hash)
                    ├── SAMPLE: INFO logs at 5% rate
                    ├── KEEP: 100% of ERROR, FATAL, WARN
                    ├── KEEP: 100% of security events
                    └── KEEP: 100% of Airflow task failures
                    Output: ~10 GB/day (98% reduction)
                           │
                           ▼
                    STAGE 2: AGGREGATE (10x reduction)
                    ──────────────────────────────────
Filtered Logs       SQS → Aggregation Worker
10 GB/day           ├── Group by correlation_id / trace_id
                    │   (all log lines for ONE request become ONE event)
                    ├── Group by error_signature
                    │   (100 identical ConnectionTimeout → 1 event, count=100)
                    ├── Attach context:
                    │   - K8s pod name, namespace, service
                    │   - Airflow dag_id, task_id, run_id
                    │   - Time window (first_seen, last_seen)
                    └── PII redaction (before any storage)
                    Output: ~1 GB/day (10x reduction)
                           │
                           ▼
                    STAGE 3: SUMMARIZE (5x reduction)
                    ──────────────────────────────────
Aggregated Events   LLM Summarizer (Bedrock Claude Haiku — cheap and fast)
1 GB/day            ├── Input: grouped log event (raw lines + metadata)
                    ├── Output: 2-3 sentence natural language summary
                    │   Example: "payment-service ConnectionTimeout to GOS DB
                    │   at host:1521. 47 occurrences between 02:15-02:25 UTC.
                    │   Correlated with VPC flow log REJECT on port 1521.
                    │   Root cause likely ACL change. First affected pod:
                    │   payment-api-7f8d9."
                    └── Score: severity (P0-P4), category (infra/app/data)
                    Output: ~200 MB/day (5x reduction; summaries only)
                           │
                           ▼
                    STAGE 4: EMBED + STORE (final)
                    ──────────────────────────────────
Log Summaries       Embedding + Qdrant Upsert
200 MB/day          ├── Embed summary text (Bedrock Titan v2, 1024-dim)
(~50K events)       ├── Upsert to Qdrant collection: "log_events"
                    │   payload: {team_id, service, severity, category,
                    │             timestamp, occurrence_count, raw_s3_key}
                    └── Raw grouped logs → S3 (hot/warm/cold tiering)
                    
                    Qdrant: ~50K new vectors/day (~1.5M/month)
                    S3 Raw: 1 GB/day for full-text drill-down
```

### 1.3 What Gets Stored Where

| Data | Where | Retention | Size/Month | Queryable Via |
|------|-------|:---------:|:----------:|---------------|
| **Log summaries (embedded)** | Qdrant | 90 days | ~45 GB | RAG (natural language queries) |
| **Aggregated event metadata** | PostgreSQL | 1 year | ~10 GB | SQL (structured queries, dashboards) |
| **Raw filtered logs** | S3 (hot 7d → warm 30d → cold 1yr) | 1 year | ~30 GB | S3 Select or Athena (drill-down only) |
| **Original unfiltered logs** | CloudWatch / S3 Glacier | Per compliance policy | N/A | CloudWatch Insights (emergency only) |

### 1.4 Smart Filtering Rules

> [!NOTE]
> The config below is **pseudocode** illustrating the filtering logic.
> Real Fluent Bit uses `.conf` files or a different YAML schema with `grep`, `lua`,
> and `modify` filters. Translate to your actual Fluent Bit/OTel Collector syntax.

```yaml
# PSEUDOCODE — illustrates filtering intent, not literal Fluent Bit syntax
# Translate to Fluent Bit grep/lua filters or OTel Collector processors
filters:
  # DROP: Health checks, readiness probes
  - match: "*"
    condition: "message MATCHES 'GET /health|GET /ready|heartbeat|ping'"
    action: DROP

  # DROP: Duplicate lines within 10s window
  - match: "*"
    dedup:
      key: "sha256(message + service_name)"
      window: 10s
      action: DROP_AFTER_FIRST

  # SAMPLE: INFO logs at 5%
  - match: "*"
    condition: "level == 'INFO'"
    action: SAMPLE
    rate: 0.05

  # SAMPLE: DEBUG logs at 1% (only in prod)
  - match: "*"
    condition: "level == 'DEBUG'"
    action: SAMPLE
    rate: 0.01

  # KEEP: All errors, warnings, security events
  - match: "*"
    condition: "level IN ('ERROR', 'FATAL', 'WARN', 'CRITICAL')"
    action: KEEP

  # KEEP: All Airflow task state changes
  - match: "airflow.*"
    condition: "event_type IN ('task_failed', 'task_success', 'dag_started', 'dag_failed')"
    action: KEEP

  # KEEP: All auth events
  - match: "*"
    condition: "message MATCHES 'auth|login|api_key|unauthorized|forbidden'"
    action: KEEP
```

### 1.5 Cost Comparison

> [!NOTE]
> All volume/cost figures below are **order-of-magnitude estimates** for a 50-team
> deployment. Your actual numbers depend on team workloads, log verbosity, and pod count.
> Use these for directional planning, then benchmark with real data.

| Approach | Qdrant Vectors/Month | Embedding Cost/Month | LLM Summarization/Month | Qdrant Storage/Month | Total/Month |
|----------|:-------------------:|:-------------------:|:----------------------:|:-------------------:|:-----------:|
| ❌ Embed every log line | ~1.5B | ~$150,000 | $0 (no summarization) | ~6 TB (~$1,200) | **~$151,200** |
| ✅ Smart pipeline (filter→aggregate→summarize→embed) | ~1.5M | ~$150 | ~$1,900 (Haiku) | ~45 GB (~$9) | **~$2,060** |
| **Savings** | 1000x fewer vectors | 99.9% reduction | N/A | 99% reduction | **~$149,000/mo saved (98.6%)** |

---

## Part 2: Resiliency Architecture

### 2.1 Resiliency Principles (Aligned with AWS Well-Architected Reliability Pillar)

| # | Principle | What It Means For CentRAG |
|---|-----------|--------------------------|
| 1 | **Expect failure** | Every component WILL fail. Design for it, don't prevent it. |
| 2 | **Reduce blast radius** | One team's bad query should never affect another team. |
| 3 | **Degrade gracefully** | When Qdrant is down, serve from cache. When cache is cold, return "please retry." Don't crash. |
| 4 | **Recover automatically** | Circuit breakers + auto-scaling + multi-AZ failover. No human involvement for common failures. |
| 5 | **Test failure regularly** | Chaos testing quarterly. If you haven't tested a failover, it doesn't work. |

### 2.2 Resiliency Patterns Implementation

#### Pattern 1: Circuit Breaker (per dependency)

```
Every external call (Qdrant, Bedrock, Cohere, Neptune, GOS DB) is wrapped
in a circuit breaker.

States:
  CLOSED  ──────────→  OPEN  ──────────→  HALF-OPEN
  (normal)   5 failures    (reject all)   30s timer    (allow 1 probe)
             in 60s                       expires        │
                                                         ├─ success → CLOSED
                                                         └─ failure → OPEN

Implementation per service:

┌──────────────────────────────────────────────────────────┐
│ Service         │ Threshold │ Timeout │ Fallback         │
├──────────────────────────────────────────────────────────┤
│ Qdrant          │ 5 in 60s  │ 30s     │ Return cached    │
│                 │           │         │ results if avail │
│ Bedrock (embed) │ 3 in 60s  │ 30s     │ Queue for retry  │
│ Bedrock (LLM)   │ 3 in 60s  │ 30s     │ Return "please   │
│                 │           │         │ retry" + chunks  │
│ Cohere Rerank   │ 5 in 60s  │ 10s     │ Skip reranking,  │
│                 │           │         │ return raw results│
│ Neptune         │ 5 in 60s  │ 15s     │ Skip KG, use     │
│                 │           │         │ vector-only       │
│ Redis           │ 3 in 30s  │ 5s      │ Skip cache,      │
│                 │           │         │ go direct to RAG  │
│ GOS DB (MCP)    │ 3 in 60s  │ 30s     │ Return error with │
│                 │           │         │ last known status │
│ Aurora PG       │ 3 in 30s  │ 10s     │ Multi-AZ failover│
│                 │           │         │ (auto, <30s)      │
└──────────────────────────────────────────────────────────┘
```

#### Pattern 2: Bulkhead Isolation (per team)

```
Problem: Team Alpha sends 10,000 queries/min (runaway agent).
         Without isolation, this consumes all async capacity.
         Team Beta's legitimate 10 queries/min get starved.

Solution: Per-team concurrency limits using asyncio.Semaphore.

┌───────────────────────────────────────────────────────────────────┐
│            API Server Async Concurrency (FastAPI / asyncio)        │
│                                                                   │
│  ┌───────────────┐  ┌───────────────┐  ┌───────────────────────┐ │
│  │ Team Alpha    │  │ Team Beta     │  │ Shared Pool           │ │
│  │ Semaphore: 10 │  │ Semaphore: 10 │  │ (all teams, overflow) │ │
│  │ Reject: 429   │  │ Reject: 429   │  │ Semaphore: 50         │ │
│  └───────────────┘  └───────────────┘  └───────────────────────┘ │
│                                                                   │
│  When Alpha's 10 slots are full, Alpha gets 429.                  │
│  Beta's slots are untouched. Beta keeps working.                  │
│                                                                   │
│  Implementation (Python):                                         │
│    team_semaphores: dict[str, asyncio.Semaphore]                  │
│    acquired = sem.acquire(timeout=0)  # non-blocking              │
│    if not acquired: raise HTTPException(429)                      │
└───────────────────────────────────────────────────────────────────┘

Also applies to:
  - Qdrant connection pools (per-team limits via connection pooler)
  - Bedrock API rate limits (per-team quotas via middleware)
  - SQS ingestion (per-team queue depth limits)
```

#### Pattern 3: Retry with Exponential Backoff + Jitter

```python
# Applied to ALL transient-failure-prone calls
async def resilient_call(func, *args, max_retries=3, **kwargs):
    for attempt in range(max_retries):
        try:
            return await func(*args, **kwargs)
        except TransientError:
            if attempt == max_retries - 1:
                raise
            # Exponential backoff: 1s, 2s, 4s
            base_delay = 2 ** attempt
            # Jitter: randomize to prevent thundering herd
            jitter = random.uniform(0, base_delay * 0.5)
            await asyncio.sleep(base_delay + jitter)
    
# Rules:
# - Only retry IDEMPOTENT operations (reads, not writes)
# - Never retry auth failures (401/403) — they won't fix themselves
# - Cap at 3 retries — after that, circuit breaker takes over
# - Always add jitter — prevents all pods retrying simultaneously
```

#### Pattern 4: Backpressure / Load Shedding

```
When the system is overloaded, REJECT early rather than queue forever.

Implementation:
  1. API server tracks in-flight requests per team
  2. If team's in-flight > max_concurrent (from tier config):
     → Return 429 Too Many Requests immediately
     → Include Retry-After header
  3. If global in-flight > system_capacity * 0.85:
     → Activate load shedding mode
     → Only process requests from enterprise-tier teams
     → Free/pro-tier get 503 with "system at capacity"
  4. SQS queue depth > 10,000:
     → Stop accepting new document uploads
     → Return 503 "ingestion queue full, retry later"
```

#### Pattern 5: Graceful Degradation Matrix

| Component Down | Impact | Degraded Behavior | User Sees |
|---------------|--------|-------------------|-----------|
| **Qdrant** | No vector search | Serve from L2/L3 cache if available. If not, return "search temporarily unavailable, please retry." | Cached answers or clear error + retry hint |
| **Bedrock LLM** | No generation | Return raw top-5 chunks with scores (no LLM answer). User gets source material directly. | Chunks + "generation temporarily unavailable" |
| **Bedrock Embed** | No new embeddings | Queue ingestion for later. Existing vectors still searchable. New queries use BM25-only fallback. | Slightly lower quality results, ingestion delayed |
| **Cohere Rerank** | No re-ranking | Skip reranker, return raw fusion results. Quality drops ~15%. | Slightly lower quality, no visible error |
| **Redis** | No cache, no working memory | All queries go to full RAG (L4). Higher latency (~3s vs ~50ms). No session memory. | Slower responses, no memory recall |
| **Neptune** | No knowledge graph | Skip KG retrieval. Use vector + BM25 only. Quality drops ~10%. | Slightly lower quality, no visible error |
| **Aurora PG** | No metadata, no auth (briefly) | Multi-AZ auto-failover in <30s. During failover: API key validation from Redis cache (TTL 5min). | Possible 1-2 failed requests during 30s failover |
| **SQS** | No ingestion | Documents accepted via API but queued locally. Retry when SQS recovers. | Upload accepted, processing delayed |

### 2.3 Disaster Recovery

> [!IMPORTANT]
> RTO/RPO targets below are scoped to **single-AZ failure** (the most common failure mode).
> Full-region failure requires a separate DR plan (Pilot Light or Warm Standby in a second region)
> with significantly higher RTO (30-60 min for CDK redeploy) and higher cost.

| Metric | Target | Scope | How |
|--------|--------|-------|-----|
| **RTO** | **< 2 minutes** | Single-AZ failure | Aurora auto-failover <30s. EKS pod rescheduled <60s. Redis replica promoted <10s. |
| **RTO** | **< 60 minutes** | Full-region failure | Pilot Light in us-west-2. CDK deploy + DNS failover + Qdrant restore from S3 snapshot. |
| **RPO** | **< 5 minutes** | Both | Aurora PITR (continuous). S3 versioning. Qdrant snapshots every 15 min to S3 (schedule during off-peak to avoid I/O contention on large collections). Redis AOF persistence. |
| **MTTR** | **< 30 minutes** | Both | Automated runbooks (SSM). PagerDuty alerting with escalation. Health checks every 10s. |
| **MTBF** | **> 30 days** | Both | Multi-AZ. Circuit breakers. Load shedding. Chaos testing. |

### 2.4 Multi-AZ Deployment (the "3-AZ Rule")

```
┌───────────────────────────────────────────────────────────────┐
│                     us-east-1                                  │
│                                                                │
│  ┌────── AZ-a ──────┐  ┌────── AZ-b ──────┐  ┌── AZ-c ─────┐│
│  │ EKS node pool    │  │ EKS node pool    │  │ EKS node     ││
│  │ ├── api-server   │  │ ├── api-server   │  │ pool         ││
│  │ ├── retrieval    │  │ ├── retrieval    │  │ ├── api      ││
│  │ ├── ingestion-w  │  │ ├── ingestion-w  │  │ ├── retr    ││
│  │ └── mcp-gateway  │  │ └── mcp-gateway  │  │ └── ing     ││
│  │                  │  │                  │  │              ││
│  │ Aurora Primary   │  │ Aurora Replica   │  │ Aurora       ││
│  │ Qdrant node-1    │  │ Qdrant node-2    │  │ Replica      ││
│  │ Redis shard-1    │  │ Redis shard-2    │  │ Qdrant       ││
│  │                  │  │                  │  │ node-3       ││
│  │                  │  │                  │  │ Redis        ││
│  │                  │  │                  │  │ shard-3      ││
│  └──────────────────┘  └──────────────────┘  └──────────────┘│
│                                                                │
│  Why 3 AZs (not 2):                                            │
│  - Quorum: 3 nodes need 2/3 for consensus. Losing 1 AZ = OK. │
│  - With 2 AZs: losing 1 AZ = 50% loss = no quorum = OUTAGE. │
└───────────────────────────────────────────────────────────────┘
```

### 2.5 Chaos Testing Plan

| Test | What It Does | Frequency | Expected Outcome |
|------|-------------|-----------|------------------|
| Kill 1 API server pod | Tests pod rescheduling | Weekly | New pod up in <30s, zero dropped requests (K8s readiness probe) |
| Kill Qdrant node | Tests vector DB failover | Monthly | Remaining 2 nodes serve queries. Recovery in <5 min. |
| Block Bedrock network | Tests LLM circuit breaker | Monthly | Circuit opens. Users get raw chunks. No crash. |
| Kill Redis primary | Tests cache failover | Monthly | Replica promoted. 1-2 cache misses during failover. |
| Aurora AZ failure | Tests DB failover | Quarterly | Auto-failover in <30s. 0-2 requests fail during window. |
| SQS unreachable | Tests ingestion resilience | Monthly | Docs accepted, queued locally, processed when SQS recovers. |
| Fill team quota | Tests bulkhead | Weekly | Target team gets 429. Other teams unaffected. |

---

## Part 3: Functional & Non-Functional Requirements Specification

### 3.1 Functional Requirements (What the System Does)

#### FR-1: Document Management

| ID | Requirement | Priority | Acceptance Criteria |
|----|------------|:--------:|---------------------|
| FR-1.1 | Teams SHALL upload documents (PDF, DOCX, CSV, MD, TXT) via API or Admin UI | P0 | Upload succeeds, S3 key returned, doc status = "processing" |
| FR-1.2 | System SHALL parse, chunk, embed, and index uploaded documents within 60 seconds for files < 10MB | P0 | RAGAS Context Precision > 0.80 on test set |
| FR-1.3 | System SHALL support semantic chunking with configurable token size (default 512) and overlap (default 50) | P1 | Chunks maintain semantic coherence; no mid-sentence splits |
| FR-1.4 | System SHALL deduplicate documents by content hash (SHA-256) within a namespace | P1 | Uploading same file twice results in 409 Conflict |
| FR-1.5 | Teams SHALL delete documents and all associated vectors/chunks | P0 | DELETE returns 200, vector count decreases, no orphaned data |

#### FR-2: Retrieval & Generation

| ID | Requirement | Priority | Acceptance Criteria |
|----|------------|:--------:|---------------------|
| FR-2.1 | Teams SHALL query documents via natural language through REST API | P0 | POST /v1/retrieve returns answer + sources |
| FR-2.2 | System SHOULD perform hybrid retrieval (dense + sparse + KG) | P1 (dense+sparse), P6 (KG) | RAGAS scores higher than dense-only baseline |
| FR-2.3 | System SHALL re-rank results using a cross-encoder before generation | P1 | Re-ranked results have higher NDCG@5 than raw results |
| FR-2.4 | System SHALL return source citations with document_id, chunk_index, and relevance_score | P0 | Every answer includes at least 1 source citation |
| FR-2.5 | System SHALL support streaming responses via SSE | P2 | Time-to-first-token < 500ms |

#### FR-3: Authentication & Authorization

| ID | Requirement | Priority | Acceptance Criteria |
|----|------------|:--------:|---------------------|
| FR-3.1 | System SHALL authenticate requests via API key (X-API-Key header) | P0 | Invalid key → 401, valid key → 200 |
| FR-3.2 | System SHALL resolve API key to team_id and scopes in < 5ms | P0 | Benchmarked with Redis cache |
| FR-3.3 | Admin SHALL generate, rotate, and revoke API keys via Admin UI | P0 | Key shown once on create, revoked key fails within 5 min |
| FR-3.4 | System SHALL support RBAC roles: viewer, editor, owner, super_admin | P1 | viewer cannot upload, editor cannot create keys |

#### FR-4: Memory

| ID | Requirement | Priority | Acceptance Criteria |
|----|------------|:--------:|---------------------|
| FR-4.1 | System SHALL extract and store facts from conversations | P2 | "User prefers charts" remembered across sessions |
| FR-4.2 | System SHALL recall relevant memories during retrieval | P2 | Memory-augmented answers are more personalized |
| FR-4.3 | System SHALL scope memory per team (no cross-team memory) | P0 | Search with Team A's key returns 0 of Team B's memories |

#### FR-5: Observability & Logs

| ID | Requirement | Priority | Acceptance Criteria |
|----|------------|:--------:|---------------------|
| FR-5.1 | System SHALL trace every retrieval request end-to-end with trace_id | P1 | Langfuse shows full span tree per query |
| FR-5.2 | System SHALL ingest team application logs from EKS, ECS, Airflow | P2 | Logs queryable via RAG within 5 minutes of emission |
| FR-5.3 | System SHALL filter/aggregate logs before embedding (not raw dump) | P0 | < 50K vectors/day from logs (not millions) |
| FR-5.4 | System SHALL generate natural language log summaries | P2 | Summaries accurately describe error root cause |

### 3.2 Non-Functional Requirements (How the System Performs)

#### NFR-1: Performance (ISO 25010: Performance Efficiency)

| ID | Requirement | Target | Measurement |
|----|------------|--------|-------------|
| NFR-1.1 | Query latency (cache hit) P95 | **< 50ms** | Locust load test |
| NFR-1.2 | Query latency (cache miss) P95 | **< 3,000ms** | Locust load test |
| NFR-1.3 | Query latency P99 | **< 5,000ms** | Locust load test |
| NFR-1.4 | Document ingestion throughput | **≥ 100 docs/min** | Celery flower metrics |
| NFR-1.5 | API key validation time | **< 5ms** | Redis hash lookup benchmark |
| NFR-1.6 | Cache hit ratio (steady state) | **≥ 40%** | Redis metrics |
| NFR-1.7 | Time-to-first-token (streaming) | **< 500ms** | Client-side measurement |
| NFR-1.8 | Concurrent teams supported | **≥ 100** | Load test with 100 team keys |

#### NFR-2: Scalability (ISO 25010: Performance Efficiency → Capacity)

| ID | Requirement | Target | Scaling Mechanism |
|----|------------|--------|-------------------|
| NFR-2.1 | Horizontal compute scaling | API: 3-20 pods, Ingestion: 1-50 pods | HPA on CPU/request count |
| NFR-2.2 | Vector storage scaling | 100M+ vectors | Qdrant sharding + dedicated tenant shards |
| NFR-2.3 | Ingestion queue scaling | Unlimited backlog, no data loss | SQS unlimited capacity + DLQ |
| NFR-2.4 | Cache scaling | Linear with shard addition | Redis Cluster (add shards) |
| NFR-2.5 | Zero-downtime deployment | Rolling updates, no dropped requests | K8s rolling update + PDB |

#### NFR-3: Reliability (ISO 25010: Reliability)

| ID | Requirement | Target | Mechanism |
|----|------------|--------|-----------|
| NFR-3.1 | Availability | **99.9%** (8.7 hrs downtime/yr) | Multi-AZ, auto-failover, health checks |
| NFR-3.2 | RTO | **< 15 minutes** | Aurora failover + K8s reschedule + CDK redeploy |
| NFR-3.3 | RPO | **< 5 minutes** | Aurora PITR + S3 versioning + Qdrant snapshots q15m |
| NFR-3.4 | Fault tolerance | Survive 1 AZ loss | 3-AZ deployment, quorum-based systems |
| NFR-3.5 | Circuit breaker on ALL external deps | Open at 5 failures/60s (tune per service) | `circuitbreaker` library with per-service config |
| NFR-3.6 | Retry with backoff on transient errors | Max 3 retries, exponential + jitter | Custom middleware |
| NFR-3.7 | Bulkhead per team | Max N concurrent per team | `asyncio.Semaphore` per team_id |
| NFR-3.8 | DLQ for failed ingestion | 0 data loss | SQS DLQ after 3 retries |
| NFR-3.9 | Graceful degradation | 7 defined fallback behaviors | See degradation matrix above |

#### NFR-4: Security (ISO 25010: Security)

| ID | Requirement | Target | Mechanism |
|----|------------|--------|-----------|
| NFR-4.1 | Namespace isolation | 0 cross-tenant data leaks | RLS + payload filter + key prefix + S3 prefix |
| NFR-4.2 | Encryption at rest | AES-256 (BYOK) | Envelope encryption with per-team CMK |
| NFR-4.3 | Encryption in transit | TLS 1.3 | ALB TLS termination + internal mTLS |
| NFR-4.4 | SQL injection prevention | 0 injection vulnerabilities | Parameterized queries + keyword blocking |
| NFR-4.5 | PII auto-redaction | SSN, CC, email, phone patterns | Regex-based scrub on ALL outbound data |
| NFR-4.6 | API key hashing | SHA-256, never stored in plaintext | Hash-on-create, hash-on-validate |
| NFR-4.7 | Rate limiting | Configurable per team tier | Token bucket (60/min free, 300/min pro) |
| NFR-4.8 | Audit logging | 100% of data access events logged | Immutable S3 (WORM) + CloudWatch |
| NFR-4.9 | Zero standing human access | No engineer has prod data access | Break-glass: 2-person approval, 4-hr window |

#### NFR-5: Maintainability (ISO 25010: Maintainability)

| ID | Requirement | Target | Mechanism |
|----|------------|--------|-----------|
| NFR-5.1 | Add new data source connector | **< 1 week** | BaseConnector interface + template |
| NFR-5.2 | Deploy new environment | **< 1 hour** | `cdk deploy` — all stacks parameterized |
| NFR-5.3 | Code coverage | **≥ 80%** | pytest + coverage gate in CI |
| NFR-5.4 | API backward compatibility | No breaking changes without v2/ migration | Semantic versioning + deprecation headers |
| NFR-5.5 | Configuration change | **< 5 minutes** (env var + pod restart) | Pydantic settings, no code deploy needed |

#### NFR-6: Observability (ISO 25010: Reliability → Recoverability)

| ID | Requirement | Target | Mechanism |
|----|------------|--------|-----------|
| NFR-6.1 | Distributed tracing | 100% of requests traced | Langfuse + OTel |
| NFR-6.2 | Alert on error rate spike | Alert within 60 seconds | CloudWatch Alarm → PagerDuty |
| NFR-6.3 | Per-span latency visibility | Every retrieval stage measured | Langfuse spans (auth, cache, retrieve, rerank, generate, pii) |
| NFR-6.4 | Cost tracking per team | Tokens consumed, queries made | PostgreSQL usage_metrics + Langfuse |
| NFR-6.5 | Dashboard for platform health | CPU, memory, queue depth, error rate, cache hit | CloudWatch Dashboard |

#### NFR-7: Compliance (ISO 25010: Security → Non-Repudiation)

| ID | Requirement | Target | Mechanism |
|----|------------|--------|-----------|
| NFR-7.1 | Data residency | Single region (configurable) | CDK param: `region = us-east-1` |
| NFR-7.2 | Audit log retention | 1 year (hot 90d, cold 275d) | S3 lifecycle: IA → Glacier |
| NFR-7.3 | Right to deletion | Complete data erasure in < 24h | Revoke CMK + delete S3 + purge Qdrant + truncate PG |
| NFR-7.4 | SOC 2 evidence | Continuous collection | Automated CloudTrail + access reviews quarterly |

---

## Part 4: Architect vs Developer Requirements Split

### What Architects Own (Design Decisions)

| Responsibility | Deliverable | Example |
|---------------|------------|---------|
| Define service boundaries | Service decomposition diagram | "Retrieval engine is separate from ingestion worker" |
| Choose technologies | ADR (Architecture Decision Record) | "Qdrant over OpenSearch because native tiered multi-tenancy" |
| Define NFRs | Requirements table (above) | "P95 < 3s, 99.9% availability" |
| Design data flows | Sequence diagrams (ingestion, retrieval, auth) | See HLD Part 8 |
| Design isolation model | 6-layer isolation architecture | See Privacy Trust Framework |
| Design resilience patterns | Circuit breaker/bulkhead/retry configs | See Part 2 of this document |
| Define DR strategy | RTO/RPO targets + failover procedures | "RTO < 15 min, RPO < 5 min" |
| Review security posture | Threat model + OWASP assessment | "OWASP LLM Top 10 mapping" |
| Capacity planning | Sizing spreadsheet | "50 teams = 3 EKS nodes, 3 Qdrant nodes" |
| Define SLAs/SLOs | SLA document | "99.9% monthly uptime guarantee" |

### What Developers Own (Implementation)

| Responsibility | Deliverable | Example |
|---------------|------------|---------|
| Implement BaseConnector interface | `gosdb_connector.py` | Working MCP server with tests |
| Implement guardrails | `guardrails.py` | SQL validation, PII redaction, rate limiting |
| Implement circuit breakers | `resilience.py` | Per-service circuit breaker with fallbacks |
| Write unit + integration tests | `tests/` directory | ≥ 80% code coverage |
| Build ingestion pipeline | `ingestion/worker.py` | Parse → chunk → embed → upsert |
| Build retrieval pipeline | `retrieval/engine.py` | Dense + sparse + rerank + generate |
| Implement cache tiers | `cache/manager.py` | L1 → L2 → L3 → L4 |
| Write CDK constructs | `infra/constructs/` | Reusable, parameterized stacks |
| Implement smart log filtering | `logs/filter.py` | Filter → aggregate → summarize → embed |
| Write chaos tests | `tests/chaos/` | Kill pods, block network, fill quotas |
| Performance tuning | Locust scripts + flame graphs | "Identified N+1 query in retrieval, fixed with batch" |
| Implement health checks | `/health` + `/ready` endpoints | K8s liveness + readiness probes |

---

## Resources

### Resiliency & Reliability

| Resource | Type | Link |
|---------|:----:|------|
| AWS Well-Architected Reliability Pillar | 📄 Docs | https://docs.aws.amazon.com/wellarchitected/latest/reliability-pillar/ |
| Release It! (2nd Ed) by Michael Nygard | 📖 Book | The definitive book on stability patterns (circuit breaker, bulkhead, etc.) |
| AWS Fault Injection Simulator | 📄 Docs | https://docs.aws.amazon.com/fis/ |
| Chaos Engineering (O'Reilly) | 📖 Book | https://www.oreilly.com/library/view/chaos-engineering/9781492043850/ |
| EKS Best Practices — Reliability | 📄 Docs | https://aws.github.io/aws-eks-best-practices/reliability/docs/ |
| circuitbreaker (Python) | 💻 Code | https://github.com/fabfuel/circuitbreaker |
| Litmus Chaos (K8s chaos) | 💻 Code | https://litmuschaos.io |

### Smart Log Storage

| Resource | Type | Link |
|---------|:----:|------|
| Fluent Bit Filters | 📄 Docs | https://docs.fluentbit.io/manual/pipeline/filters |
| OpenSearch ISM (Hot/Warm/Cold) | 📄 Docs | https://opensearch.org/docs/latest/im-plugin/ism/ |
| S3 Intelligent-Tiering | 📄 Docs | https://docs.aws.amazon.com/AmazonS3/latest/userguide/intelligent-tiering.html |
| Vector Quantization (Qdrant) | 📄 Docs | https://qdrant.tech/documentation/guides/quantization/ |
| Matryoshka Embeddings | 📄 Paper | https://arxiv.org/abs/2205.13147 |

### Requirements Engineering

| Resource | Type | Link |
|---------|:----:|------|
| ISO/IEC 25010 (Quality Model) | 📄 Standard | https://iso25000.com/index.php/en/iso-25000-standards/iso-25010 |
| IEEE 29148 (SRS Guide) | 📄 Standard | IEEE standard for requirements specifications |
| Writing Good Requirements (NASA) | 📄 Guide | https://standards.nasa.gov/standard/nasa/nasa-std-87394 |
