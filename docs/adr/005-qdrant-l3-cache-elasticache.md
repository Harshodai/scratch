# ADR-005: Qdrant for L3 Semantic Cache

## Status
Accepted

## Context
CentRAG requires a robust, high-hit-ratio caching mechanism to minimize LLM compute costs and latency across identical or semantically identical queries.
While L1 (In-Memory) and L2 (Redis ElastiCache) can handle identical lexical matches, they fail to resolve semantically similar phrasing (e.g., "What is the policy?" vs. "Tell me the policy rules?").
ElastiCache alone does not natively support dense vector matching at the scale and speed necessary for our routing layer.

## Decision
We elected to utilize **Qdrant** as the execution backend for our L3 Semantic Cache layer. When queries generate dense embeddings, Qdrant will evaluate exact contextual drift bounds (threshold 0.95+) and inject matched high-fidelity cached payloads directly back up the stack.

## Consequences
1. **Pros:**
   - Massive suppression of downstream LLM Token Costs.
   - Unified maintenance (we already maintain Qdrant for core RAG).
2. **Cons:**
   - Adds secondary read traffic to the Qdrant cluster specifically for L3, requiring horizontal autoscaling logic on the `vdb` nodes.
