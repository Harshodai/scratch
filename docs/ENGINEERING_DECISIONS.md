# CentRAG: Engineering Decisions & Architectural Intelligence

This document provides a deep-dive into the technical decisions, RAG strategies, and architectural patterns implemented in CentRAG. It follows the **5W's Approach** (Who, What, Where, When, Why) for each major component to ensure maximum clarity for engineers and architects.

---

## 1. Local-First Vector Infrastructure
CentRAG uses **Qdrant** as its primary vector database, optimized for hybrid retrieval.

- **Who**: Managed by `centrag.implementations.qdrant_vectorstore.QdrantVectorStore`.
- **What**: High-performance vector database supporting both dense and sparse vectors.
- **Where**: Deployed via `docker-compose.yml` or run in local-mode (disk-backed) for isolated dev environments.
- **When**: Triggered during `Step 5: VECTOR PATH` in the retrieval engine.
- **Why**: Qdrant's native support for sparse vectors makes it the ideal candidate for CentRAG's Hybrid (Dense + BM25) strategy without needing separate infrastructure for keyword search.

---

## 2. Advanced RAG Strategy (The 5W's)

### A. Dynamic i18n Stop-Word Filtering
Language-aware preprocessing for sparse vectors.

- **Who**: `centrag.implementations.bm25_sparse_embedder.BM25SparseEmbedder`.
- **What**: Uses `langdetect` to identify document language and `nltk.corpus.stopwords` to filter out grammatical "glue" words.
- **Where**: Triggered during document ingestion and query time for sparse vectorization.
- **When**: Every time a text segment is converted to a sparse representation.
- **Why**: Prevents sparse vectors from being inflated by common non-English words (e.g., "le", "la", "et" in French), improving retrieval precision in multi-lingual environments.
- **Payload Details**:
    - **Input**: Raw text string.
    - **Logic**: `detect(text)` → `nltk.stopwords.words(lang)` → `SHA256` caching for performance.
    - **Output**: Filtered token counts (sparse vector).

### B. Contextual Retrieval (Situated Summaries)
The Anthropic 2024 "Pre-computation" Pattern.

- **Who**: `centrag.extraction.pipeline.ExtractionPipeline`.
- **What**: Orchestrates an LLM-based pass during ingestion to generate 1-sentence situational summaries for every chunk.
- **Where**: Within the `ExtractionPipeline.process` method.
- **When**: Post-parsing and pre-embedding during document ingestion.
- **Why**: Traditional chunks often lose context (e.g., "The revenue grew by 10%" without knowing it refers to "2023 Q4"). Prepended summaries "situate" the chunk within the document, significantly improving retrieval accuracy.
- **Payload Details**:
    - **Input**: Full document text + segment chunk.
    - **Prompt**: `<document>{full_doc}</document>\n\nHere is a chunk... Summarize its context in 1 sentence.`
    - **Output**: `[Situated Context]: {summary}\n\n{original_chunk_content}`.

### C. Adaptive RAG (Complexity Routing)
Intelligent query routing to balance cost vs. quality.

- **Who**: `LLMProtocol.classify_complexity`.
- **What**: Classifies incoming queries into `SIMPLE`, `MODERATE`, or `COMPLEX` categories.
- **Where**: `centrag.retrieval.engine.RetrievalEngine` (Entry logic).
- **When**: On every incoming query before retrieval starts.
- **Why**: Saves cost by skipping retrieval for basic facts and ensures complex multi-hop reasoning is handled by higher-order models.

### D. Corrective RAG (CRAG)
Autonomous validation of retrieval quality.

- **Who**: Orchestrated by `RetrievalEngine` using `RerankerProtocol`.
- **What**: If the reranker scores retrieved chunks below a confidence threshold, the engine triggers a "rewrite-and-retry" loop.
- **Where**: `centrag/retrieval/engine.py` (Post-rerank logic).
- **When**: After initial retrieval if confidence is low.
- **Why**: Prevents "hallucination by proxy" where the LLM tries to answer from irrelevant context.

