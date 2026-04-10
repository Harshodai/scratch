# ADR-004: AWS SQS FIFO Queues over Celery Redis Workers

## Status
Accepted

## Context
CentRAG's document ingestion pipeline extracts, processes, and embeds massive files (PDFs, PPTs) simultaneously. 
Scaling these extraction workers via standard Python `Celery` + Redis architecture introduces scaling boundaries, Redis memory pressure limits, and complex state management in kubernetes topologies.

## Decision
We elected to use AWS SQS FIFO Queues coupled with Serverless consumers instead of standing up a Redis-backed Celery worker cluster.

## Consequences
1. **Pros:**
   - At-Least-Once Delivery semantics (may deliver duplicates; consumers must be idempotent) with Built-In Dead Letter Queue filtering natively decoupled from our infrastructure overhead.
   - SQS FIFO preserves the strict temporal generation sequence of chunks sequentially per MessageGroupId (e.g. mapping the base document UUID to the Group ID ensures hierarchical chunks are indexed in chronological order, critical for Parent-Child Document retrieval).
   - Massive reduction in infrastructure overhead and cluster sizing constraints.
2. **Cons:**
   - Vendor Lock-in (AWS).
   - Higher baseline latency between enqueuing jobs during development topologies compared to localized fast-path Redis queueing.
