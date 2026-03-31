# CentRAG — App Logs Architecture, LangSmith Extension & Data Privacy Trust Framework

**Version:** 1.0  
**Last Updated:** 2026-03-31  
**Audience:** CIO, Technical Directors, Enterprise Architects, Product Owners  
**Classification:** Internal — Architecture Decision Record

---

## Part A: Application Logs Ingestion Architecture

> [!IMPORTANT]
> **CORRECTION:** The log ingestion worker below shows the collection layer (still correct),
> but the processing pipeline has been significantly revised.  
> **DO NOT embed every log line.** See [RESILIENCY_LOGS_REQUIREMENTS.md](./RESILIENCY_LOGS_REQUIREMENTS.md) Part 1
> for the corrected **4-stage smart pipeline** (Filter → Aggregate → Summarize → Embed)
> that reduces log volume by **99.9%** before it touches the vector database.

### A.1 Problem Statement

Teams run workloads across AWS services (EKS, ECS, Airflow, Lambda). Their application logs contain:
- Runtime errors and stack traces
- Business events and transaction flows
- AI/ML inference logs (model inputs/outputs, latencies, costs)
- Airflow DAG execution logs (task success/failure, duration)
- Kubernetes events and pod lifecycle logs

Today, these logs are scattered across CloudWatch log groups, S3 buckets, and local files. There is no way to **ask questions** about logs using natural language. CentRAG changes that.

### A.2 Vision: Log Intelligence Layer

```
Traditional:     Logs → CloudWatch → Dashboard → Human reads logs manually
CentRAG:         Logs → Ingestion → Index → RAG → "Why did DAG X fail at 3am?"
                                                    → Instant, cited answer
```

### A.3 Architecture: Log Ingestion Pipeline

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        LOG COLLECTION LAYER                                 │
│                                                                             │
│  ┌── EKS Pods ──┐    ┌── ECS Tasks ──┐    ┌── Airflow ──┐   ┌── Lambda ──┐│
│  │  Fluent Bit   │    │  FireLens     │    │  S3 remote  │   │  CW Logs   ││
│  │  (DaemonSet)  │    │  (sidecar)    │    │  log store  │   │  (built-in)││
│  └──────┬────────┘    └──────┬────────┘    └──────┬──────┘   └──────┬─────┘│
│         │                    │                    │                  │      │
│         └──────────┬─────────┴──────────┬─────────┘                 │      │
│                    │                    │                            │      │
│                    ▼                    ▼                            │      │
│         ┌────────────────┐   ┌──────────────────┐                   │      │
│         │ Kinesis Data   │   │ CloudWatch Logs   │←──────────────────┘      │
│         │ Firehose       │   │ Subscription      │                         │
│         │ (buffered)     │   │ Filter            │                         │
│         └───────┬────────┘   └────────┬──────────┘                         │
│                 │                     │                                     │
└─────────────────┼─────────────────────┼─────────────────────────────────────┘
                  │                     │
                  ▼                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                     LOG PROCESSING LAYER                                    │
│                                                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                    SQS FIFO Queue                                    │   │
│  │              (team_id, source, log_type)                             │   │
│  └───────────────────────────┬──────────────────────────────────────────┘   │
│                              │                                              │
│  ┌───────────────────────────▼──────────────────────────────────────────┐   │
│  │         Log Ingestion Worker — DEPRECATED: SEE RESILIENCY DOC        │   │
│  │   ⚠️  This shows the ORIGINAL design. The corrected 4-stage         │   │
│  │      pipeline (Filter→Aggregate→Summarize→Embed) is in              │   │
│  │      RESILIENCY_LOGS_REQUIREMENTS.md Part 1.                        │   │
│  │                                                                      │   │
│  │  1. Parse JSON log lines                                             │   │
│  │  2. Classify log type (error, info, warning, trace, metric)          │   │
│  │  3. Extract structured fields:                                       │   │
│  │     - timestamp, level, service, pod, container                     │   │
│  │     - error_class, stack_trace (if error)                            │   │
│  │     - dag_id, task_id, run_id (if Airflow)                          │   │
│  │     - trace_id, span_id (if OTel)                                   │   │
│  │  4. PII redaction (scrub before storage)                             │   │
│  │  5. Semantic chunking (group related log lines by correlation_id)    │   │
│  │  6. Generate embeddings (Bedrock Titan v2)                           │   │
│  │  7. Upsert to Qdrant: collection=app_logs, payload={team_id, ...}   │   │
│  │  8. Store raw lines in S3: s3://logs/{team_id}/{date}/{source}/     │   │
│  │  9. Insert metadata in PostgreSQL (log_sources table)                │   │
│  │                                                                      │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### A.4 Source-Specific Collection

