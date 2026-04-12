# Centralized RAG Platform — HLD, LLD & Implementation Plan

## 1. Executive Summary

Build an enterprise **Centralized RAG-as-a-Service Platform** (codename: **"NexusRAG"**) that eliminates the need for individual teams to install, maintain, and operate their own RAG applications, memory layers, and observability stacks. Teams onboard via API keys, upload their data sources, and consume retrieval + generation capabilities through a unified API — completely namespace-isolated.

> [!IMPORTANT]
> This is a **distributed system** designed for **1000+ concurrent teams** with strict namespace isolation, multi-tenant vector storage, tiered caching, and governance controls comparable to Google's NotebookLM.

---

## 2. High-Level Design (HLD)

### 2.1 System Context Diagram

```mermaid
graph TB
    subgraph "Consumer Teams"
        T1["Team Alpha<br/>(API Key: nxr_alpha_****)"]
        T2["Team Beta<br/>(API Key: nxr_beta_****)"]
        T3["Team Gamma<br/>(API Key: nxr_gamma_****)"]
    end

    subgraph "NexusRAG Platform"
        direction TB
        
        subgraph "Edge Layer"
            GW["API Gateway<br/>(AWS ALB + WAF)"]
            AUTH["Auth Service<br/>(API Key + OAuth)"]
            RL["Rate Limiter<br/>(Token Bucket)"]
        end

        subgraph "Control Plane"
            UI["Admin UI<br/>(Next.js)"]
            ADMIN["Admin API<br/>(Team/Key Mgmt)"]
            GOV["Governance Engine<br/>(Policy-as-Code)"]
        end

        subgraph "Data Plane"
            direction TB
            
            subgraph "Ingestion Layer"
                ING["Ingestion Workers<br/>(Celery/SQS)"]
                CONN["Source Connectors<br/>(MCP Servers)"]
                PARSE["Parsers<br/>(Unstructured)"]
                CHUNK["Semantic Chunker"]
                EMB["Embedding Service<br/>(Bedrock Titan / OpenAI)"]
            end

            subgraph "Storage Layer"
                VDB["Vector DB Cluster<br/>(Qdrant / OpenSearch)"]
                PG["PostgreSQL<br/>(Metadata + Teams)"]
                S3["S3<br/>(Raw Documents)"]
                REDIS["Redis Cluster<br/>(Cache + Memory)"]
                GRAPH["Neo4j / Neptune<br/>(Knowledge Graph)"]
            end

            subgraph "Retrieval Layer"
                RET["Retrieval Router<br/>(Hybrid RAG)"]
                RERANK["Re-ranker<br/>(Cross-Encoder)"]
                GEN["Generation Service<br/>(Bedrock / vLLM)"]
            end

            subgraph "Memory Layer"
                MEM["Memory Engine<br/>(Mem0-style)"]
                PROFILE["User Profiles<br/>(Temporal)"]
                KG["Knowledge Graph<br/>(Entity-Relation)"]
            end

            subgraph "Observability Layer"
                TRACE["Trace Collector<br/>(Langfuse / OTel)"]
                METRICS["Metrics<br/>(CloudWatch)"]
                AUDIT["Audit Log<br/>(Immutable)"]
            end
        end
    end

    T1 & T2 & T3 --> GW --> AUTH --> RL
    RL --> ADMIN & RET & ING
    UI --> ADMIN
    ADMIN --> GOV
    GOV --> PG
    ING --> CONN --> PARSE --> CHUNK --> EMB --> VDB
    CONN -.-> S3
    RET --> VDB & REDIS & GRAPH
    RET --> RERANK --> GEN
    RET --> MEM
    MEM --> REDIS & GRAPH & PROFILE
    ING & RET & GEN --> TRACE
    TRACE --> METRICS & AUDIT
```

### 2.2 Core Architectural Principles

