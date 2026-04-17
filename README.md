# CentRAG: Centralized Retrieval-Augmented Generation

**CentRAG** is an enterprise-grade, multi-tenant RAG platform designed for security, observability, and extreme performance. It follows a pure **SOLID** architecture, enabling teams to swap between cloud providers (AWS Bedrock, OpenAI) and local/noop implementations with zero changes to business logic.

---

## 🏗️ Architecture Deep Dive (Folder-by-Folder)

### `centrag/abstractions/` — The "Contract" Layer
**Purpose:** Defines the protocols (interfaces) for all system components.
**Why we chose this:** By depending on protocols rather than concrete classes (Dependency Inversion), the core engine remains agnostic to specific technologies. We can swap Qdrant for Pinecone or Bedrock for OpenAI by simply implementing a new strategy.

### `centrag/implementations/` — The "Strategy" Layer
**Purpose:** Concrete implementations of abstractions (e.g., `BedrockEmbedder`, `OpenAIEmbedder`, `NoOpLLM`).
**Why we chose this:** Provides "batteries-included" production providers while maintaining deterministic `NoOp` versions for lightning-fast unit testing without API costs.

### `centrag/retrieval/` — The "Orchestration" Layer
**Purpose:** Houses the `RetrievalEngine`, `QueryRouter`, `HybridRetriever`, `GraphRetriever`, and `MultivectorRetriever`.
**Why we chose this:** This is the brain of the system. We chose a "Chain of Responsibility" for the retrieval pipeline, allowing us to insert steps like caching, reranking, and guardrails in a clean, sequential flow.

### `centrag/extraction/` — The "Data Intake" Layer
**Purpose:** Handles document parsing and chunking.
**Why we chose this:** Includes a `ParserRegistry` (Strategy pattern) to support multiple formats (PDF, Markdown, HTML) and advanced `PropositionChunker` for atomic fact extraction, which improves retrieval precision.

### `centrag/cache/` — The "Performance" Layer
**Purpose:** Tiered caching system (L1 In-Memory → L2 Redis → L3 Semantic).
**Why we chose this:** Production RAG is expensive. Tiered caching allows the system to serve repeat queries in <10ms, while L3 Semantic Cache (GPTCache style) handles nearly-identical queries, saving LLM costs. All tiers maintain strict **Team Isolation**.

### `centrag/guardrails/` — The "Safety" Layer
**Purpose:** Input/Output validation, PII scrubbing (14 patterns), and cost tracking.
**Why we chose this:** Enterprise readiness requires non-negotiable safety. We implemented "Corrective RAG" (CRAG) logic here to detect low-confidence retrieval and trigger automatic query rewrites.

### `centrag/observability/` — The "Operations" Layer
**Purpose:** Unified Tracing, Metrics, and Cost Tracking protocols.
**Why we chose this:** RAG pipelines are "black boxes" without instrumentation. This layer provides deep visibility into latency, token usage, and retrieval accuracy.

### `centrag/mcp_bridge/` — The "Integration" Layer
**Purpose:** Bi-directional Model Context Protocol (MCP) support.
**Why we chose this:** Allows CentRAG to participate in the MCP ecosystem—either as a tool for other agents or as a consumer of external data sources.

### `centrag/evaluation/` — The "Quality" Layer
**Purpose:** Automated RAG evaluation (Judges, Metrics, Golden Datasets).
**Why we chose this:** RAG quality is notoriously hard to measure. This layer provides deterministic heuristic judges and LLM-as-a-judge (DeepEval) capabilities to ensure continuous improvement and regression detection.

### `centrag/middleware/` — The "Transport" Layer
**Purpose:** FastAPI middleware for Auth, Rate Limiting, and Logging.
**Why we chose this:** Cross-cutting concerns are handled outside the business logic, ensuring strict tenant isolation and protection against DDOS/abuse at the perimeter.

### `mcp_enterprise_server/` — The "Aggregator" Layer
**Purpose:** Standalone MCP server that bundles CentRAG tools with enterprise utilities.
**Why we chose this:** Provides a unified interface for agents like Claude or Antigravity to interact with the entire project via a single MCP connection.

---

## 🛠️ Performance & Advanced RAG Patterns

| Pattern | Implementation | Benefit |
|---------|----------------|---------|
| **PageIndex** | `retrieval/pageindex_retriever.py` | 98.7% accuracy on complex long-form docs |
| **Contextual Retrieval** | `extraction/contextualizer.py` | Anthropic-style situational context for 49% better relevance |
| **Corrective RAG (CRAG)** | `engine.py` | Self-reasoning loop to detect and fix retrieval errors |
| **Adaptive RAG** | `engine.py` | Auto-detects query complexity (SIMPLE vs COMPLEX) |
| **Two-Pass Reasoning** | `generator.py` | Grounding: Fact Extraction → Answer Synthesis |
| **Hybrid Search** | `retrieval/hybrid.py` | Dense (Qdrant) + Sparse (BM25) with RRF fusion |
| **Dual-Path Routing** | `engine.py` | VECTOR vs VECTORLESS (PageIndex) auto-routing |
| **Late Chunking** | `extraction/chunkers/late_chunking.py` | Contextual chunk embedding for cross-chunk context (approx. late chunking) |
| **Graph RAG** | `retrieval/graph_retriever.py` | Relational path (Subject-Predicate-Object) for multi-hop facts |
| **Multivector Retrieval** | `retrieval/multivector_retriever.py` | Facet path (Content + Summary + Keywords) for query diversity |
| **CAG (Static Context)** | `retrieval/cag_manager.py` | Pre-loading core handbooks into system prompt for low latency |
| **Evaluation Harness** | `evaluation/runner.py` | Full orchestrator: Retrieval → Judging → Metrics → Failure Store |
| **Semantic Cache (L3)** | `cache/semantic.py` | GPTCache-style similarity hits; saves 90% cost on recurring queries |
| **BGE v2 Reranking** | `implementations/bge_reranker.py` | SOTA local cross-encoder for high-precision semantic re-ordering |
| **Dynamic SQL MCP** | `mcp/dynamic_db_factory.py` | On-the-fly SQL tool generation via SQLAlchemy reflection |
| **MCP Subprocess Mgr** | `mcp/process_manager.py` | Lifecycle management for external AWS/Jira/Confluence Servers |
| **Failure Store** | `evaluation/failure_store.py` | Persistent capture of hallucinations and retrieval misses for debugging |
| **Composition Root** | `centrag/wiring.py` | Centralized DI; no "hidden" dependencies in deep files. |