| Source | Collection Agent | Transport | Log Format | Team Identification |
|--------|-----------------|-----------|-----------|-------------------|
| **EKS** | Fluent Bit (DaemonSet) | Kinesis Firehose → SQS | JSON (structured) | Kubernetes namespace → team_id mapping |
| **ECS** | FireLens (Fluent Bit sidecar) | Kinesis Firehose → SQS | JSON (structured) | ECS task tag `team_id` |
| **Airflow (MWAA)** | S3 remote logging | S3 event → SQS | Text (semi-structured) | DAG name prefix → team_id mapping |
| **Lambda** | CloudWatch Logs Subscription | CW → Kinesis Firehose → SQS | JSON/Text | Lambda function tag `team_id` |
| **Custom Apps** | Fluent Bit / OTEL Collector | Kinesis Firehose → SQS | JSON (structured) | API key in log shipper config |
| **CloudWatch Metrics** | CW Metric Streams | Kinesis Firehose → SQS | JSON | Account tag → team_id mapping |

### A.5 Log-Specific Qdrant Schema

```python
# Qdrant collection: "app_logs"
# Each point = one log event or correlated group of log lines
{
    "id": "uuid",
    "vector": [0.123, ...],  # 1024-dim Titan v2 embedding
    "payload": {
        "team_id": "alpha",
        "namespace_id": "production",
        "source": "eks",                    # eks | ecs | airflow | lambda
        "service_name": "payment-service",
        "log_level": "ERROR",               # ERROR | WARN | INFO | DEBUG
        "timestamp": "2026-03-31T02:00:00Z",
        "correlation_id": "corr_abc123",    # Groups related log lines
        "error_class": "ConnectionTimeout",  # Extracted by classifier
        "container": "payment-api-7f8d9",
        "dag_id": null,                     # Populated for Airflow logs
        "task_id": null,
        "trace_id": "tr_xyz789",            # OTel trace link
        "raw_s3_key": "logs/alpha/2026-03-31/eks/payment-service/chunk_42.json",
        "content_preview": "ConnectionTimeout: Failed to connect to GOS DB at host:1521 after 30s..."
    }
}
```

### A.6 Querying Logs via RAG

```
User Query:   "Why did the payment-service crash last night?"
Namespace:    "production"
Log Sources:  [eks, cloudwatch]

CentRAG does:
  1. Embed query
  2. Search app_logs collection (filter: team_id=alpha, source∈[eks,cw], log_level=ERROR)
  3. Retrieve top-20 error log groups from last 24h
  4. Re-rank by relevance to "payment-service crash"
  5. Feed top-5 log groups + context to Claude 3.5
  6. Generate answer with citations to specific log lines

Response:
  "The payment-service crashed at 02:17 AM due to a ConnectionTimeout exception
   when connecting to GOS DB. The root cause was a network ACL change at 02:15 AM
   that blocked port 1521 from the EKS private subnet.

   Sources:
   - payment-service-7f8d9 ERROR log at 02:17:03 [trace: tr_xyz789]
   - kubernetes event: pod CrashLoopBackOff at 02:17:15
   - CloudWatch VPC Flow Log: REJECT on port 1521 at 02:15:42"
```

### A.7 MCP Connector: App Logs