### E. Contextual Compression (Dynamic Refinement)
Post-retrieval LLM-based context pruning.

- **Who**: `RetrievalEngine._compress_context`.
- **What**: Uses a fast LLM pass to extract ONLY the specific sentences within retrieved chunks that answer the user's query.
- **Where**: `centrag/retrieval/engine.py` (Post-retrieval, pre-generation).
- **When**: If `CENTRAG_ENABLE_CONTEXTUAL_COMPRESSION=true`.
- **Why**: Reduces context window bloat and noise, leading to more focused and higher-fidelity answers.
- **Payload Details**:
    - **Input**: User query + List of candidate chunks.
    - **Logic**: LLM filters out non-relevant sentences within each chunk.
    - **Output**: A refined, compressed context block for final synthesis.

---

## 3. Addressing System Hallucinations
CentRAG employs a multi-layered defense against LLM inaccuracies:

1. **Strict Grounding (Two-Pass Synthesis)**:
    - **Pass 1**: The LLM extracts atomic facts from the context.
    - **Pass 2**: Final synthesis uses ONLY extracted facts.
2. **Confidence Gating**: If no sources pass the relevance check, the system gracefully responds with "I don't know" rather than forcing an answer.
3. **Reflection Rails**: The `GuardrailEngine` performs post-generation checks to ensure the answer is strictly sourced from provided citations.

---

## 4. Vector vs. Vectorless RAG
CentRAG implements a **Dual-Path Architecture**:

- **Semantic Path (Vector)**: Traditional embedding search. Best for "vibe" checks and broad topical search.
- **Reasoning Path (PageIndex)**: LLM navigates a hierarchical tree of the document. Best for "structural" questions (e.g., "Summarize the risks in Section 4").

---

## 5. Security & Isolation
CentRAG is built for multi-tenant enterprise environments.

- **Tenant Isolation**: Every database query (Postgres and Qdrant) is strictly filtered by `team_id` at the infrastructure layer (RLS in PG, Must-Filters in Qdrant).
- **PII Scrubbing**: A 5-stage cleaning pipeline in `DocumentCleaner` handles 14 categories of PII, ensuring sensitive data never reaches the LLM or index in raw form.
- **Guardrail Engine**: Pluggable `InputRail` and `OutputRail` systems protect against prompt injection and ensure data safety.

---

## 6. Observability & Performance
- **Tiered Caching**:
    - **L1 (In-Memory)**: 5-minute TTL for active bursts.
    - **L2 (Redis)**: Cross-instance scalar hits.
    - **L3 (Semantic)**: `centrag/cache/semantic.py` implementing the **SSDataManager** pattern.
- **SSDataManager Pattern**: Decouples Vector Similarity from Scalar Storage. Qdrant performs the similarity search (threshold 0.95), but the full Answer payload is stored in the `scalar_store` (Redis) to minimize the Qdrant memory footprint and allow metadata-rich caching.
- **LLM Gateway**: Implements **Circuit Breakers** and **Budget Gating** to prevent runaway cloud costs and cascade failures during provider outages.
- **CentragLogger**: Standardized `structlog`-based logging with `ELK/Datadog` ready JSON outputs and colored console outputs for local dev.

---

## 7. API Contracts (REST)

### A. Retrieval: `POST /v1/retrieve`
The primary entry point for grounded intelligence.

**Request Body:**
```json
{
  "query": "string (1-5000 chars)",
  "namespace": "string (default: 'default')",
  "max_results": "integer (1-20, default: 5)",
  "include_memory": "boolean (default: true)",
  "include_sources": "boolean (default: true)",
  "mode": "auto | pageindex | vector | hybrid | rag",
  "target_doc_id": "string (optional UUID)"
}
```

**Response:**
```json
{
  "answer": "string",
  "sources": [
    {
      "content": "string (capped at 1000 chars)",
      "document_id": "uuid",
      "chunk_index": "integer",
      "relevance_score": "float",
      "source_type": "pageindex | vector",
      "reasoning": "string (LLM navigation trace)"
    }
  ],
  "query_complexity": "simple | moderate | complex",
  "cache_tier": "hit | miss | none"
}
```