| # | Principle | How It's Applied |
|---|-----------|-----------------|
| 1 | **Namespace Isolation** | Every team's data (vectors, docs, memory, cache) is logically or physically isolated by `team_id` |
| 2 | **Distributed & Stateless** | All services are horizontally scalable containers; state lives in managed datastores |
| 3 | **Defence in Depth** | API key auth → rate limiting → namespace guard → PII redaction → audit log |
| 4 | **Event-Driven Ingestion** | Upload events → SQS → async worker pipeline (no blocking the API) |
| 5 | **Hybrid RAG** | Dense vector + sparse BM25 + knowledge graph retrieval fused by a re-ranker |
| 6 | **Tiered Caching** | L1 (in-process) → L2 (Redis exact) → L3 (Redis semantic) → L4 (Vector DB) |
| 7 | **Policy-as-Code Governance** | Access policies, data retention, PII rules defined as code, versioned in Git |
| 8 | **Observability First** | Every retrieval chain has a trace ID linking query → retrieval → generation → response |

### 2.3 Namespace Isolation Architecture

```mermaid
graph LR
    subgraph "Single Qdrant Cluster"
        direction TB
        
        subgraph "Collection: documents"
            A1["Vector + Payload<br/>team_id=alpha"]
            A2["Vector + Payload<br/>team_id=beta"]
            A3["Vector + Payload<br/>team_id=gamma"]
        end
        
        subgraph "Tiered Sharding (v1.16+)"
            SHARED["Fallback Shard<br/>(small teams)"]
            DEDA["Dedicated Shard<br/>(Team Alpha — whale)"]
        end
    end
    
    subgraph "PostgreSQL"
        PG_T["teams table"]
        PG_D["documents table<br/>(team_id FK)"]
        PG_K["api_keys table<br/>(team_id FK)"]
    end

    subgraph "Redis"
        R1["cache:alpha:*"]
        R2["cache:beta:*"]
        R3["memory:alpha:*"]
        R4["memory:beta:*"]
    end
```

**Isolation Strategy (3 tiers):**

| Layer | Isolation Mechanism | Details |
|-------|-------------------|---------|
| **API Gateway** | API key → `team_id` resolution | Every request carries team context |
| **Vector DB** | Payload-based filtering (`team_id`) + tiered sharding | Qdrant `is_tenant=true` on `team_id` field; whale teams get dedicated shards |
| **PostgreSQL** | Row-Level Security (RLS) | `WHERE team_id = current_setting('app.team_id')` on all tables |
| **Redis** | Key prefix namespacing | `{service}:{team_id}:{key}` pattern |
| **S3** | Prefix-based isolation | `s3://bucket/raw/{team_id}/...` |
| **Memory** | Scoped memory stores | Per-team memory graph; no cross-contamination |

### 2.4 Component Inventory

| Component | Technology | Why This Choice |
|-----------|-----------|----------------|
| **API Gateway** | AWS ALB + WAF | DDoS protection, TLS termination, path-based routing |
| **Auth** | Custom + AWS Cognito | API key validation (fast path) + OAuth for admin UI |
| **Ingestion Queue** | Amazon SQS (FIFO) | Exactly-once processing, dead-letter queues, no ops |
| **Ingestion Workers** | ECS Fargate (Celery) | Auto-scaling, zero server management |
| **Source Connectors** | MCP Servers (FastMCP) | GOS DB, DynamoDB, Athena, Confluence, Teams/Outlook |
| **Parser** | Unstructured.io | Best-in-class PDF/DOCX/CSV/HTML extraction |
| **Chunker** | Semantic chunking (LangChain) | Boundary-aware splitting preserving context |
| **Embedding** | Amazon Bedrock Titan v2 | Managed, scalable, 1024-dim, AWS-native |
| **Vector DB** | Qdrant (self-hosted on EKS) | Native multi-tenancy, HNSW, tiered sharding |
| **Metadata DB** | Amazon Aurora PostgreSQL | RLS, JSONB, battle-tested relational store |
| **Cache** | Amazon ElastiCache (Redis 7+) | Vector similarity search (HNSW), TTL, pub/sub |
| **Knowledge Graph** | Amazon Neptune | Managed graph DB, Gremlin/SPARQL, entity relations |
| **Memory Engine** | Custom (Mem0-inspired) | Hybrid: vector + KG + key-value per team |
| **Re-ranker** | Cohere Rerank v3 / cross-encoder | Dramatically improves retrieval precision |
| **Generation** | Amazon Bedrock (Claude 3.5) | Managed, secure, no model hosting |
| **Observability** | Langfuse (self-hosted) | OSS, OTel-native, traces + evals + prompts |
| **Admin UI** | Next.js + shadcn/ui | Modern, responsive, team management |
| **IaC** | AWS CDK (Python) | Same language as backend, L2 constructs |
| **CI/CD** | GitHub Actions + ECR | Container builds, automated deploys |

