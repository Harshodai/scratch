# Master Integration Decision Matrix

Following a thorough evaluation of the 34 advanced parameters from `RAG_Techniques` and applying CentRAG's non-negotiable performance SLAs (<3s P95 latency) and Enterprise constraints, here are the decisions on what gaps to integrate.

## 🔴 Rejected Strategies
1. **HyDE / HyPE**: B2B Enterprise teams require absolute ground-truth factual context. Generative hypothetical expansion prior to the search heavily risks mutating domain-specific phrasing into generic hallucinated vectors. 
2. **Contextual Compression & Selective Segments**: Appending a secondary LLM pipeline dynamically during the synchronous `retrieve` event to rewrite chunk excerpts breaches our latency budget and increases token cost significantly.
3. **Graph RAG**: Highly scalable but requires migrating deployment topologies to incorporate graph databases (Neo4J), destroying current EKS deployment models.

## 🟢 Approved Integration Targets

### 1. Multi-faceted Query Filtering (Query Enhancement)
* **Rationale**: Enterprise datasets possess heavy metadata (`author`, `date`, `category`). Providing an agentic `QueryTransformer` that extracts JSON payloads (`{"query": "revenue", "filters": {"year": 2024}}`) unlocks deterministic filtering prior to vectoring.

### 2. BM25 Sparse Embedder (Fusion Retrieval)
* **Rationale**: CentRAG manages an RRF `HybridRetriever`, but relying exclusively on Dense embeddings + PageIndex weakens exact-keyword lookups (like an exact SKU ID or Product Code). Building a local `SparseEmbedderProtocol` (mapped to Qdrant's sparse vector capability) solves keyword matching perfectly without breaking latency APIs.

### 3. Local CRAG Fallback Loop (Iterative Retrieval)
* **Rationale**: CentRAG evaluates confidence via `RerankerProtocol`, but fails immediately if confidence drops. We will implement `QueryRewriter` logic: if the initial retrieval yields no confident chunks, CentRAG dynamically rewrites the query using abstract synonyms and attempts *one* local re-fetch against Qdrant, recovering from poor user prompting without breaching namespace privacy (rejecting DDG searches).