```python
# Extends BaseConnector interface — fully reusable pattern
class AppLogsMCPConnector(BaseConnector):
    """
    MCP tools for querying application logs via CentRAG.
    Wraps CloudWatch Logs Insights + indexed Qdrant logs.
    """

    # Tools exposed to AI agents:
    # ├── search_logs(query, service, level, time_range)
    # ├── get_recent_errors(service, last_n_hours)
    # ├── get_log_context(correlation_id)  ← fetches all lines for a request
    # ├── get_airflow_dag_status(dag_id, run_id)
    # ├── list_services()
    # └── get_error_trends(service, days)  ← aggregated error counts
```

---

## Part B: LangSmith-Type Extension (AI Observability Knowledge Base)

### B.1 Vision

> CentRAG starts as a RAG platform. It **evolves** into an AI observability knowledge base — where teams can trace, evaluate, debug, and improve their agentic applications. Think LangSmith, but self-hosted, namespace-isolated, and integrated with CentRAG's RAG capabilities.

### B.2 Architecture Evolution

```
Phase 1 (Now):     CentRAG = RAG Platform (upload docs, query them)
Phase 2 (Months 4-5): + App Logs Intelligence (query logs with natural language)
Phase 3 (Months 6-8): + AI Observability KB (trace agents, evaluate quality, detect drift)

Phase 3 Architecture:
┌──────────────────────────────────────────────────────────────────┐
│                    AI OBSERVABILITY LAYER                         │
│                                                                  │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────────┐ │
│  │ Trace    │  │ Eval     │  │ Prompt   │  │ Cost & Usage     │ │
│  │ Storage  │  │ Pipeline │  │ Registry │  │ Analytics        │ │
│  └─────┬────┘  └────┬─────┘  └────┬─────┘  └────┬─────────────┘ │
│        │            │             │              │               │
│        └────────────┴──────┬──────┴──────────────┘               │
│                            │                                     │
│                    ┌───────▼────────┐                             │
│                    │   CentRAG      │                             │
│                    │   RAG Engine   │                             │
│                    │   (query your  │                             │
│                    │   own traces!) │                             │
│                    └────────────────┘                             │
│                                                                  │
│  "Why did Agent X hallucinate on Tuesday?"                       │
│  "Show me all traces where retrieval precision < 0.7"            │
│  "What prompts work best for our financial Q&A agent?"           │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

### B.3 What We Capture Per AI Invocation

| Field | Example | Why |
|-------|---------|-----|
| `trace_id` | `tr_8a9b0c1d` | Unique ID for the entire request chain |
| `spans[]` | `auth → cache → retrieve → rerank → generate` | Breakdown of each step |
| `input_query` | "What was Q3 revenue?" | The user's question |
| `retrieved_chunks[]` | [{doc: "q3.pdf", chunk: 7, score: 0.94}] | What the retriever found |
| `prompt_template` | "Answer based on {context}..." | Which prompt was used |
| `llm_model` | "claude-3-5-sonnet" | Which model generated the answer |
| `output_answer` | "Revenue was $42.3M..." | The generated response |
| `latency_per_span` | {retrieve: 15ms, rerank: 100ms, generate: 1500ms} | Per-step timing |
| `token_usage` | {input: 3200, output: 180, cost: $0.0054} | Cost per invocation |
| `eval_scores` | {faithfulness: 0.92, relevancy: 0.88} | Auto-evaluated quality |
| `user_feedback` | "thumbs_up" | Explicit user rating |

### B.4 Data Model: AI Traces (PostgreSQL)

```sql
CREATE TABLE ai_traces (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    team_id UUID NOT NULL REFERENCES teams(id),
    trace_id VARCHAR(64) UNIQUE NOT NULL,
    session_id VARCHAR(64),             -- Groups multi-turn conversations
    user_context VARCHAR(256),
    input_query TEXT NOT NULL,
    output_answer TEXT,
    total_latency_ms INTEGER,
    total_tokens INTEGER,
    total_cost_usd NUMERIC(10, 6),
    model_name VARCHAR(64),
    prompt_template_id UUID,
    cache_hit BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE ai_spans (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trace_id VARCHAR(64) NOT NULL REFERENCES ai_traces(trace_id),
    team_id UUID NOT NULL,
    span_name VARCHAR(64) NOT NULL,     -- 'retrieve', 'rerank', 'generate', etc.
    span_type VARCHAR(32),              -- 'retrieval', 'llm', 'tool', 'chain'
    input_data JSONB,
    output_data JSONB,
    latency_ms INTEGER,
    token_count INTEGER,
    cost_usd NUMERIC(10, 6),
    error TEXT,                         -- NULL if success
    metadata JSONB,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ
);

CREATE TABLE ai_evaluations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trace_id VARCHAR(64) NOT NULL REFERENCES ai_traces(trace_id),
    team_id UUID NOT NULL,
    metric_name VARCHAR(64) NOT NULL,   -- 'faithfulness', 'answer_relevancy', etc.
    score FLOAT NOT NULL,               -- 0.0 to 1.0
    evaluator VARCHAR(64),              -- 'ragas', 'llm_judge', 'human', 'thumbs'
    details JSONB,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE prompt_templates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    team_id UUID NOT NULL REFERENCES teams(id),
    name VARCHAR(128) NOT NULL,
    version INTEGER NOT NULL,
    template TEXT NOT NULL,
    metadata JSONB,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(team_id, name, version)
);