---

## 3. Low-Level Design (LLD)

### 3.1 Data Model (PostgreSQL)

```mermaid
erDiagram
    TEAMS ||--o{ API_KEYS : has
    TEAMS ||--o{ DOCUMENTS : owns
    TEAMS ||--o{ TEAM_MEMBERS : has
    TEAMS ||--o{ NAMESPACES : has
    TEAMS ||--o{ MEMORY_ENTRIES : has
    USERS ||--o{ TEAM_MEMBERS : belongs_to
    DOCUMENTS ||--o{ CHUNKS : split_into
    DOCUMENTS ||--o{ INGESTION_JOBS : processed_by
    NAMESPACES ||--o{ DOCUMENTS : contains

    TEAMS {
        uuid id PK
        string name
        string slug UK
        jsonb settings
        string tier "free|pro|enterprise"
        int vector_quota_mb
        timestamp created_at
        timestamp updated_at
    }

    API_KEYS {
        uuid id PK
        uuid team_id FK
        string key_prefix "nxr_<team_slug>_"
        string key_hash "SHA-256"
        string name
        string[] scopes "read|write|admin"
        boolean is_active
        timestamp last_used_at
        timestamp expires_at
        timestamp created_at
    }

    USERS {
        uuid id PK
        string email UK
        string name
        string password_hash
        string role "admin|user"
        timestamp created_at
    }

    TEAM_MEMBERS {
        uuid team_id FK
        uuid user_id FK
        string role "owner|editor|viewer"
        timestamp joined_at
    }

    NAMESPACES {
        uuid id PK
        uuid team_id FK
        string name
        string description
        jsonb config
        timestamp created_at
    }

    DOCUMENTS {
        uuid id PK
        uuid team_id FK
        uuid namespace_id FK
        string source_type "pdf|docx|csv|confluence|teams|mcp"
        string filename
        string s3_key
        bigint file_size_bytes
        string content_hash "SHA-256 dedup"
        string status "pending|processing|ready|error"
        jsonb metadata
        int chunk_count
        timestamp created_at
        timestamp processed_at
    }

    CHUNKS {
        uuid id PK
        uuid document_id FK
        uuid team_id FK
        int chunk_index
        text content
        string vector_id "Qdrant point ID"
        jsonb metadata
        int token_count
    }

    INGESTION_JOBS {
        uuid id PK
        uuid team_id FK
        uuid document_id FK
        string status "queued|processing|completed|failed"
        jsonb error_details
        int retry_count
        timestamp started_at
        timestamp completed_at
    }

    MEMORY_ENTRIES {
        uuid id PK
        uuid team_id FK
        string user_context
        text memory_content
        string memory_type "fact|preference|event|relation"
        float relevance_score
        jsonb temporal_metadata
        string vector_id
        timestamp created_at
        timestamp last_accessed
    }
```

### 3.2 API Key Lifecycle

