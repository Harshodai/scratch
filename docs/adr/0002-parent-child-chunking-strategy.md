# 0002. Parent-Child Chunking Strategy

Date: 2026-04-10

## Status
Accepted

## Context
Standard RAG systems often chunk documents cleanly (e.g. 512 tokens). However, using the same text for both *semantic vector retrieval* and *LLM context window insertion* yields conflicting incentives. Smaller chunks (< 256 tokens) yield incredibly high vector cosine-similarity precision. Large chunks (> 1024 tokens) provide the LLM enough surrounding prose to answer questions comprehensively without hallucinating.

## Decision
We implemented a Parent-Child (Hierarchical) Chunking strategy inside `centrag/extraction/chunkers/parent_child.py`. 
- The document is first segmented into larger "Parent" blocks (e.g., 1024 tokens).
- Each Parent is then sub-divided into smaller "Child" vectors (e.g., 256 tokens).
- The vector database indexes *only* the embeddings of the Child chunks but returns the raw text of their associated Parent chunk.

## Consequences
- **Positive:** Significantly improves precise matching without discarding vital contextual context for the final generation phase. Reduces prompt starvation.
- **Negative:** Doubles the complexity of indexing and complicates the relational integrity logic within our storage components. Increases document upload pipeline latency.