-- RLS on all tables
ALTER TABLE ai_traces ENABLE ROW LEVEL SECURITY;
ALTER TABLE ai_spans ENABLE ROW LEVEL SECURITY;
ALTER TABLE ai_evaluations ENABLE ROW LEVEL SECURITY;
ALTER TABLE prompt_templates ENABLE ROW LEVEL SECURITY;

CREATE POLICY team_iso ON ai_traces USING (team_id = current_setting('app.team_id')::uuid);
CREATE POLICY team_iso ON ai_spans USING (team_id = current_setting('app.team_id')::uuid);
CREATE POLICY team_iso ON ai_evaluations USING (team_id = current_setting('app.team_id')::uuid);
CREATE POLICY team_iso ON prompt_templates USING (team_id = current_setting('app.team_id')::uuid);
```

### B.5 How It Plugs Into CentRAG

```
Traces are just another data source:

AI Trace → structured JSON → embed trace summary → Qdrant (collection: ai_traces)

Now teams can RAG over their own AI traces:
  - "Show me the worst-performing queries this week"
  - "Why did the agent hallucinate about revenue figures?"
  - "Compare prompt v3 vs v4 for financial Q&A accuracy"
  - "What's our average cost per query by model?"
```

### B.6 Competitor Mapping: CentRAG vs LangSmith

| Capability | LangSmith | CentRAG (Phase 3) | Advantage |
|-----------|-----------|-------------------|-----------|
| Trace collection | ✅ | ✅ | Parity |
| Prompt versioning | ✅ | ✅ | Parity |
| Cost tracking | ✅ | ✅ | Parity |
| Auto-evaluation | ✅ (custom evaluators) | ✅ (RAGAS + custom) | Parity |
| RAG over traces | ❌ | ✅ | **CentRAG wins** — ask questions about your traces |
| Self-hosted | ✅ (Enterprise tier, $$$) | ✅ (included) | **CentRAG wins** — no extra license cost |
| Namespace isolation (per-team) | ❌ (org-level only) | ✅ (per-team RLS) | **CentRAG wins** — granular team isolation |
| App log correlation | ❌ | ✅ | **CentRAG wins** — link AI traces to infra logs |
| Memory layer | ❌ | ✅ | **CentRAG wins** |

---

## Part C: Data Privacy & Trust Framework

> **The #1 question leadership will ask:**  
> *"How do we know the platform team can't see our data?"*
>
> This section answers that question for CIOs, architects, directors, and product owners with **cryptographic guarantees, not just policy promises**.

### C.1 The Trust Problem (Why Leadership Worries)

```
Team Alpha uploads sensitive financial data to CentRAG.
Team Beta uploads HR compensation data.
The CentRAG platform team manages both.