```mermaid
sequenceDiagram
    participant Admin as Team Admin
    participant UI as Admin UI
    participant API as Admin API
    participant DB as PostgreSQL
    participant Cache as Redis

    Admin->>UI: Create new API key
    UI->>API: POST /api/teams/{team_id}/keys
    API->>API: Generate key: nxr_{slug}_{uuid4}
    API->>API: Hash key with SHA-256
    API->>DB: INSERT api_keys (key_hash, team_id, scopes)
    API->>Cache: SET key_hash → {team_id, scopes, tier} (TTL 5min)
    API-->>UI: Return plaintext key (SHOWN ONCE)
    UI-->>Admin: Display key + usage instructions

    Note over Admin, Cache: --- Runtime Flow ---

    participant Client as Team's App
    participant GW as API Gateway

    Client->>GW: GET /v1/retrieve (Header: X-API-Key: nxr_alpha_****)
    GW->>API: Forward request
    API->>API: Hash received key
    API->>Cache: GET key_hash
    alt Cache Hit
        Cache-->>API: {team_id, scopes, tier}
    else Cache Miss
        API->>DB: SELECT * FROM api_keys WHERE key_hash = ?
        DB-->>API: row
        API->>Cache: SET key_hash → data (TTL 5min)
    end
    API->>API: Inject team_id into request context
    API->>API: Validate scopes vs. requested operation
    API->>API: Apply rate limits by tier
```

### 3.3 Ingestion Pipeline (Detailed)

```mermaid
graph TD
    A["User uploads PDF/DOCX/CSV<br/>via UI or API"] --> B["API Server"]
    B --> C{"File validation<br/>size, type, virus scan"}
    C -->|Pass| D["Upload to S3<br/>s3://bucket/raw/{team_id}/{doc_id}"]
    C -->|Fail| E["Return 400 error"]
    D --> F["Insert DOCUMENTS row<br/>status=pending"]
    F --> G["Publish to SQS<br/>{doc_id, team_id, s3_key}"]
    
    subgraph "Ingestion Worker (ECS Fargate)"
        G --> H["Dequeue message"]
        H --> I["Download from S3"]
        I --> J["Parse with Unstructured<br/>PDF→Markdown, DOCX→Text"]
        J --> K["Semantic Chunking<br/>target: 512 tokens<br/>overlap: 50 tokens"]
        K --> L["Generate Embeddings<br/>Bedrock Titan v2 (batch)"]
        L --> M["Upsert to Qdrant<br/>collection: documents<br/>payload: {team_id, doc_id, ...}"]
        M --> N["Insert CHUNKS rows"]
        N --> O["Update DOCUMENT<br/>status=ready"]
        O --> P["ACK SQS message"]
    end
    
    H --> Q{"Error?"}
    Q -->|Yes| R["Increment retry_count<br/>Update status=error"]
    R --> S["DLQ after 3 retries"]
```

### 3.4 Retrieval Pipeline (Hybrid RAG)

```mermaid
graph TD
    A["User Query<br/>+ API Key + team_id"] --> B["Query Router"]
    
    B --> C["Semantic Cache Check<br/>Redis: embed(query) → cosine sim"]
    C -->|Cache Hit ≥0.95| D["Return cached response"]
    
    C -->|Cache Miss| E["Query Expansion<br/>HyDE / Multi-Query"]
    
    E --> F["Parallel Retrieval"]
    
    F --> G["Dense Vector Search<br/>Qdrant (HNSW)<br/>filter: team_id={id}"]
    F --> H["Sparse BM25 Search<br/>Qdrant (sparse vectors)"]
    F --> I["Knowledge Graph<br/>Neptune: entity lookup"]
    F --> J["Memory Retrieval<br/>Mem0: user context"]
    
    G & H --> K["Reciprocal Rank Fusion<br/>(RRF)"]
    I --> K
    J --> K
    
    K --> L["Re-ranker<br/>Cohere Rerank v3<br/>Cross-encoder scoring"]
    
    L --> M["Context Assembly<br/>Top-K chunks + memory + KG facts"]
    
    M --> N["LLM Generation<br/>Bedrock Claude 3.5<br/>with citations"]
    
    N --> O["PII Redaction<br/>Post-process"]
    
    O --> P["Cache Response<br/>Redis: embed(query) → response<br/>TTL 1hr"]
    
    P --> Q["Return Response<br/>+ source citations<br/>+ trace_id"]
    
    N --> R["Emit Trace<br/>Langfuse"]
```