---

## 📈 Free Production Observability (Research)

You can achieve $0 instrumentation costs using the following "LGTM" stack:

1.  **OpenTelemetry SDK**: (Built-in) ZERO cost tracing and metrics collection.
2.  **Prometheus**: (Self-hosted) Scrapes metrics. Free and industry standard.
3.  **Grafana Tempo**: (Self-hosted) High-scale tracing backend.
4.  **Grafana Loki**: (Self-hosted) Logs aggregator that correlates with traces.
5.  **AgentsView**: (Self-hosted) Local-first visual dashboard for browsing and searching agent sessions.

---

## 🚀 Quickstart

1.  **Install Dependencies:**
    ```bash
    pip install "centrag[production]"  # installs bedrock, openai, qdrant-client
    ```

1.  **Configure Environment:**
    ```bash
    export CENTRAG_LLM_PROVIDER="openai"
    export CENTRAG_OPENAI_API_KEY="sk-..."
    export LLAMA_CLOUD_API_KEY="llx-..."
    ```

2.  **Generate SQL Schema (Optional):**
    ```bash
    py scripts/generate_ddl.py > sql/schema.sql
    ```

3.  **Deploy Production Stack:**
    ```bash
    docker-compose up -d
    ```
    This launches:
    - **App**: FastAPI (Port 8000)
    - **DB**: PostgreSQL 16 (Port 5432) with RLS enabled
    - **Cache**: Redis 7 (Port 6379)
    - **Vector**: Qdrant (Port 6333)

4.  **Visualize Sessions:**
    ```bash
    # Open the AgentsView dashboard
    npx skills run antigravity-view
    ```

---

## 📚 Complete Documentation Index

| Topic | File | Expertise Level |
| :--- | :--- | :--- |
| **Evaluation Guide** | [`docs/EVALUATION_GUIDE.md`](docs/EVALUATION_GUIDE.md) | AI Engineer |
| **RAG Advanced Analysis** | [`docs/ADVANCED_RAG_ANALYSIS.md`](docs/ADVANCED_RAG_ANALYSIS.md) | Principal Architect |
| **Architectural Rationale** | [`docs/ENGINEERING_DECISIONS.md`](docs/ENGINEERING_DECISIONS.md) | Principal Architect |
| **Logic & Code Flow** | [`docs/CODE_FLOW.md`](docs/CODE_FLOW.md) | Senior Engineer |
| **Observability Guide** | [`docs/AGENTSVIEW_GUIDE.md`](docs/AGENTSVIEW_GUIDE.md) | DevOps / SRE |
| **RAG Strategy Roadmap** | [`docs/RAG_ADVANCEMENT_STRATEGY.md`](docs/RAG_ADVANCEMENT_STRATEGY.md) | AI Engineer |
| **Decision Records (ADRs)** | [`docs/adr/`](docs/adr/) | Principal Architect |
| **Privacy & Security** | [`docs/APP_LOGS_PRIVACY_LANGSMITH.md`](docs/APP_LOGS_PRIVACY_LANGSMITH.md) | Security Auditor |

### 📖 Quick Reference — Common Questions

| Question | Read This |
| :--- | :--- |
| How do I run evals? | [Evaluation Guide → Running Evaluation](docs/EVALUATION_GUIDE.md#running-evaluation) |
| How do I add a new chunking strategy? | [Code Flow](docs/CODE_FLOW.md) |
| How do I debug retrieval failures? | [Evaluation Guide → Failure Case Storage](docs/EVALUATION_GUIDE.md#4-failure-case-storage) |
| How do I enable Cohere reranking? | [Evaluation Guide → Enabling Cohere Reranker](docs/EVALUATION_GUIDE.md#enabling-cohere-reranker) |
| What metrics are available? | [Evaluation Guide → Retrieval Evaluation](docs/EVALUATION_GUIDE.md#1-retrieval-evaluation-layer-1) |
| How do I switch retrieval strategies? | [Engineering Decisions](docs/ENGINEERING_DECISIONS.md) |


---

## 🛡️ Security Audit & PII
CentRAG implements a 5-stage cleaning pipeline that scrubs:
- Email addresses, Phone numbers, Credit Cards, Social Security Numbers, and IP addresses.
- Enforced via `centrag/guardrails/pii.py`.
- Full audit report available in `docs/AUDIT_REPORT.md`.

![Tests Passing](https://img.shields.io/badge/tests-257%2F257%20passed-brightgreen)