Leadership's fear:
  - "Can the CentRAG engineers read our financial reports?"
  - "Can Team Alpha's data accidentally leak to Team Beta?"
  - "What if a CentRAG admin goes rogue?"
  - "Will regulators accept this?"
  - "How is this different from sending data to an external vendor?"
```

### C.2 Our Answer: 5-Layer Privacy Architecture

We don't ask teams to **trust us**. We make it **technically impossible** for us to access their data.

```
Layer 1: CRYPTOGRAPHIC ISOLATION (Envelope Encryption + BYOK)
   │  Team's data is encrypted with THEIR key. We literally cannot decrypt it.
   │
Layer 2: ROW-LEVEL SECURITY (PostgreSQL RLS)
   │  Even if someone accesses the database, SQL queries auto-filter by team_id.
   │
Layer 3: VECTOR DB PAYLOAD FILTERING (Qdrant)
   │  Every vector search requires team_id filter. No filter = no results.
   │
Layer 4: ZERO STANDING ACCESS (No Human Access to Production Data)
   │  Engineers cannot SSH into prod. No database credentials. Break-glass only.
   │
Layer 5: IMMUTABLE AUDIT TRAIL (Every Access Logged, Tamper-Proof)
      Teams can independently verify every access to their data.
```

### C.3 Layer 1: Cryptographic Isolation (The Strongest Guarantee)

**How it works — Envelope Encryption with Customer Managed Keys (BYOK):**

```
                        ┌─────────────────────────┐
                        │   Team Alpha's AWS KMS   │
                        │                         │
                        │   CMK (Customer Master  │
                        │   Key) — OWNED by Alpha │
                        │                         │
                        │   Alpha controls:       │
                        │   ├── Who can use it    │
                        │   ├── When to rotate it │
                        │   └── When to revoke it │
                        └───────────┬─────────────┘
                                    │
                            ┌───────▼────────┐
                            │  CentRAG calls  │
                            │  KMS:Decrypt    │
                            │  (with Alpha's  │
                            │   CMK)          │
                            └───────┬─────────┘
                                    │
                            ┌───────▼────────┐
                            │  Plaintext DEK   │
                            │  (Data Encryption│
                            │   Key) — exists  │
                            │   IN MEMORY ONLY │
                            │   for < 1 second │
                            └───────┬──────────┘
                                    │
                            ┌───────▼──────────┐
                            │  Encrypt/Decrypt  │
                            │  Alpha's chunks,  │
                            │  documents, logs   │
                            │  in memory         │
                            └───────┬──────────┘
                                    │
                            ┌───────▼──────────┐
                            │  Wipe DEK from     │
                            │  memory            │
                            └──────────────────┘