### 3.5 Memory Layer Architecture

```mermaid
graph TB
    subgraph "Memory Engine (per team_id)"
        direction TB
        
        subgraph "Working Memory (L1)"
            WM["In-Session Context<br/>(Redis, TTL 30min)"]
        end
        
        subgraph "Episodic Memory (L2)"
            EM["Conversation History<br/>(PostgreSQL + Vector)"]
        end
        
        subgraph "Semantic Memory (L3)"
            SM["Facts & Preferences<br/>(Qdrant + KG)"]
        end
        
        subgraph "Procedural Memory (L4)"
            PM["Learned Patterns<br/>(Neo4j/Neptune)"]
        end
    end
    
    WM --> EM --> SM --> PM
    
    subgraph "Memory Operations"
        EX["Extract<br/>parse messages → atomic facts"]
        ST["Store<br/>embed + graph + KV"]
        RE["Retrieve<br/>context-aware recall"]
        UP["Update<br/>conflict resolution + decay"]
    end
    
    EX --> ST --> RE
    UP --> ST
```

**Memory Layer Design (Mem0-inspired):**

| Memory Type | Storage | Retrieval Strategy | TTL |
|------------|---------|-------------------|-----|
| **Working** | Redis hash | Exact key lookup | 30 min (session) |
| **Episodic** | PostgreSQL + Qdrant | Vector similarity + recency | 90 days |
| **Semantic** | Qdrant + Neptune KG | Hybrid: vector + graph traversal | Permanent |
| **Procedural** | Neptune KG | Pattern matching on graph | Permanent |

### 3.6 Cache Layer Architecture

```mermaid
graph LR
    Q["User Query"] --> L1["L1: In-Process<br/>LRU (100 items)<br/>~0.01ms"]
    L1 -->|Miss| L2["L2: Redis Exact<br/>Hash of query<br/>~1ms"]
    L2 -->|Miss| L3["L3: Redis Semantic<br/>Vector similarity<br/>threshold ≥0.95<br/>~5ms"]
    L3 -->|Miss| L4["L4: Full RAG<br/>Vector DB + LLM<br/>~500-2000ms"]
    
    L4 -->|Populate| L3
    L4 -->|Populate| L2
```

| Cache Tier | Technology | Key Strategy | TTL | Invalidation |
|-----------|-----------|-------------|-----|-------------|
| **L1** | Python `lru_cache` | `hash(query + team_id)` | 60s | Process restart |
| **L2** | Redis String | `SHA-256(query + team_id)` | 1 hour | On doc re-ingestion |
| **L3** | Redis Vector (HNSW) | `embed(query)` + `team_id` filter | 6 hours | On doc re-ingestion |
| **L4** | Qdrant + LLM | Full retrieval pipeline | N/A | Source of truth |

### 3.7 Access Control Model

```mermaid
graph TD
    subgraph "RBAC Hierarchy"
        SA["Platform Admin<br/>(super_admin)"]
        TO["Team Owner<br/>(owner)"]
        TE["Team Editor<br/>(editor)"]
        TV["Team Viewer<br/>(viewer)"]
        AK["API Key<br/>(scoped)"]
    end
    
    SA --> TO --> TE --> TV
    TO --> AK
    
    subgraph "Permissions Matrix"
        P1["manage_teams ✅ owner"]
        P2["create_api_keys ✅ owner"]
        P3["upload_documents ✅ editor+"]
        P4["delete_documents ✅ editor+"]
        P5["query_data ✅ viewer+"]
        P6["view_traces ✅ viewer+"]
        P7["manage_namespaces ✅ editor+"]
    end
```

