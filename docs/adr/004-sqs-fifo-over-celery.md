# ADR-004: AWS SQS FIFO Queues over Celery Redis Workers

## Status
Accepted

## Context
CentRAG's document ingestion pipeline extracts, processes, and embeds massive files (PDFs, PPTs) simultaneously. 
Scaling these extraction workers via standard Python `Celery` + Redis architecture introduces scaling boundaries, Redis memory pressure limits, and complex state management in kubernetes topologies.

## Decision
We elected to use AWS SQS FIFO Queues coupled with Serverless consumers instead of standing up an in-process Redis Celery worker cluster.

## Consequences
1. **Pros:**
   - Perfect At-Least-Once Delivery semantics with Built-In Dead Letter Queue filtering natively decoupled from our infrastructure overhead.
   - SQS FIFO preserves the strict temporal generation sequence of chunks (critical for Parent-Child Document retrieval strategies).
   - Massive reduction in infrastructure overhead and cluster sizing constraints.
2. **Cons:**
   - Vendor Lock-in (AWS).
   - Higher baseline latency between enqueuing jobs during development topologies compared to localized fast-path Redis queueing.