### B. Ingestion: `POST /v1/documents`
Supports multi-path ingestion (Vector + PageIndex).

**Request:** `multipart/form-data` with `file`, `namespace`, and `async_mode`.

**Response:**
```json
{
  "id": "uuid",
  "filename": "string",
  "status": "pending | processing | ready | failed",
  "tree_available": "boolean",
  "vectors_available": "boolean",
  "chunk_count": "integer"
}
```

---

## 8. Hybrid Retrieval (RRF Fusion)
CentRAG uses **Reciprocal Rank Fusion (RRF)** to merge results from the Semantic (Vector) and Reasoning (PageIndex) paths.

- **Logic**: For each document $d$, the score is calculated as:
  $RRFscore(d) = \sum_{r \in R} \frac{1}{k + rank(r, d)}$
  where $k = 60$ (default constant) and $rank(r, d)$ is the rank of document $d$ in retrieval path $r$.
- **Why**: RRF is parameter-free and robust. It prioritizes documents that appear consistently at the top across different retrieval methodologies (Dense Vector vs. Keyword/Hierarchical), outperforming raw score averaging.

---

## 9. Cross-Encoder Reranking Cascade
To balance retrieval precision with inference latency:

- **What**: A fall-through selection hierarchy:
  1. **Cohere (API)**: Best-in-class, used if API key is present.
  2. **BGE-v2 (Local)**: SOTA local transformer, used if GPU/CPU allows.
  3. **FlashRank (Local)**: Optimized CPU-only cross-encoder for low latency.
  4. **NoOp (Heuristic)**: Simple similarity-scoring fallback.
- **Decision**: CentRAG uses **Sigmoid Normalization** on raw cross-encoder logits to ensure score consistency across different providers, enabling predictable CRAG (Corrective RAG) thresholds.

---

## 10. Model Context Protocol (MCP) Orchestration
Decoupling tools from business logic via a Unified Bridge.

- **What**: `centrag.mcp.bridge.MCPBridge` acts as a facade for:
  - **Dynamic SQL Tools**: Uses SQLAlchemy reflection to generate read-only `SELECT` tools for any target DB.
  - **Managed Subprocesses**: Spawns and manages the lifecycle of external MCP servers (stdio-based JSON-RPC).
- **Decision: Automated Enterprise Integration**: If the `mcp_enterprise_server` directory is present, CentRAG auto-registers it as a managed subprocess, providing secure access to AWS (Athena/S3/DynamoDB) with built-in PII redaction.

---

## 11. Specialized Agent Ecosystem (Quality Gates)
To ensure production hardening, CentRAG implements a suite of custom agent skills in `.gemini/skills/`:

| Skill | Role |
|-------|------|
| `centrag-orchestrator` | Coordinates all gates and provides production readiness scores. |
| `centrag-sdlc-validator` | Enforces the 6-step post-change ritual and TDD. |
| `centrag-architect-review` | Validates SOLID adherence and multi-tenant isolation. |
| `centrag-security-rail` | Detects PII gaps and ensures "localhost" blocking in prod. |
| `centrag-ai-engineer` | Benchmarks retrieval precision and prompt fidelity. |

---

## 12. Final Gap Assessment (Verified 2026-04-17)
| Feature | Status | Implementation Reference |
|---------|--------|--------------------------|
| Multi-Tenant Isolation | ✅ 100% | `QdrantVectorStore.search` payload filtering |
| Deep Immutability | ✅ 100% | `ExtractedDocument.__post_init__` |
| Contextual Retrieval | ✅ 100% | `ExtractionPipeline.process` situational Pass |
| Hybrid RRF Fusion | ✅ 100% | `HybridRetriever.fuse` |
| Agentic Quality Gates | ✅ 100% | `.gemini/skills/` custom skill suite |
| Tiered L3 Semantic Cache | ✅ 100% | `SemanticCache` (SSDataManager) |
| Unified MCP Orchestration| ✅ 100% | `MCPBridge` (Subprocess + Dynamic SQL) |