### 3.8 MCP Integration Points

| MCP Server | Data Source | Direction | Tools |
|-----------|-----------|-----------|-------|
| **GOS DB MCP** | JPMC GOS DB (Oracle) | Ingest + Query | `query_gosdb`, `list_schemas`, `describe_table` |
| **DynamoDB MCP** | AWS DynamoDB | Ingest + Query | `query_table`, `scan_table`, `get_item` |
| **Athena MCP** | AWS Athena / S3 data lake | Query | `execute_query`, `list_databases` |
| **Confluence MCP** | Atlassian Confluence | Ingest | `get_pages`, `search_content`, `get_spaces` |
| **Teams/Outlook MCP** | Microsoft Graph API | Ingest | `get_messages`, `search_mail`, `get_channels` |
| **App Logs MCP** | CloudWatch / ELK | Ingest + Query | `get_log_events`, `search_logs` |
| **Agent Logs MCP** | Langfuse / LangSmith | Ingest + Query | `get_traces`, `get_runs`, `search_spans` |

### 3.9 AWS Deployment Architecture

```mermaid
graph TB
    subgraph "AWS Account"
        subgraph "VPC (10.0.0.0/16)"
            subgraph "Public Subnets"
                ALB["Application Load Balancer<br/>+ WAF + ACM Certificate"]
            end
            
            subgraph "Private Subnets (App Tier)"
                EKS["EKS Cluster"]
                subgraph "EKS Pods"
                    API_POD["API Server<br/>(3 replicas)"]
                    ING_POD["Ingestion Workers<br/>(auto-scale 1-20)"]
                    MCP_POD["MCP Servers<br/>(2 replicas)"]
                    UI_POD["Admin UI<br/>(2 replicas)"]
                end
            end
            
            subgraph "Private Subnets (Data Tier)"
                AURORA["Aurora PostgreSQL<br/>(Multi-AZ)"]
                QDRANT_C["Qdrant Cluster<br/>(3 nodes, r6g.2xlarge)"]
                REDIS_C["ElastiCache Redis<br/>(Cluster Mode)"]
                NEPTUNE["Amazon Neptune<br/>(Knowledge Graph)"]
            end
        end
        
        S3_B["S3<br/>(Raw Documents)"]
        SQS_Q["SQS FIFO Queue<br/>(Ingestion)"]
        BEDROCK["Amazon Bedrock<br/>(Embeddings + LLM)"]
        CW["CloudWatch<br/>(Metrics + Logs)"]
        SM["Secrets Manager"]
        ECR["ECR<br/>(Container Registry)"]
    end
    
    ALB --> API_POD & UI_POD
    API_POD --> AURORA & QDRANT_C & REDIS_C & SQS_Q & BEDROCK & NEPTUNE
    ING_POD --> S3_B & AURORA & QDRANT_C & BEDROCK
    MCP_POD --> AURORA
    SQS_Q --> ING_POD
    API_POD & ING_POD --> SM
    API_POD & ING_POD & MCP_POD --> CW
```

### 3.10 Microservice Decomposition

| Service | Responsibilities | Language | Scales By |
|---------|-----------------|----------|-----------|
| **api-server** | Auth, routing, query orchestration, team mgmt | Python (FastAPI) | Request volume |
| **ingestion-worker** | Document processing, chunking, embedding | Python (Celery) | Queue depth |
| **retrieval-engine** | Hybrid search, re-ranking, context assembly | Python (FastAPI) | Query volume |
| **memory-service** | Extract/store/retrieve/update memories | Python (FastAPI) | User count |
| **mcp-gateway** | MCP server aggregation for external sources | Python (FastMCP) | Connector count |
| **admin-ui** | Frontend for team/document/key management | TypeScript (Next.js) | Users |
| **observability-collector** | Trace aggregation, metrics emission | Python (OTel SDK) | Event volume |

