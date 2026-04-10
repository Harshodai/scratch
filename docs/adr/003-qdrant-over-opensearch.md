# ADR-003: Qdrant over OpenSearch

## Status
Accepted

## Context
CentRAG requires a highly performant Vector Database capable of handling dense and sparse hybrid searches concurrently, coupled with severe RLS and multi-tenant partitioning logic. 
OpenSearch provides extensive traditional search analytics, whereas Qdrant is purpose-built as a Rust-native AI similarity search engine.

## Decision
We elected to use **Qdrant** instead of OpenSearch. 

## Consequences
1. **Pros:** 
   - Massive reduction in memory footprint compared to JVM-based OpenSearch.
   - Built-in `Prefetch` natively supports automated Reciprocal Rank Fusion (RRF), eliminating the need for python-side rank collation.
   - Rust-native vector primitives offer near real-time ingestion indexing latency.
2. **Cons:**
   - Lacks historical log analytics dashboards (Kibana). 
   - OpenSearch standard string queries (lucence format) are not supported.
