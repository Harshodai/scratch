# CentRAG Evaluation Guide

This guide covers the complete RAG evaluation framework — retrieval metrics, generation metrics, end-to-end evaluation, failure tracking, and advanced chunking strategies.

> **Quick Links:**
> - [Architecture & Design](ARCHITECTURE_HLD.md)
> - [Code Flow & Method Signatures](CODE_FLOW.md)
> - [Engineering Decisions](ENGINEERING_DECISIONS.md)
> - [Maintenance Rituals](MAINTENANCE.md)

---

## Overview

CentRAG's evaluation system is structured in **three layers**:

```
┌────────────────────────────────────────────────────────┐
│  Layer 1: RETRIEVAL EVALUATION                         │
│  Did we find the right documents?                      │
│  Metrics: Precision@K, Recall@K, MRR, NDCG@K, F1@K   │
├────────────────────────────────────────────────────────┤
│  Layer 2: GENERATION EVALUATION                        │
│  Did we generate a correct answer?                     │
│  Judges: Faithfulness, Relevance, Hallucination,       │
│          Coverage, Contextual Precision/Recall          │
├────────────────────────────────────────────────────────┤
│  Layer 3: END-TO-END EVALUATION                        │
│  Did the user get a good experience?                   │
│  Metrics: Task Success Rate, Human Feedback, Latency   │
└────────────────────────────────────────────────────────┘
```

---

## 1. Retrieval Evaluation (Layer 1)

These metrics measure retrieval quality **independently** from generation quality. A perfect LLM cannot compensate for a broken retriever.

### Available Metrics

| Metric | What It Measures | File |
|:---|:---|:---|
| **Precision@K** | What fraction of top-K retrieved docs are relevant? | `evaluation/metrics.py` |
| **Recall@K** | What fraction of all relevant docs appear in top-K? | `evaluation/metrics.py` |
| **MRR** | How high does the first relevant doc appear? | `evaluation/metrics.py` |
| **NDCG@K** | Are relevant docs ranked higher than irrelevant ones? | `evaluation/metrics.py` |
| **F1@K** | Harmonic mean of Precision@K and Recall@K | `evaluation/metrics.py` |

### Usage

```python
from centrag.evaluation.metrics import precision_at_k, recall_at_k, mean_reciprocal_rank

retrieved = ["doc-1", "doc-5", "doc-3", "doc-7"]
relevant = {"doc-1", "doc-3"}

precision_at_k(retrieved, relevant, k=5)   # → 0.5
recall_at_k(retrieved, relevant, k=5)      # → 1.0
mean_reciprocal_rank(retrieved, relevant)   # → 1.0 (doc-1 is first)
```

### Path Comparison

Use `PathComparator` to compare retrieval paths side-by-side:

```python
from centrag.evaluation.comparator import PathComparator

comp = PathComparator()
comp.add_result("pageindex", composite=0.9, faithfulness=0.85, latency_ms=200)
comp.add_result("vector", composite=0.7, faithfulness=0.65, latency_ms=50)
result = comp.compare()
print(result.winner_overall)  # → "pageindex"
```

---

## 2. Generation Evaluation (Layer 2)

### Heuristic Judges (Fast, Deterministic)

| Judge | What It Checks | Cost |
|:---|:---|:---|
| `FaithfulnessJudge` | Are answer claims supported by sources? (word-overlap) | Free |
| `RelevanceJudge` | Does the answer address the query? (word-overlap) | Free |
| `CoverageJudge` | Does the answer cover expected key facts? | Free |

### DeepEval LLM Judges (Accurate, LLM-backed)

| Judge | What It Checks | Cost |
|:---|:---|:---|
| `DeepEvalFaithfulnessJudge` | NLI-based claim verification | 1 LLM call |
| `DeepEvalRelevanceJudge` | Semantic relevance scoring | 1 LLM call |
| `DeepEvalHallucinationJudge` | Fabricated fact detection | 1 LLM call |
| `DeepEvalContextualPrecisionJudge` | Are retrieved chunks relevant? | 1 LLM call |
| `DeepEvalContextualRecallJudge` | Were all needed chunks retrieved? | 1 LLM call |

### Why DeepEval?

| Framework | Strength | Weakness |
|:---|:---|:---|
| **DeepEval** ✅ | Pytest-native, CI/CD gates, component-level debugging | Requires LLM API key |
| RAGAS | Research-backed RAG metrics | Metrics-only, no test infra |
| LangSmith | Full observability platform | Vendor lock-in to LangChain |

### Installation

```bash
pip install "centrag[dev]"  # Includes deepeval>=1.4.0 and ragas>=0.2.0
```

### Running DeepEval Tests

```bash
# Standard pytest (heuristic judges only)
make test

# DeepEval with LLM scoring (requires OPENAI_API_KEY or equivalent)
deepeval test run tests/test_deepeval_rag.py
```

---

## 3. End-to-End Evaluation (Layer 3)

### Task Success Rate

### Evaluation Runner (Orchestration)

The `EvaluationRunner` is the easiest way to run a full sweep. It automatically handles retrieval, judging, scoring, and failure recording.

```python
from centrag.evaluation import EvaluationRunner, GoldenDataset

# 1. Load dataset & engine
dataset = GoldenDataset.sample_dataset()
engine = container.retrieval_engine

# 2. Run heuristic evaluation (Fast, Free)
runner = EvaluationRunner(engine, dataset)
report = await runner.run()

# 3. Run with DeepEval (Accurate, Requires LLM API Key)
runner_llm = EvaluationRunner.with_deepeval(engine, dataset)
report_llm = await runner_llm.run()

print(f"Pass rate: {report.pass_rate:.1%}")
```