---

## 4. Proposed Changes — MVP Scope

### Phase 1: Foundation (Weeks 1-3)
- PostgreSQL schema (teams, api_keys, documents, chunks)
- API key generation, hashing, validation
- FastAPI server with auth middleware
- S3 upload + SQS ingestion pipeline
- Basic chunking + embedding (Bedrock Titan)
- Qdrant single-collection multi-tenant setup

### Phase 2: Retrieval + Cache (Weeks 4-5)
- Hybrid retrieval (dense + sparse)
- Re-ranker (Cohere)
- L2 + L3 semantic cache (Redis)
- LLM generation with citations (Bedrock Claude)

### Phase 3: Memory + MCP (Weeks 6-7)
- Memory layer (working + episodic + semantic)
- MCP servers (GOS DB, DynamoDB, Athena — already built)
- Confluence + Teams connectors (MCP)

### Phase 4: Admin UI + Observability (Weeks 8-9)
- Next.js admin dashboard
- Team management, API key CRUD
- Document upload UI, namespace viewer
- Langfuse integration for tracing

### Phase 5: Governance + Hardening (Weeks 10-12)
- RBAC enforcement
- PII redaction pipeline
- Rate limiting per tier
- CDK deployment scripts
- Load testing + security audit

---

## 5. Open Questions

> [!IMPORTANT]
> **Vector DB Choice**: Qdrant (self-hosted on EKS) vs. AWS OpenSearch Serverless. Qdrant has native tiered multi-tenancy; OpenSearch is fully managed. Which do you prefer?

> [!IMPORTANT]
> **Embedding Model**: Bedrock Titan v2 (AWS-native, 1024d) vs. OpenAI `text-embedding-3-large` (3072d, higher quality). Titan avoids external network calls. Preference?

> [!WARNING]
> **Knowledge Graph**: Amazon Neptune ($$$) vs. Neo4j Community (self-hosted, free). Neptune is managed but expensive. For MVP, should we start without graph RAG and add it in Phase 3+?

> [!IMPORTANT]
> **LLM Provider**: Amazon Bedrock (Claude 3.5 Sonnet) vs. self-hosted vLLM (e.g., Llama 3.1 70B on EKS GPU nodes). Bedrock is fastest to production; self-hosted reduces per-token cost at scale.

> [!IMPORTANT]
> **GOS DB Access**: For the MCP server to connect to GOS DB, we need the actual: hostname, service name, Oracle wallet location (or credentials), and schema whitelists. Can you provide or get these from your DBA team?

> [!WARNING]
> **Compliance**: Does JPMC require specific data residency (e.g., us-east-1 only)? Are there internal security review gates before deploying to AWS?

---

## 6. Verification Plan

### Automated Tests
```bash
# Unit tests (guardrails, auth, cache)
pytest tests/ -v --cov=nexusrag --cov-report=html

# Integration tests (ingestion pipeline end-to-end)
pytest tests/integration/ -v --timeout=120

# Load test (retrieval latency under concurrent teams)
locust -f tests/load/locustfile.py --users=100 --spawn-rate=10
```

### Manual Verification
- Upload PDF/DOCX/CSV via UI → verify chunks appear in Qdrant with correct `team_id`
- Query via API key → verify namespace isolation (Team A cannot see Team B's data)
- Rotate API key → verify old key stops working within cache TTL (5 min)
- Check Langfuse traces → verify full retrieval chain is instrumented
- Memory test → have conversation, close session, re-open → verify memory recall

### Performance Targets
| Metric | Target | Measurement |
|--------|--------|-------------|
| **Query P95 latency (cache hit)** | < 50ms | Load test |
| **Query P95 latency (cache miss)** | < 3s | Load test |
| **Ingestion throughput** | 100 docs/min | Celery monitoring |
| **Namespace isolation** | 0 cross-tenant leaks | Security test suite |
| **API key validation** | < 5ms | Benchmark |
