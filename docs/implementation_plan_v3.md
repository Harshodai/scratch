# Production RAG Enhancement Implementation Plan

This orchestrated plan focuses strictly on integrating the defined approved targets from the `rag_techniques_decision.md` to harden CentRAG's query resolution without duplicating existing architecture.

## User Review Required
> [!IMPORTANT]
> The Multi-faceted Filter extraction requires introducing a new fast-LLM pass at the very beginning of the retrieve pipeline to evaluate metadata criteria before searching the Vector store. This will append roughly ~500ms to the `moderate` and `complex` P95 latencies. Please approve this latency budget adjustment before execution begins.

## 1. Feature: Sparse Vector Support (BM25 Hybrid Setup)
**Orchestrator Delegation**: `architecture-review` -> `subagent-driven-development`

### `centrag/abstractions/`
- [MODIFY] `embedder.py`: Introduce `SparseEmbedderProtocol` requiring `embed_sparse(text) -> dict[int, float]`.

### `centrag/implementations/`
- [NEW] `bm25_sparse_embedder.py`: Implement a deterministic fast BM25 tokenizer directly in-memory to yield dictionary term weights.
- [MODIFY] `qdrant_vectorstore.py`: Expand Qdrant upsert and search behaviors. Check if the initialized configuration contains a sparse vector implementation, and append keyword vectors to the payload natively to leverage Qdrant's internal hybrid fusion scoring.

## 2. Feature: Multi-Faceted Query Extraction
**Orchestrator Delegation**: `senior-fullstack`

### `centrag/abstractions/`
- [NEW] `query_transformer.py`: Define `QueryTransformerProtocol` that accepts a query and returns structured logic: a modified query string + a `VectorFilter` dataclass mapping metadata requirements.

### `centrag/implementations/`
- [NEW] `llm_query_extractor.py`: A prompt-engineered LLM implementation utilizing Structured Output chains to generate `{"optimized_query": "...", "filters": {...}}`.

### `centrag/retrieval/`
- [MODIFY] `engine.py`: Pre-pend the retrieval phase. Process the raw query through the `QueryTransformerProtocol` when appropriate, applying the returning constraints strictly against the `vectorstore.search()`.

## 3. Feature: SLA-Guarded CRAG Fallback Loop
**Orchestrator Delegation**: `senior-fullstack` -> `test-driven-development`

### `centrag/retrieval/`
- [MODIFY] `engine.py`: If the `Rerank` stage evaluates all `SourceChunk` instances beneath the acceptable `confidence_threshold`, intercept the workflow. Activate the new `QueryTransformerProtocol` sequentially with a `query_translation` prompt to generalize terms, and re-execute the Vector Search + RRF sequence one maximum time before resorting to the generic LLM "I don't know" fallback.

## 4. Hardening & Graph Documentation
**Orchestrator Delegation**: `harden` / `documentation-generation-doc-generate`
- [MODIFY] `CODE_FLOW.md`: Update step-by-step documentation detailing the Multi-faceted filter parsing and CRAG retry loops within `Asking a Question (Retrieval)`.
- [COMMAND] Run `python -m code_review_graph build --repo .` to index the new logic patterns under the structural mapping, adhering to `AGENTS.md` rules.
