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
- **Tiered Caching**: L1 (In-memory) → L2 (Redis) ensure sub-100ms response times for repeat queries.
- **LLM Gateway**: Implements **Circuit Breakers** and **Budget Gating** to prevent runaway cloud costs and cascade failures during provider outages.
- **AgentsView Integration**: Real-time export of session metadata to the AgentsView dashboard for deep-trace analysis of agent reasoning.
