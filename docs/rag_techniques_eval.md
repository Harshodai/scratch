# RAG Techniques Evaluation & Gap Analysis

## 1. Understanding `NirDiamant/RAG_Techniques`
The repository is an extensive, modular catalogue documenting production-level and academic Retrieval-Augmented Generation (RAG) advancements. It emphasizes high-precision retrieval through advanced data conditioning, dynamic query manipulation, and autonomous post-retrieval validation. Key concepts include:

- **Query Transformations:** Using LLMs to modify the user's initial prompt (e.g., HyDE for hypothetical answers, Step-back Prompting for abstractions).
- **Advanced Chunking:** Proposition Chunking (breaking complex sentences into independent atomic facts) and Contextual Chunk Headers (injecting the document's global context into every micro-chunk).
- **Retrieval Orchestration:** Fusion Retrieval (RRF combining multiple ranking algorithms), Ensemble Retrieval, and Adaptive Retrieval (dynamic path routing).
- **Validation Loops:** Self-RAG (LLM critiques its own retrieval/generation) and CRAG (Corrective RAG - grading chunks and automatically rewriting queries if confidence is low).
- **Knowledge Integration:** Graph RAG (mapping entity relationships).

## 2. Gap Analysis: CentRAG vs. RAG_Techniques
CentRAG boasts a robust, production-hardened architecture with tiered caching (*L1 to L3*), namespace isolation, and dependency injection. However, an analysis reveals discrepancies between the RAG state-of-the-art and CentRAG's current module wiring:

| Technique | `RAG_Techniques` Implementation | CentRAG Current State | Gap/Opportunity |
|-----------|---------------------------------|-----------------------|-----------------|
| **Adaptive Retrieval** | LLM-based query routing. | Implemented via `QueryRouter` classifying queries using simple heuristics. | **Opportunity:** Enhance the heuristic classifier with LLM fallback for ambiguous queries. |
| **Hybrid Search (Fusion)**| BM25 + Dense vector with RRF. | Architecture mentions BM25 + Qdrant, but `engine.py` currently only executes Dense Search. | **Actionable Gap:** fully wire Qdrant BM25 sparse vectors alongside dense embeddings. |
| **Query Transformation (HyDE)**| Generates a hypothetical document before embedding. | Claimed in `ARCHITECTURE_HLD.md` but missing in `engine.py`. | **Actionable Gap:** Implement a `HyDEQueryTransformer` step before vector search. |
| **Corrective RAG (CRAG)** | Grader evaluates chunks. If bad, trigger a fallback mechanism. | Partially implemented: filters chunks based on Cohere Reranker confidence. | **Opportunity:** Implement an active fallback loop (query rewriting) when all chunks fail confidence checks. |
| **Proposition Chunking** | LLM decomposes text into atomic propositions. | Uses semantic/recursive/parent-child strategies. | **Opportunity/Risk:** Proposition extraction is highly precise but computationally prohibitive at scale. |
| **Self-RAG** | Active token-level critique loop during generation. | Not currently implemented within the main retrieval pipeline. | **Opportunity:** Excellent for long-form, complex queries, though too slow for synchronous API responses. |

## 3. Decision Matrix
Based on performance budgets, multi-tenant SLAs, and architectural constraints, the following decisions have been made for adopting techniques into CentRAG:

| Technique | Effort | Latency Impact | Decision | Reasoning |
|-----------|--------|----------------|----------|-----------|
| **Full Hybrid (Sparse + BM25)** | Medium | Low | **✅ Adopt** | Qdrant natively supports sparse vectors. Provides massive relevance boost for keyword queries with negligible latency overhead. |
| **CRAG (Active Query Rewrite)** | Low | Med *(Only when triggered)* | **✅ Adopt** | Significantly improves zero-result queries by automatically retrying failed searches with an expanded term, preventing frustrating "No documents found" errors. |
| **HyDE (Hypothetical Embeds)** | Medium | High *(1 extra LLM call)* | **✅ Adopt (Conditional)** | Useful for vague queries, but must be gated. We will implement it but only activate it for queries classified as `complex` by the Adaptive Router. |
| **Contextual Headers** | Low | Low | **✅ Adopt** | Easy to implement metadata enrichment during ingestion. Enhances semantic chunk isolation. |
| **Proposition Chunking** | High | High *(At Ingestion)* | **❌ Reject** | Too computationally expensive for a RAG-as-a-Service ingestion pipeline. The existing Semantic + Parent/Child strategies provide 80% of the value for 10% of the cost. |
| **Self-RAG (Critique Loop)** | High | Extremely High | **❌ Reject for Core API** | P95 latency guarantees (<3s) govern CentRAG. Multi-step LLM critiques violate this budget. It should only be utilized in specific background asynchronous Agent tasks. |