What CentRAG stores:
  - Encrypted data blob (AES-256) — documents, chunks, raw logs
  - Encrypted DEK (encrypted by Alpha's CMK)
  - NEVER the plaintext DEK or plaintext data on disk

What the CentRAG team can see:
  ❌ Plaintext documents
  ❌ Plaintext chunks
  ❌ Plaintext log content
  ✅ Metadata only: file sizes, timestamps, team names, API usage counts

⚠️  EMBEDDING CAVEAT:
  Vector embeddings are stored as plaintext vectors in Qdrant's memory
  because similarity search (cosine/dot-product) requires unencrypted
  floating-point values. However:
  - Qdrant's disk storage is encrypted at rest (EBS encryption with team CMK)
  - Embeddings cannot be reversed to reconstruct original text
    (embedding is a one-way lossy function)
  - Qdrant is in a private subnet with no internet access
  - All access requires team_id payload filter (no anonymous search)
  - This is the SAME model used by Pinecone, Weaviate, and all major
    vector DB providers — there is no production system that does
    similarity search on application-layer-encrypted vectors
```

**Key properties that leadership needs to hear:**

| Property | Guarantee |
|---------|-----------|
| **Ownership** | Team Alpha owns the CMK. CentRAG does not. We cannot create a copy. |
| **Revocability** | Alpha can revoke our access in <1 second by disabling the CMK in AWS KMS. Instantly, all their data becomes unreadable to us. |
| **Auditability** | Every time CentRAG uses Alpha's CMK, it creates a CloudTrail log entry in Alpha's AWS account. Alpha can independently audit every access. |
| **Non-extractability** | CMKs are backed by FIPS 140-2 Level 3 HSMs. Keys cannot be exported, even by AWS staff. |
| **Rotation** | Alpha can rotate their CMK at any time. CentRAG automatically uses the new key version. |

### C.4 Layer 2: Database Isolation (PostgreSQL RLS)

```sql
-- Even CentRAG engineers with database access see NOTHING
-- because RLS filters every query by team_id

-- CentRAG application sets team context from API key:
SET LOCAL app.team_id = '<team_alpha_uuid>';

-- All queries are auto-filtered:
SELECT * FROM documents;
-- → Returns ONLY Alpha's documents. Beta's docs are invisible.

-- Even a rogue engineer running raw SQL:
SELECT * FROM documents WHERE team_id != current_setting('app.team_id');
-- → Returns 0 rows. RLS policy BLOCKS it.

-- The RLS policy:
CREATE POLICY strict_isolation ON documents
    USING (team_id = current_setting('app.team_id')::uuid);
-- FORCE ROW LEVEL SECURITY applies to table owners too
ALTER TABLE documents FORCE ROW LEVEL SECURITY;
```

### C.5 Layer 3: Zero Standing Access (Production Environment)

```
                    Who Can Access What in Production
    ┌──────────────────────────────────────────────────────────────────┐
    │                                                                  │
    │  CentRAG Developer (normal day)                                  │
    │  ├── Can access: Dev/Staging environments                       │
    │  ├── CANNOT access: Production database                         │
    │  ├── CANNOT access: Production S3 buckets                       │
    │  ├── CANNOT access: Production Redis                            │
    │  ├── CANNOT SSH: Into any production pod/instance                │
    │  └── CANNOT access: AWS KMS keys (no IAM permission)            │
    │                                                                  │
    │  CentRAG SRE (break-glass emergency)                            │
    │  ├── Must submit: Justification in PagerDuty                    │
    │  ├── Must receive: 2-person approval (manager + security)       │
    │  ├── Gets: Time-boxed access (max 4 hours)                      │
    │  ├── All actions: Logged in CloudTrail + audit log              │
    │  ├── After access: Credentials auto-expire                      │
    │  └── Review: Mandatory post-access review within 24 hours       │
    │                                                                  │
    │  Automated CentRAG Application (runtime)                        │
    │  ├── Has: IAM role with least-privilege permissions              │
    │  ├── Can: Read/write to team's data WITH team_id context        │
    │  ├── CANNOT: Access data without a valid API key (team context) │
    │  ├── CANNOT: Bypass RLS policies                                │
    │  └── All actions: Logged in immutable audit log                  │
    │                                                                  │
    └──────────────────────────────────────────────────────────────────┘
```

### C.6 Layer 4: Immutable Audit Trail

Every data access generates an audit record that **cannot be altered or deleted**:

```json
{
  "timestamp": "2026-03-31T02:45:00Z",
  "event_type": "data_access",
  "team_id": "alpha",
  "caller": "api-server-pod-7f8d9",     // Not a human
  "api_key_prefix": "nxr_alpha_3f2a",
  "action": "vector_search",
  "collection": "documents",
  "filter": {"team_id": "alpha"},
  "results_count": 5,
  "latency_ms": 15,
  "pii_redacted": true,
  "source_ip": "10.0.1.45",
  "trace_id": "tr_9a8b7c6d"
}
```

**Storage:** Audit logs are written to:
1. **S3** (append-only, versioned, Object Lock WORM) — cannot be deleted
2. **CloudWatch Logs** — for real-time alerting
3. **Team-accessible dashboard** — each team sees their own access logs

### C.7 What We Tell Leadership (By Role)

#### For the CIO

> *"CentRAG uses envelope encryption with customer-managed keys (BYOK). Each team's data is encrypted with a key that only they own, stored in FIPS 140-2 Level 3 hardware security modules. Our platform team physically cannot decrypt team data because we never possess the keys. Teams can revoke our access in one click. Every access is independently auditable via CloudTrail in the team's own AWS account."*

**One-liner:** "We've made it **cryptographically impossible** — not just policy-prohibited — for anyone on our team to read team data."

#### For Technical Directors / Architects

> *"Five isolation layers: (1) Envelope encryption with per-team CMKs in AWS KMS, where plaintext DEKs exist only in memory for <1s, (2) PostgreSQL Row-Level Security with `FORCE ROW LEVEL SECURITY` applied to table owner, (3) Qdrant mandatory payload filtering on `team_id` enforced at the middleware layer, (4) Zero standing human access to production with break-glass requiring 2-person approval and 4-hour time-box, (5) Immutable audit logs in S3 Object Lock WORM mode with 1-year retention."*

**One-liner:** "Even if all our engineers colluded, the cryptographic and database enforcement layers prevent access without the team's own KMS key."

#### For Product Owners & Managers

> *"Think of it like a safety deposit box at a bank. The bank provides the vault (CentRAG). You hold the only key (your AWS KMS key). The bank staff cannot open your box. If you ever want to leave, you revoke the key and your data becomes unreadable to everyone. You also get a log of every time anyone — including the system — touched your box."*

**One-liner:** "Your data, your key, your control. We're the vault, not the owner."

#### For Compliance / Risk

| Compliance Requirement | How CentRAG Addresses It |
|----------------------|------------------------|
| **SOX — Access Controls** | RBAC + RLS + Zero standing access + audit trail |
| **SOX — Segregation of Duties** | Platform team ≠ data access. Break-glass requires 2 approvals. |
| **GDPR — Right to Erasure** | Revoke CMK → all data becomes cryptographically irretrievable |
| **GDPR — Data Minimization** | PII auto-redacted before storage. Only embeddings stored, not full PII. |
| **SOC 2 Type II — Confidentiality** | BYOK + RLS + Zero standing access operating for 6+ months |
| **SOC 2 Type II — Availability** | Multi-AZ Aurora, Redis cluster, EKS across 2 AZs |
| **Data Residency** | Configurable to single region (us-east-1). No cross-region replication. |
| **Regulatory Audit** | Immutable S3 audit logs (WORM), 1-year retention, exportable |

### C.8 Technical Comparison: CentRAG Privacy vs. Competitors

| Feature | CentRAG | LangSmith | Glean | Danswer/Onyx |
|---------|:-------:|:---------:|:-----:|:------------:|
| Self-hosted (data stays in your VPC) | ✅ | ❌ (SaaS) | ❌ (SaaS) | ✅ |
| BYOK (Customer managed encryption keys) | ✅ | ❌ | ❌ | ❌ |
| Per-team cryptographic isolation | ✅ | ❌ | ❌ | ❌ |
| Row-Level Security (DB enforcement) | ✅ | N/A | N/A | Basic |
| Zero standing human access to prod | ✅ | Unknown | Unknown | Self-managed |
| Immutable audit trail | ✅ | ❌ | Partial | Basic |
| Team can independently audit access | ✅ (CloudTrail) | ❌ | ❌ | Only if self-hosted |
| Team can revoke access instantly | ✅ (disable CMK) | ❌ | ❌ | Only if self-hosted |

### C.9 FAQ That Leadership Will Ask

| Question | Answer |
|---------|--------|
| *"Can a CentRAG engineer read our documents?"* | **No.** Documents are encrypted with your CMK. Our team has no IAM permission to call KMS:Decrypt with your key. Even with database access, they see encrypted blobs. With RLS, they can't even query your rows. |
| *"What if someone leaks our API key?"* | API keys can be revoked instantly via the Admin UI. Old key stops working within 5 minutes (cache TTL). Teams can also set `expires_at` for auto-expiry and IP allowlisting. |
| *"What happens if CentRAG shuts down?"* | Your data is in S3 (encrypted with your key) and Qdrant (encrypted). You retain the CMK. You can decrypt and export all raw data at any time. We provide a data export API. |
| *"Can one team's query accidentally return another team's data?"* | **Mathematically no.** Every Qdrant search has `team_id` injected by middleware (not by the user). RLS in PostgreSQL auto-filters. Cache keys are prefixed with `team_id`. There is no code path that queries without a `team_id` filter. |
| *"What about the embeddings? They encode meaning of our data."* | Embeddings are also encrypted at rest with team CMKs. In-transit, they're TLS 1.3 only. Embeddings alone cannot reconstruct original text (one-way function). |
| *"How do we audit what CentRAG does with our data?"* | Every operation generates a structured audit log. You receive a monthly access report. Daily CloudTrail events in your AWS account show every KMS key usage. We also support real-time webhook alerts for any access event. |
| *"Is this just a promise or is it enforced?"* | **Enforced at 5 layers:** hardware (HSM), cryptographic (BYOK envelope), database (RLS FORCE), application (middleware), and operational (zero standing access). A promise can be broken. A cryptographic guarantee cannot. |

---

## Part D: Resources for All Three Topics

### App Logs & Centralized Logging

| Resource | Type | Link |
|---------|:----:|------|
| AWS Centralized Logging Solution | 📄 Reference | https://aws.amazon.com/solutions/implementations/centralized-logging-with-opensearch/ |
| Fluent Bit on EKS Guide | 📄 Docs | https://docs.fluentbit.io/manual/installation/kubernetes |
| FireLens for ECS | 📄 Docs | https://docs.aws.amazon.com/AmazonECS/latest/developerguide/using_firelens.html |
| OpenSearch Ingestion Pipeline | 📄 Docs | https://docs.aws.amazon.com/opensearch-service/latest/developerguide/ingestion.html |
| Airflow Logging to S3 | 📄 Docs | https://airflow.apache.org/docs/apache-airflow/stable/administration-and-deployment/logging-monitoring/logging-tasks.html |
| Kinesis Data Firehose | 📄 Docs | https://docs.aws.amazon.com/firehose/ |

### LangSmith Alternatives & AI Observability

| Resource | Type | Link |
|---------|:----:|------|
| Langfuse (OSS LangSmith Alternative) | 💻 Code | https://github.com/langfuse/langfuse |
| Langfuse Self-Hosting Guide | 📄 Docs | https://langfuse.com/docs/deployment/self-host |
| Arize Phoenix | 💻 Code | https://github.com/Arize-ai/phoenix |
| OpenLLMetry (OTel for LLMs) | 💻 Code | https://github.com/traceloop/openllmetry |
| Braintrust (Eval Platform) | 📄 Docs | https://www.braintrust.dev/docs |
| RAGAS Evaluation | 💻 Code | https://github.com/explodinggradients/ragas |

### Data Privacy & Cryptographic Isolation

| Resource | Type | Link |
|---------|:----:|------|
| AWS KMS Developer Guide | 📄 Docs | https://docs.aws.amazon.com/kms/latest/developerguide/ |
| AWS Envelope Encryption | 📄 Docs | https://docs.aws.amazon.com/kms/latest/developerguide/concepts.html#enveloping |
| AWS Nitro Enclaves | 📄 Docs | https://docs.aws.amazon.com/enclaves/latest/user/nitro-enclave.html |
| AWS SaaS Tenant Isolation | 📄 Whitepaper | https://docs.aws.amazon.com/whitepapers/latest/saas-tenant-isolation-strategies/ |
| PostgreSQL RLS Guide | 📄 Docs | https://www.postgresql.org/docs/current/ddl-rowsecurity.html |
| SOC 2 Type II for Engineers | 📝 Blog | https://www.vanta.com/collection/soc-2 |
| Confidential Computing Consortium | 📄 Docs | https://confidentialcomputing.io |
| OWASP Top 10 for LLMs | 📄 Guide | https://owasp.org/www-project-top-10-for-large-language-model-applications/ |
| S3 Object Lock (WORM) | 📄 Docs | https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lock.html |
