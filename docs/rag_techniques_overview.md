# Overview of NirDiamant/RAG_Techniques

The `NirDiamant/RAG_Techniques` repository is an extensive, open-source educational hub that catalogs 34 distinct Retrieval-Augmented Generation (RAG) techniques, progressing from foundational strategies to advanced agentic architectures. 

The repository categorizes techniques into the following pillars:

## 1. Foundational RAG Techniques
- **Basic RAG**: Standard dense vector retrieval + generative response.
- **Optimizing Chunk Sizes / Proposition Chunking**: Formatting text before indexing for optimal meaning clustering.

## 2. Query Enhancement
- **Query Transformations**: Rewriting user queries to better match document vocabulary.
- **HyDE (Hypothetical Document Embedding)**: Utilizing an LLM to generate a synthetic response to the query, and searching the vector space using the embedding of that synthetic text.
- **HyPE (Hypothetical Prompt Embedding)**: Generating hypothetical prompts that would have led to the document.

## 3. Context Enrichment
- **Context Window Enhancement / Relevant Segment Extraction**: Retrieving surrounding context (parent/child chunking) or stripping noise from within chunks.
- **Semantic Chunking**: Using embedding similarities to chunk texts when topic drift occurs, rather than statically tokenizing.
- **Contextual Compression**: Using a secondary LLM/small model pass to extract only the sentences within a chunk that actually answer the query.

## 4. Advanced Retrieval
- **Fusion Retrieval**: Reciprocal Rank Fusion (RRF) combining keyword/sparse and dense vector spaces.
- **Multi-faceted Filtering**: Using LLMs to extract metadata filters (e.g. date, author) to restrict vector space searches.
- **Hierarchical Indices / RAPTOR**: Generating hierarchical tree models of documents, utilizing multi-level summarization.

## 5. Iterative Techniques (Agentic/Evaluation)
- **Corrective RAG (CRAG) & Self-RAG**: Utilizing LLM-as-a-judge patterns to evaluate retrieved documents. If the relevance is low, the system explicitly acts to expand scope through web searching or rewriting the query.
- **DeepEval / GroUSE**: Utilizing external frameworks for golden-dataset evaluation of generated responses metrics (Faithfulness, Context Relevance).
- **Agentic RAG / Graph RAG**: Utilizing Knowledge Graphs (e.g., Neo4j) or intelligent routing agents to perform multi-hop reasoning before retrieving data.

The overarching design pattern of the repository is modular, execution-independent scripts using `langchain` and `gpt-4o-mini`, providing high educational value but requiring architectural refactoring to be safe and performant for multi-tenant, SLA-bound production environments.