### API-Driven Evaluation

You can trigger a full evaluation sweep via the `/v1/evaluate` endpoint. This is ideal for CI/CD gates or dashboard integration.

**Endpoint:** `POST /v1/evaluate`

**Payload:**
```json
{
  "team_id": "eval-harness",
  "use_deepeval": false,
  "max_cases": 10
}
```

**Workflow:**
1. Upload documents via `/v1/documents`.
2. Trigger evaluation via `/v1/evaluate`.
3. Check `failure_summary` in the response to identify retrieval misses or hallucinations.

### Human Feedback

Feedback is collected via `POST /v1/feedback`:

```json
{
  "query": "What are the key risks?",
  "answer": "The key risks include...",
  "score": 1,
  "comments": "Accurate and well-sourced"
}
```

---

## 4. Failure Case Storage

Failed evaluation cases are automatically classified and stored for debugging and continuous improvement.

### Failure Categories

| Category | Root Cause | Remediation |
|:---|:---|:---|
| `retrieval_miss` | Relevant docs not found | Improve embeddings, add BM25 sparse search |
| `hallucination` | LLM fabricated facts | Tighten faithfulness guardrails |
| `off_topic` | Answer doesn't address query | Improve query routing |
| `low_coverage` | Missing key facts | Add source documents, improve chunking |
| `latency_exceeded` | Response too slow (>10s) | Optimize caching, reduce reranking scope |
| `guardrail_block` | PII/safety filter triggered | Review guardrail thresholds |

### Usage

```python
from centrag.evaluation.failure_store import FailureStore

store = FailureStore(output_dir="evaluate/reports")

for result in metrics.failed_results:
    store.add_from_result(result)

store.save()       # → evaluate/reports/failures.json
print(store.summary())
```

### Database Persistence

For production analysis, failures are also stored in the `evaluation_failures` PostgreSQL table (team-scoped with RLS).

---

## 5. Chunking Strategies

| Strategy | File | Best For |
|:---|:---|:---|
| Fixed | `chunkers/fixed.py` | Uniform token-budget control |
| Recursive | `chunkers/recursive.py` | General-purpose (default) |
| Semantic | `chunkers/semantic.py` | Topic-shift-aware splitting |
| Proposition | `chunkers/proposition.py` | Atomic fact extraction |
| Structure-Aware | `chunkers/structure_aware.py` | HTML/Markdown-respect |
| Hierarchical | `chunkers/hierarchical.py` | Multi-level context expansion |
| Parent-Child | `chunkers/parent_child.py` | Small search + large context |
| **Contextual Chunk Embedding** | `chunkers/late_chunking.py` | Cross-chunk context preservation (approx. late chunking) |

### Contextual Chunk Embedding (Approximate Late Chunking)

Standard chunking loses cross-chunk context. This strategy prepends a document-level summary to each chunk before embedding, so the resulting vector captures global document context.

> **Note:** This is NOT true Late Chunking (Jina AI, 2024), which requires per-token embeddings from a long-context model. Most API-based embedding models don't expose per-token representations, so we approximate the benefit using contextual prefixing.

```python
from centrag.extraction.chunkers.late_chunking import LateChunker

chunker = LateChunker(embed_fn=embedder.embed_documents)
chunks, embeddings = await chunker.chunk_with_embeddings(text)
# Each chunk is prefixed with document summary before embedding
```

---

## 6. Hybrid Retrieval Stack

```
Query → QueryRouter → [PageIndex | Vector | Hybrid]
                              ↓
                        HybridRetriever (RRF, k=60)
                              ↓
                        CohereReranker (Cross-Encoder)
                              ↓
                        CRAG Confidence Gate
                              ↓
                        TwoPassGenerator
```

### Key Components

| Component | File | Role |
|:---|:---|:---|
| `QueryRouter` | `retrieval/query_router.py` | Auto-routes to best path |
| `HybridRetriever` | `retrieval/hybrid.py` | RRF fusion of dual paths |
| `BM25SparseEmbedder` | `implementations/bm25_sparse_embedder.py` | Lexical sparse vectors |
| `FlashRankReranker` | `implementations/flashrank_reranker.py` | Local cross-encoder (free, no API key) |
| `CohereReranker` | `implementations/cohere_reranker.py` | API cross-encoder (free trial: 1K calls/mo) |
| `NoOpReranker` | `implementations/noop_reranker.py` | Dev fallback (keyword overlap) |

### Reranker Selection Hierarchy

The wiring module (`wiring.py`) auto-selects the best available reranker:

```
CENTRAG_COHERE_API_KEY set?  →  CohereReranker (best quality, API)
flashrank installed?          →  FlashRankReranker (good quality, free)
fallback                      →  NoOpReranker (keyword heuristic)
```

**Enabling FlashRank** (recommended for dev/CI):
```bash
pip install flashrank  # ~4 MB model, auto-downloads on first use
```

**Enabling Cohere** (recommended for production):
Sign up at [cohere.com](https://cohere.com) for a free trial key (no credit card). Set:
```bash
export CENTRAG_COHERE_API_KEY=co-...
```

---

## Running Evaluation

```bash
# Unit tests (deterministic, no LLM)
make test

# Full quality gate (test + lint + security)
make audit

# DeepEval with LLM scoring
deepeval test run tests/test_deepeval_rag.py

# Generate failure report
python -m centrag.evaluation.runner --output evaluate/reports/
```
