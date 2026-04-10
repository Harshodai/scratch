# ADR-006: Temporal Memory Versioning 

## Status
Accepted

## Context
Multi-tenant enterprise RAG solutions require a conversational memory that accurately surfaces state without destructively mutating historical logs. 
If an agent learns that Team A's contact is "Bob", and a week later it learns the contact is "Alice", simply overwriting "Bob" destroys rollback fidelity and context resolution.

## Decision
We elected to implement a **Temporal Memory Strategy** (Zep/Graphiti Pattern). Memory entries are structurally immutable. When a fact changes, the newer entry simply asserts dominance via `valid_to`/`superseded_by` pointer links bounding the lifetime of the previous fact matrix.

## Consequences
1. **Pros:**
   - Audit-grade transactional histories of fact adjustments.
   - Decoupled TTL logic enables seamless query routing bounding context by timestamp ranges.
2. **Cons:**
   - Memory queries must traverse pointer-graphs internally to resolve the current active state.
   - Higher row persistence counts in PostgreSQL.
