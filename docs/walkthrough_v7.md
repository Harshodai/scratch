# CentRAG Production Hardening — Walkthrough

## Summary

Completed a 3-phase production hardening of the CentRAG platform, transforming it from a "beautifully architected but non-runnable" system into a fully wired, testable, end-to-end RAG pipeline.

---

## Phase 1: Make It Run

### 1.1 NoOp Implementations
Created `centrag/implementations/` package with 4 concrete protocol implementations:

| File | Protocol | Strategy |
|------|----------|----------|
| [noop_embedder.py](file:///c:/Users/khars/PycharmProjects/scratch/centrag/implementations/noop_embedder.py) | `EmbedderProtocol` | Deterministic hash-seeded random vectors, unit-normalized |
| [noop_vectorstore.py](file:///c:/Users/khars/PycharmProjects/scratch/centrag/implementations/noop_vectorstore.py) | `VectorStoreProtocol` | In-memory dict + brute-force cosine similarity |
| [noop_llm.py](file:///c:/Users/khars/PycharmProjects/scratch/centrag/implementations/noop_llm.py) | `LLMProtocol` | Template-based generation + heuristic complexity classification |
| [noop_reranker.py](file:///c:/Users/khars/PycharmProjects/scratch/centrag/implementations/noop_reranker.py) | `RerankerProtocol` | Keyword overlap scoring |

> [!IMPORTANT]
> These are **deterministic** — same input always produces the same output. This makes tests reproducible without mocking.

### 1.2 App Lifespan Wiring
Rewrote [app.py](file:///c:/Users/khars/PycharmProjects/scratch/centrag/app.py) lifespan to:
- Initialize Postgres, Redis, Qdrant clients **in parallel** (`asyncio.gather`)
- **Graceful fallback** — if any service is down in dev, log a warning and continue
- Build the `RetrievalEngine` via the composition root and attach to `app.state`

### 1.3 Composition Root
Created [wiring.py](file:///c:/Users/khars/PycharmProjects/scratch/centrag/wiring.py) — the **single place** where concrete implementations are selected:
- Embedder → `NoOpEmbedder(dim=1024)`
- VectorStore → `NoOpVectorStore()`
- LLM → `NoOpLLM(model_name="noop-llm-v1")`
- Reranker → `NoOpReranker()`
- Cache → `TieredCacheOrchestrator([L1, L2])`
- Memory → `InMemoryStore()`
- Guardrails → `GuardrailEngine(default_config)`

Wired [retrieve route](file:///c:/Users/khars/PycharmProjects/scratch/centrag/routes/retrieve.py) via FastAPI dependency injection from `app.state`.

### 1.4 Legacy Cleanup
Deleted `guardrails_legacy.py` — redundant after the `guardrails/` package was verified.

---

## Phase 2: Bug Fixes

### 2.1 SemanticChunker Deadlock
**Bug**: `chunk()` called `loop.run_in_executor(pool, lambda: asyncio.run(...))` which returns a coroutine, not a result — causing the async caller to hang.

**Fix**: Use `pool.submit(asyncio.run, coro)` + `future.result()` in a dedicated `ThreadPoolExecutor(max_workers=1)` when already inside an event loop.

```diff:semantic.py
"""
Semantic chunker — embedding-based boundary detection.

Splits documents at points where the topic shifts, detected by
measuring embedding similarity between adjacent sentences.

This is HIGHER QUALITY but SLOWER than recursive chunking because
it requires calling the embedding model for every sentence.

Design: STRATEGY PATTERN leaf — implements ChunkerProtocol.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Awaitable

from centrag.abstractions.chunker import (
    ChunkingConfig,
    ChunkingStrategy,
    ChunkResult,
    ChunkerProtocol,
)


def _split_into_sentences(text: str) -> list[str]:
    """Split text into sentences using regex."""
    sentences = re.split(r'(?<=[.!?])\s+', text)
    return [s.strip() for s in sentences if s.strip()]


def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    if not vec_a or not vec_b:
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = sum(a * a for a in vec_a) ** 0.5
    norm_b = sum(b * b for b in vec_b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class SemanticChunker:
    """
    Split documents at semantic boundaries.

    Algorithm:
      1. Split text into sentences
      2. Embed each sentence
      3. For each adjacent pair, compute cosine similarity
      4. When similarity drops below threshold → insert boundary
      5. Group sentences between boundaries into chunks

    Requires an embedding function to be injected — this keeps the
    chunker decoupled from any specific embedding provider.
    """

    def __init__(
        self,
        embed_fn: Callable[[list[str]], Awaitable[list[list[float]]]],
    ) -> None:
        """
        Args:
            embed_fn: Async function that embeds a list of strings.
                      Injected from the EmbedderProtocol implementation.
                      Signature: async (texts: list[str]) -> list[list[float]]
        """
        self._embed_fn = embed_fn

    @property
    def strategy(self) -> ChunkingStrategy:
        return ChunkingStrategy.SEMANTIC

    def chunk(
        self,
        text: str,
        config: ChunkingConfig | None = None,
        document_title: str = "",
        section_headers: list[str] | None = None,
    ) -> list[ChunkResult]:
        """
        Synchronous interface — wraps the async implementation.

        NOTE: In practice, call chunk_async() directly from async code.
        This sync wrapper exists to satisfy ChunkerProtocol's interface.
        """
        import asyncio

        try:
            loop = asyncio.get_running_loop()
            # Already in async context — create a task
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return loop.run_in_executor(
                    pool,
                    lambda: asyncio.run(
                        self.chunk_async(text, config, document_title, section_headers)
                    ),
                )  # type: ignore
        except RuntimeError:
            # No running loop — safe to use asyncio.run
            return asyncio.run(
                self.chunk_async(text, config, document_title, section_headers)
            )

    async def chunk_async(
        self,
        text: str,
        config: ChunkingConfig | None = None,
        document_title: str = "",
        section_headers: list[str] | None = None,
    ) -> list[ChunkResult]:
        """Async semantic chunking — the real implementation."""
        cfg = config or ChunkingConfig(strategy=ChunkingStrategy.SEMANTIC)

        sentences = _split_into_sentences(text)
        if len(sentences) <= 1:
            return [
                ChunkResult(
                    content=text,
                    chunk_index=0,
                    start_char=0,
                    end_char=len(text),
                    token_count=int(len(text.split()) * 1.3),
                    metadata={"strategy": "semantic"},
                )
            ] if text.strip() else []

        # Embed all sentences
        embeddings = await self._embed_fn(sentences)

        # Find semantic boundaries
        boundaries: list[int] = [0]
        for i in range(len(embeddings) - 1):
            sim = _cosine_similarity(embeddings[i], embeddings[i + 1])
            if sim < cfg.similarity_threshold:
                boundaries.append(i + 1)
        boundaries.append(len(sentences))

        # Group sentences between boundaries
        results: list[ChunkResult] = []
        current_pos = 0

        for idx in range(len(boundaries) - 1):
            start_idx = boundaries[idx]
            end_idx = boundaries[idx + 1]
            chunk_sentences = sentences[start_idx:end_idx]
            chunk_text = " ".join(chunk_sentences)

            # Skip if too small
            if len(chunk_text.split()) < int(cfg.min_chunk_size * 0.75):
                continue

            # Truncate if too large
            words = chunk_text.split()
            max_words = int(cfg.max_chunk_size * 0.75)
            if len(words) > max_words:
                chunk_text = " ".join(words[:max_words])

            # Context enrichment
            prefix_parts: list[str] = []
            if cfg.prepend_title and document_title:
                prefix_parts.append(f"[Document: {document_title}]")
            if cfg.prepend_headers and section_headers:
                prefix_parts.append(f"[Section: {' > '.join(section_headers)}]")

            enriched = chunk_text
            if prefix_parts:
                enriched = " ".join(prefix_parts) + "\n" + chunk_text

            start_char = text.find(chunk_sentences[0], current_pos)
            if start_char < 0:
                start_char = current_pos
            end_char = start_char + len(chunk_text)

            results.append(
                ChunkResult(
                    content=enriched,
                    chunk_index=len(results),
                    start_char=start_char,
                    end_char=end_char,
                    token_count=int(len(chunk_text.split()) * 1.3),
                    metadata={
                        "strategy": "semantic",
                        "boundary_similarity": cfg.similarity_threshold,
                        "document_title": document_title,
                    },
                )
            )
            current_pos = end_char

        return results

    def chunk_boundaries(
        self,
        text: str,
        config: ChunkingConfig | None = None,
    ) -> list[tuple[int, int]]:
        results = self.chunk(text, config)
        return [r.boundary for r in results]
===
"""
Semantic chunker — embedding-based boundary detection.

Splits documents at points where the topic shifts, detected by
measuring embedding similarity between adjacent sentences.

This is HIGHER QUALITY but SLOWER than recursive chunking because
it requires calling the embedding model for every sentence.

Design: STRATEGY PATTERN leaf — implements ChunkerProtocol.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Awaitable

from centrag.abstractions.chunker import (
    ChunkingConfig,
    ChunkingStrategy,
    ChunkResult,
    ChunkerProtocol,
)


def _split_into_sentences(text: str) -> list[str]:
    """Split text into sentences using regex."""
    sentences = re.split(r'(?<=[.!?])\s+', text)
    return [s.strip() for s in sentences if s.strip()]


def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    if not vec_a or not vec_b:
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = sum(a * a for a in vec_a) ** 0.5
    norm_b = sum(b * b for b in vec_b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class SemanticChunker:
    """
    Split documents at semantic boundaries.

    Algorithm:
      1. Split text into sentences
      2. Embed each sentence
      3. For each adjacent pair, compute cosine similarity
      4. When similarity drops below threshold → insert boundary
      5. Group sentences between boundaries into chunks

    Requires an embedding function to be injected — this keeps the
    chunker decoupled from any specific embedding provider.
    """

    def __init__(
        self,
        embed_fn: Callable[[list[str]], Awaitable[list[list[float]]]],
    ) -> None:
        """
        Args:
            embed_fn: Async function that embeds a list of strings.
                      Injected from the EmbedderProtocol implementation.
                      Signature: async (texts: list[str]) -> list[list[float]]
        """
        self._embed_fn = embed_fn

    @property
    def strategy(self) -> ChunkingStrategy:
        return ChunkingStrategy.SEMANTIC

    def chunk(
        self,
        text: str,
        config: ChunkingConfig | None = None,
        document_title: str = "",
        section_headers: list[str] | None = None,
    ) -> list[ChunkResult]:
        """
        Synchronous interface — wraps the async implementation.

        WARNING: Only works when called OUTSIDE an async event loop.
        From async code (e.g., ExtractionPipeline.process()), call
        chunk_async() directly instead.
        """
        import asyncio

        try:
            asyncio.get_running_loop()
            # Already in async context — cannot use asyncio.run().
            # Run in a dedicated thread with its own event loop.
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(
                    asyncio.run,
                    self.chunk_async(text, config, document_title, section_headers),
                )
                return future.result()
        except RuntimeError:
            # No running loop — safe to use asyncio.run
            return asyncio.run(
                self.chunk_async(text, config, document_title, section_headers)
            )

    async def chunk_async(
        self,
        text: str,
        config: ChunkingConfig | None = None,
        document_title: str = "",
        section_headers: list[str] | None = None,
    ) -> list[ChunkResult]:
        """Async semantic chunking — the real implementation."""
        cfg = config or ChunkingConfig(strategy=ChunkingStrategy.SEMANTIC)

        sentences = _split_into_sentences(text)
        if len(sentences) <= 1:
            return [
                ChunkResult(
                    content=text,
                    chunk_index=0,
                    start_char=0,
                    end_char=len(text),
                    token_count=int(len(text.split()) * 1.3),
                    metadata={"strategy": "semantic"},
                )
            ] if text.strip() else []

        # Embed all sentences
        embeddings = await self._embed_fn(sentences)

        # Find semantic boundaries
        boundaries: list[int] = [0]
        for i in range(len(embeddings) - 1):
            sim = _cosine_similarity(embeddings[i], embeddings[i + 1])
            if sim < cfg.similarity_threshold:
                boundaries.append(i + 1)
        boundaries.append(len(sentences))

        # Group sentences between boundaries
        results: list[ChunkResult] = []
        current_pos = 0

        for idx in range(len(boundaries) - 1):
            start_idx = boundaries[idx]
            end_idx = boundaries[idx + 1]
            chunk_sentences = sentences[start_idx:end_idx]
            chunk_text = " ".join(chunk_sentences)

            # Skip if too small
            if len(chunk_text.split()) < int(cfg.min_chunk_size * 0.75):
                continue

            # Truncate if too large
            words = chunk_text.split()
            max_words = int(cfg.max_chunk_size * 0.75)
            if len(words) > max_words:
                chunk_text = " ".join(words[:max_words])

            # Context enrichment
            prefix_parts: list[str] = []
            if cfg.prepend_title and document_title:
                prefix_parts.append(f"[Document: {document_title}]")
            if cfg.prepend_headers and section_headers:
                prefix_parts.append(f"[Section: {' > '.join(section_headers)}]")

            enriched = chunk_text
            if prefix_parts:
                enriched = " ".join(prefix_parts) + "\n" + chunk_text

            start_char = text.find(chunk_sentences[0], current_pos)
            if start_char < 0:
                start_char = current_pos
            end_char = start_char + len(chunk_text)

            results.append(
                ChunkResult(
                    content=enriched,
                    chunk_index=len(results),
                    start_char=start_char,
                    end_char=end_char,
                    token_count=int(len(chunk_text.split()) * 1.3),
                    metadata={
                        "strategy": "semantic",
                        "boundary_similarity": cfg.similarity_threshold,
                        "document_title": document_title,
                    },
                )
            )
            current_pos = end_char

        return results

    def chunk_boundaries(
        self,
        text: str,
        config: ChunkingConfig | None = None,
    ) -> list[tuple[int, int]]:
        results = self.chunk(text, config)
        return [r.boundary for r in results]
```

### 2.2 Cache Serialization
**Bug**: `RetrievalResponse` (frozen dataclass with nested dataclasses + enums) was passed to `json.dumps(value, default=str)`, producing garbled data that couldn't be deserialized.

**Fix**: Added `to_dict()`/`from_dict()` methods to `RetrievalResponse`. Cache write serializes via `to_dict()`, cache read reconstructs via `from_dict()` (with `isinstance(value, dict)` check so L1 Python objects still work).

```diff:engine.py
"""
Retrieval Engine — The core RAG pipeline.

┌─────────────────────────────────────────────────────────────────────┐
│  Design Patterns Used:                                              │
│                                                                     │
│  1. CHAIN OF RESPONSIBILITY (Middleware Pipeline)                   │
│     Cache Check → Retrieve → Rerank → Validate → Generate          │
│     Each step can short-circuit (cache hit skips retrieval)         │
│                                                                     │
│  2. STRATEGY PATTERN (Swappable components)                        │
│     Embedder, VectorStore, Reranker, LLM — all injected via DI     │
│                                                                     │
│  3. TEMPLATE METHOD (retrieve flow)                                │
│     The pipeline steps are fixed, but each step's implementation   │
│     is swappable via Protocol abstractions                         │
│                                                                     │
│  RAG Advancements Applied:                                         │
│  - Adaptive Retrieval: classify_complexity → route to right model  │
│  - Corrective RAG (CRAG): validate retrieved chunks, rewrite if    │
│    confidence is too low                                           │
│  - Hybrid Search: dense + sparse (BM25) with RRF fusion           │
│                                                                     │
│  Agentic Patterns Applied:                                         │
│  - ReAct: reason about query → act (retrieve) → observe results   │
│  - Reflection: check if retrieved context is sufficient            │
│  - Tool Use: retrieval engine is itself a "tool" for agents        │
└─────────────────────────────────────────────────────────────────────┘
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable, List

import structlog

from centrag.abstractions import (
    CacheProtocol,
    EmbedderProtocol,
    LLMProtocol,
    MemoryProtocol,
    RerankerProtocol,
    VectorStoreProtocol,
)
from centrag.abstractions.cache import CacheResult, CacheTier
from centrag.abstractions.llm import LLMResponse, QueryComplexity
from centrag.abstractions.guardrail import (
    InputRailProtocol,
    OutputRailProtocol,
    RailContext,
    GuardrailViolation,
)
from centrag.abstractions.vectorstore import VectorFilter
from centrag.middleware import RequestContext
import time

logger = structlog.get_logger()


# =============================================================================
# Request / Response DTOs (Immutable)
# =============================================================================


@dataclass(frozen=True)
class RetrievalRequest:
    """Immutable retrieval request."""

    query: str
    namespace: str = "default"
    max_results: int = 5
    include_memory: bool = True
    include_sources: bool = True
    mode: str = "rag"  # "rag" | "full_context" (NotebookLM-style for small docs)


@dataclass(frozen=True)
class SourceChunk:
    """A retrieved source chunk with citation metadata."""

    content: str
    document_id: str
    chunk_index: int
    relevance_score: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RetrievalResponse:
    """Immutable retrieval response."""

    answer: str
    sources: list[SourceChunk]
    cache_tier: CacheTier
    query_complexity: QueryComplexity
    llm_response: LLMResponse | None = None
    memory_context: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

# =============================================================================
# Agentic Design Patterns
# =============================================================================

class TokenBudgetManager:
    """
    Agentic Context Compression (Pattern 8).
    Dynamically tracks the context building window to prevent API truncation limits.
    """
    def __init__(self, max_budget: int = 3000):
        self.max_budget = max_budget
        
    def fit_context(self, sources: list[SourceChunk]) -> list[SourceChunk]:
        fitted = []
        current_cost = 0.0
        for chunk in sources:
            cost = len(chunk.content.split()) * 1.3 # simple estimation
            if current_cost + cost <= self.max_budget:
                fitted.append(chunk)
                current_cost += cost
            else:
                break
        return fitted


# =============================================================================
# Retrieval Engine
# =============================================================================


class RetrievalEngine:
    """
    Core RAG pipeline with Adaptive + Corrective RAG patterns.

    SOLID: Single Responsibility — orchestrates retrieval, doesn't implement any component.
           Guardrails are INJECTED, not called inline. This class only sequences steps.
    SOLID: Dependency Inversion — depends on Protocols, not concrete classes.
    SOLID: Open/Closed — add new retrieval strategies without modifying this class.

    All dependencies are injected via __init__ (constructor injection).
    """

    def __init__(
        self,
        embedder_factory: Callable[[], EmbedderProtocol],
        vectorstore_factory: Callable[[], VectorStoreProtocol],
        reranker_factory: Callable[[], RerankerProtocol],
        llm_factory: Callable[[], LLMProtocol],
        cache: CacheProtocol,
        memory: MemoryProtocol | None = None,
        input_rails: list[InputRailProtocol] | None = None,
        output_rails: list[OutputRailProtocol] | None = None,
    ) -> None:
        # Pattern 3: Pervasive Lazy Loading
        # SDKs (boto3, transformers) only initialize when their property is first accessed.
        self._embedder_factory = embedder_factory
        self._vectorstore_factory = vectorstore_factory
        self._reranker_factory = reranker_factory
        self._llm_factory = llm_factory
        self._cache = cache
        self._memory = memory
        self._input_rails = input_rails or []
        self._output_rails = output_rails or []

        self.__embedder = None
        self.__vectorstore = None
        self.__reranker = None
        self.__llm = None

        self.budget_manager = TokenBudgetManager()

    @property
    def _embedder(self) -> EmbedderProtocol:
        if not self.__embedder: self.__embedder = self._embedder_factory()
        return self.__embedder
        
    @property
    def _vectorstore(self) -> VectorStoreProtocol:
        if not self.__vectorstore: self.__vectorstore = self._vectorstore_factory()
        return self.__vectorstore
        
    @property
    def _reranker(self) -> RerankerProtocol:
        if not self.__reranker: self.__reranker = self._reranker_factory()
        return self.__reranker
        
    @property
    def _llm(self) -> LLMProtocol:
        if not self.__llm: self.__llm = self._llm_factory()
        return self.__llm

    async def retrieve(
        self,
        request: RetrievalRequest,
        ctx: RequestContext,
    ) -> RetrievalResponse:
        """
        Main retrieval pipeline.

        Flow (Chain of Responsibility):
        0. GUARDRAILS: Validate input query (schema, pii, prompt injection)
        1. ADAPTIVE: Classify query complexity
        2. CACHE: Check tiered cache (L1 → L2 → L3)
        3. RETRIEVE: Dense vector search (+ sparse BM25 in future)
        4. RERANK: Score chunks by relevance
        5. VALIDATE (CRAG): Check confidence — rewrite if too low
        6. MEMORY: Inject relevant memories into context
        7. GENERATE: LLM produces answer with citations
        8. GUARDRAILS: Validate response, redact PII
        9. REPORT: Audit trail with latency + cost tracking
        10. CACHE WRITE: Store result for future queries
        """
        start_time = time.monotonic()
        log = logger.bind(
            team_id=ctx.team_id,
            request_id=ctx.request_id,
            query=request.query[:100],
        )

        error_msg = None

        try:
            # --- Step 0: Input Guardrails (delegated to injected rails) ---
            rail_ctx = RailContext(
                team_id=ctx.team_id,
                namespace=request.namespace,
                tier=ctx.tier,
                request_id=ctx.request_id,
            )
            sanitized_query = request.query
            for rail in self._input_rails:
                sanitized_query = await rail.validate(sanitized_query, rail_ctx)
                log.debug("input_rail_passed", rail=rail.name)

            # --- Step 1: Adaptive RAG — classify complexity ---
            complexity = await self._llm.classify_complexity(sanitized_query)
            log.info("query_classified", complexity=complexity.value)

            # --- Step 2: Cache check ---
            cache_result = await self._cache.get(sanitized_query, ctx.team_id)
            if cache_result.hit:
                log.info("cache_hit", tier=cache_result.tier.value)
                log.info(
                    "cache_hit_audit",
                    source_count=len(cache_result.value.sources),
                    latency_ms=(time.monotonic() - start_time) * 1000,
                )
                return cache_result.value

            # --- Step 3: Dense vector search ---
            query_embedding = await self._embedder.embed_query(sanitized_query)
            # Tracking embed tokens (approximation)
            embed_token_estimate = len(sanitized_query.split()) * 2
            search_filter = VectorFilter.for_team(ctx.team_id).with_condition(
                "namespace", request.namespace
            )
            raw_results = await self._vectorstore.search(
                collection="documents",
                vector=query_embedding,
                filter=search_filter,
                limit=request.max_results * 3,  # Over-fetch for reranker
            )
            log.info("vector_search_complete", result_count=len(raw_results))

            if not raw_results:
                return RetrievalResponse(
                    answer="No relevant documents found for your query.",
                    sources=[],
                    cache_tier=CacheTier.MISS,
                    query_complexity=complexity,
                )

            # --- Step 4: Rerank ---
            reranked = await self._reranker.rerank(
                query=request.query,
                documents=[r.payload.get("content", "") for r in raw_results],
                top_n=request.max_results,
            )

            # --- Step 5: CRAG — Corrective validation (Pattern 9: The Advisor Loop) ---
            confident_chunks = [r for r in reranked if r.is_confident]
            if not confident_chunks:
                log.warning("crag_low_confidence", message="Advisor intercepting bad context.")
                # The Advisor (Critic node) logic:
                # In full implementation, we spawn `await self._llm.advise(...)` to rewrite the query.
                confident_chunks = reranked[:3]

            sources = [
                SourceChunk(
                    content=chunk.text,
                    document_id=raw_results[chunk.index].payload.get("document_id", ""),
                    chunk_index=raw_results[chunk.index].payload.get("chunk_index", 0),
                    relevance_score=chunk.relevance_score,
                )
                for chunk in confident_chunks
            ]

            # --- Step 6: Memory context ---
            memory_context: list[str] = []
            if request.include_memory and self._memory:
                memories = await self._memory.recall(
                    query=request.query,
                    team_id=ctx.team_id,
                )
                memory_context = [m.content for m in memories if m.is_current]
                log.info("memory_recalled", count=len(memory_context))

            # --- Step 7: Generate ---
            # Pattern 8: Dynamic Context Compression via TokenBudgetManager
            sources = self.budget_manager.fit_context(sources)
            context_texts = [s.content for s in sources]
            if memory_context:
                context_texts = memory_context + context_texts

            # Pattern 10: Adaptive Thinking Prompting
            adaptive_prompt = f"{sanitized_query}\n\n<search_strategy>Explain your retrieval rationale here.</search_strategy>\n<evaluation>Evaluate the context here.</evaluation>\n"

            llm_response = await self._llm.generate(
                prompt=adaptive_prompt,
                context=context_texts,
                temperature=0.1,
            )

            log.info(
                "generation_complete",
                input_tokens=llm_response.input_tokens,
                output_tokens=llm_response.output_tokens,
                embed_tokens=embed_token_estimate,
            )

            # --- Step 8: Output Guardrails (delegated to injected rails) ---
            clean_answer = llm_response.content
            for rail in self._output_rails:
                clean_answer = await rail.validate(clean_answer, sources, rail_ctx)
                log.debug("output_rail_passed", rail=rail.name)

            response = RetrievalResponse(
                answer=clean_answer,
                sources=sources,
                cache_tier=CacheTier.MISS,
                query_complexity=complexity,
                llm_response=llm_response,
                memory_context=memory_context,
            )

            # --- Step 10: Cache write ---
            await self._cache.set(
                key=request.query,  # Cache on the original query
                value=response,
                team_id=ctx.team_id,
            )

            return response
        
        except asyncio.CancelledError:
            # Pattern 7: Hierarchical Request Cancellation
            # Explicitly halt expensive vector/LLM GPU operations if the client aborts.
            logger.warning("request_cancelled_by_client", request_id=ctx.request_id)
            raise
        
        except Exception as e:
            error_msg = str(e)
            raise e
            
        finally:
            # --- Step 9: Audit Trail ---
            latency_ms = (time.monotonic() - start_time) * 1000
            log.info(
                "retrieval_complete",
                latency_ms=round(latency_ms, 2),
                source_count=len(sources) if 'sources' in locals() else 0,
                success=(error_msg is None),
                error=error_msg,
            )

    async def retrieve_stream(
        self,
        request: RetrievalRequest,
        ctx: RequestContext,
    ) -> AsyncIterator[str]:
        """
        Pattern 2: Asynchronous Token Streaming & Backpressure Management.
        Yields results chunk by chunk, drastically reducing TTFB.
        """
        try:
            # We would duplicate the retrieval phase or modularize it, resolving context here
            # For brevity:
            query_embedding = await self._embedder.embed_query(request.query)
            # pseudo-code context loading...
            context_texts = ["retrieved text chunks"] 
            
            # Pattern 10: Adaptive Thinking structure
            adaptive_prompt = request.query + "\n\nProvide <search_strategy> first."
            
            # Iterate stream from LLM directly
            if hasattr(self._llm, "generate_stream"):
                async for chunk in self._llm.generate_stream(prompt=adaptive_prompt, context=context_texts):
                    # Here we would do sliding-window string validation to strip PII mid-stream
                    # BEFORE yielding to the client via backpressure
                    yield chunk
            else:
                # Fallback
                response = await self.retrieve(request, ctx)
                yield response.answer

        except asyncio.CancelledError:
            logger.warning("stream_aborted_by_client", request_id=ctx.request_id)
            raise
===
"""
Retrieval Engine — The core RAG pipeline.

┌─────────────────────────────────────────────────────────────────────┐
│  Design Patterns Used:                                              │
│                                                                     │
│  1. CHAIN OF RESPONSIBILITY (Middleware Pipeline)                   │
│     Cache Check → Retrieve → Rerank → Validate → Generate          │
│     Each step can short-circuit (cache hit skips retrieval)         │
│                                                                     │
│  2. STRATEGY PATTERN (Swappable components)                        │
│     Embedder, VectorStore, Reranker, LLM — all injected via DI     │
│                                                                     │
│  3. TEMPLATE METHOD (retrieve flow)                                │
│     The pipeline steps are fixed, but each step's implementation   │
│     is swappable via Protocol abstractions                         │
│                                                                     │
│  RAG Advancements Applied:                                         │
│  - Adaptive Retrieval: classify_complexity → route to right model  │
│  - Corrective RAG (CRAG): validate retrieved chunks, rewrite if    │
│    confidence is too low                                           │
│  - Hybrid Search: dense + sparse (BM25) with RRF fusion           │
│                                                                     │
│  Agentic Patterns Applied:                                         │
│  - ReAct: reason about query → act (retrieve) → observe results   │
│  - Reflection: check if retrieved context is sufficient            │
│  - Tool Use: retrieval engine is itself a "tool" for agents        │
└─────────────────────────────────────────────────────────────────────┘
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable, List

import structlog

from centrag.abstractions import (
    CacheProtocol,
    EmbedderProtocol,
    LLMProtocol,
    MemoryProtocol,
    RerankerProtocol,
    VectorStoreProtocol,
)
from centrag.abstractions.cache import CacheResult, CacheTier
from centrag.abstractions.llm import LLMResponse, QueryComplexity
from centrag.abstractions.guardrail import (
    InputRailProtocol,
    OutputRailProtocol,
    RailContext,
    GuardrailViolation,
)
from centrag.abstractions.vectorstore import VectorFilter
from centrag.middleware import RequestContext
import time

logger = structlog.get_logger()


# =============================================================================
# Request / Response DTOs (Immutable)
# =============================================================================


@dataclass(frozen=True)
class RetrievalRequest:
    """Immutable retrieval request."""

    query: str
    namespace: str = "default"
    max_results: int = 5
    include_memory: bool = True
    include_sources: bool = True
    mode: str = "rag"  # "rag" | "full_context" (NotebookLM-style for small docs)


@dataclass(frozen=True)
class SourceChunk:
    """A retrieved source chunk with citation metadata."""

    content: str
    document_id: str
    chunk_index: int
    relevance_score: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RetrievalResponse:
    """Immutable retrieval response."""

    answer: str
    sources: list[SourceChunk]
    cache_tier: CacheTier
    query_complexity: QueryComplexity
    llm_response: LLMResponse | None = None
    memory_context: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-safe dict for cache storage."""
        return {
            "answer": self.answer,
            "sources": [
                {
                    "content": s.content,
                    "document_id": s.document_id,
                    "chunk_index": s.chunk_index,
                    "relevance_score": s.relevance_score,
                    "metadata": s.metadata,
                }
                for s in self.sources
            ],
            "cache_tier": self.cache_tier.value,
            "query_complexity": self.query_complexity.value,
            "memory_context": self.memory_context,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RetrievalResponse":
        """Reconstruct from cached dict."""
        return cls(
            answer=data["answer"],
            sources=[
                SourceChunk(
                    content=s["content"],
                    document_id=s["document_id"],
                    chunk_index=s["chunk_index"],
                    relevance_score=s["relevance_score"],
                    metadata=s.get("metadata", {}),
                )
                for s in data.get("sources", [])
            ],
            cache_tier=CacheTier(data.get("cache_tier", "MISS")),
            query_complexity=QueryComplexity(data.get("query_complexity", "moderate")),
            memory_context=data.get("memory_context", []),
            metadata=data.get("metadata", {}),
        )

# =============================================================================
# Agentic Design Patterns
# =============================================================================

class TokenBudgetManager:
    """
    Agentic Context Compression (Pattern 8).
    Dynamically tracks the context building window to prevent API truncation limits.
    """
    def __init__(self, max_budget: int = 3000):
        self.max_budget = max_budget
        
    def fit_context(self, sources: list[SourceChunk]) -> list[SourceChunk]:
        fitted = []
        current_cost = 0.0
        for chunk in sources:
            cost = len(chunk.content.split()) * 1.3 # simple estimation
            if current_cost + cost <= self.max_budget:
                fitted.append(chunk)
                current_cost += cost
            else:
                break
        return fitted


# =============================================================================
# Retrieval Engine
# =============================================================================


class RetrievalEngine:
    """
    Core RAG pipeline with Adaptive + Corrective RAG patterns.

    SOLID: Single Responsibility — orchestrates retrieval, doesn't implement any component.
           Guardrails are INJECTED, not called inline. This class only sequences steps.
    SOLID: Dependency Inversion — depends on Protocols, not concrete classes.
    SOLID: Open/Closed — add new retrieval strategies without modifying this class.

    All dependencies are injected via __init__ (constructor injection).
    """

    def __init__(
        self,
        embedder_factory: Callable[[], EmbedderProtocol],
        vectorstore_factory: Callable[[], VectorStoreProtocol],
        reranker_factory: Callable[[], RerankerProtocol],
        llm_factory: Callable[[], LLMProtocol],
        cache: CacheProtocol,
        memory: MemoryProtocol | None = None,
        input_rails: list[InputRailProtocol] | None = None,
        output_rails: list[OutputRailProtocol] | None = None,
    ) -> None:
        # Pattern 3: Pervasive Lazy Loading
        # SDKs (boto3, transformers) only initialize when their property is first accessed.
        self._embedder_factory = embedder_factory
        self._vectorstore_factory = vectorstore_factory
        self._reranker_factory = reranker_factory
        self._llm_factory = llm_factory
        self._cache = cache
        self._memory = memory
        self._input_rails = input_rails or []
        self._output_rails = output_rails or []

        self.__embedder = None
        self.__vectorstore = None
        self.__reranker = None
        self.__llm = None

        self.budget_manager = TokenBudgetManager()

    @property
    def _embedder(self) -> EmbedderProtocol:
        if not self.__embedder: self.__embedder = self._embedder_factory()
        return self.__embedder
        
    @property
    def _vectorstore(self) -> VectorStoreProtocol:
        if not self.__vectorstore: self.__vectorstore = self._vectorstore_factory()
        return self.__vectorstore
        
    @property
    def _reranker(self) -> RerankerProtocol:
        if not self.__reranker: self.__reranker = self._reranker_factory()
        return self.__reranker
        
    @property
    def _llm(self) -> LLMProtocol:
        if not self.__llm: self.__llm = self._llm_factory()
        return self.__llm

    async def retrieve(
        self,
        request: RetrievalRequest,
        ctx: RequestContext,
    ) -> RetrievalResponse:
        """
        Main retrieval pipeline.

        Flow (Chain of Responsibility):
        0. GUARDRAILS: Validate input query (schema, pii, prompt injection)
        1. ADAPTIVE: Classify query complexity
        2. CACHE: Check tiered cache (L1 → L2 → L3)
        3. RETRIEVE: Dense vector search (+ sparse BM25 in future)
        4. RERANK: Score chunks by relevance
        5. VALIDATE (CRAG): Check confidence — rewrite if too low
        6. MEMORY: Inject relevant memories into context
        7. GENERATE: LLM produces answer with citations
        8. GUARDRAILS: Validate response, redact PII
        9. REPORT: Audit trail with latency + cost tracking
        10. CACHE WRITE: Store result for future queries
        """
        start_time = time.monotonic()
        log = logger.bind(
            team_id=ctx.team_id,
            request_id=ctx.request_id,
            query=request.query[:100],
        )

        error_msg = None

        try:
            # --- Step 0: Input Guardrails (delegated to injected rails) ---
            rail_ctx = RailContext(
                team_id=ctx.team_id,
                namespace=request.namespace,
                tier=ctx.tier,
                request_id=ctx.request_id,
            )
            sanitized_query = request.query
            for rail in self._input_rails:
                sanitized_query = await rail.validate(sanitized_query, rail_ctx)
                log.debug("input_rail_passed", rail=rail.name)

            # --- Step 1: Adaptive RAG — classify complexity ---
            complexity = await self._llm.classify_complexity(sanitized_query)
            log.info("query_classified", complexity=complexity.value)

            # --- Step 2: Cache check ---
            cache_result = await self._cache.get(sanitized_query, ctx.team_id)
            if cache_result.hit:
                log.info("cache_hit", tier=cache_result.tier.value)
                # Reconstruct from dict (L2/L3 store JSON-safe dicts)
                if isinstance(cache_result.value, dict):
                    cached_response = RetrievalResponse.from_dict(cache_result.value)
                else:
                    cached_response = cache_result.value  # L1 stores Python objects
                log.info(
                    "cache_hit_audit",
                    source_count=len(cached_response.sources),
                    latency_ms=(time.monotonic() - start_time) * 1000,
                )
                return cached_response

            # --- Step 3: Dense vector search ---
            query_embedding = await self._embedder.embed_query(sanitized_query)
            # Tracking embed tokens (approximation)
            embed_token_estimate = len(sanitized_query.split()) * 2
            search_filter = VectorFilter.for_team(ctx.team_id).with_condition(
                "namespace", request.namespace
            )
            raw_results = await self._vectorstore.search(
                collection="documents",
                vector=query_embedding,
                filter=search_filter,
                limit=request.max_results * 3,  # Over-fetch for reranker
            )
            log.info("vector_search_complete", result_count=len(raw_results))

            if not raw_results:
                return RetrievalResponse(
                    answer="No relevant documents found for your query.",
                    sources=[],
                    cache_tier=CacheTier.MISS,
                    query_complexity=complexity,
                )

            # --- Step 4: Rerank ---
            reranked = await self._reranker.rerank(
                query=request.query,
                documents=[r.payload.get("content", "") for r in raw_results],
                top_n=request.max_results,
            )

            # --- Step 5: CRAG — Corrective validation (Pattern 9: The Advisor Loop) ---
            confident_chunks = [r for r in reranked if r.is_confident]
            if not confident_chunks:
                log.warning("crag_low_confidence", message="Advisor intercepting bad context.")
                # The Advisor (Critic node) logic:
                # In full implementation, we spawn `await self._llm.advise(...)` to rewrite the query.
                confident_chunks = reranked[:3]

            sources = [
                SourceChunk(
                    content=chunk.text,
                    document_id=raw_results[chunk.index].payload.get("document_id", ""),
                    chunk_index=raw_results[chunk.index].payload.get("chunk_index", 0),
                    relevance_score=chunk.relevance_score,
                )
                for chunk in confident_chunks
            ]

            # --- Step 6: Memory context ---
            memory_context: list[str] = []
            if request.include_memory and self._memory:
                memories = await self._memory.recall(
                    query=request.query,
                    team_id=ctx.team_id,
                )
                memory_context = [m.content for m in memories if m.is_current]
                log.info("memory_recalled", count=len(memory_context))

            # --- Step 7: Generate ---
            # Pattern 8: Dynamic Context Compression via TokenBudgetManager
            sources = self.budget_manager.fit_context(sources)
            context_texts = [s.content for s in sources]
            if memory_context:
                context_texts = memory_context + context_texts

            # Pattern 10: Adaptive Thinking Prompting
            adaptive_prompt = f"{sanitized_query}\n\n<search_strategy>Explain your retrieval rationale here.</search_strategy>\n<evaluation>Evaluate the context here.</evaluation>\n"

            llm_response = await self._llm.generate(
                prompt=adaptive_prompt,
                context=context_texts,
                temperature=0.1,
            )

            log.info(
                "generation_complete",
                input_tokens=llm_response.input_tokens,
                output_tokens=llm_response.output_tokens,
                embed_tokens=embed_token_estimate,
            )

            # --- Step 8: Output Guardrails (delegated to injected rails) ---
            clean_answer = llm_response.content
            for rail in self._output_rails:
                clean_answer = await rail.validate(clean_answer, sources, rail_ctx)
                log.debug("output_rail_passed", rail=rail.name)

            response = RetrievalResponse(
                answer=clean_answer,
                sources=sources,
                cache_tier=CacheTier.MISS,
                query_complexity=complexity,
                llm_response=llm_response,
                memory_context=memory_context,
            )

            # --- Step 10: Cache write (serialize for JSON-safe L2 storage) ---
            await self._cache.set(
                key=request.query,
                value=response.to_dict(),
                team_id=ctx.team_id,
            )

            return response
        
        except asyncio.CancelledError:
            # Pattern 7: Hierarchical Request Cancellation
            # Explicitly halt expensive vector/LLM GPU operations if the client aborts.
            logger.warning("request_cancelled_by_client", request_id=ctx.request_id)
            raise
        
        except Exception as e:
            error_msg = str(e)
            raise e
            
        finally:
            # --- Step 9: Audit Trail ---
            latency_ms = (time.monotonic() - start_time) * 1000
            log.info(
                "retrieval_complete",
                latency_ms=round(latency_ms, 2),
                source_count=len(sources) if 'sources' in locals() else 0,
                success=(error_msg is None),
                error=error_msg,
            )

    async def retrieve_stream(
        self,
        request: RetrievalRequest,
        ctx: RequestContext,
    ) -> AsyncIterator[str]:
        """
        Streaming retrieval — retrieve context first, then stream LLM generation.
        Yields response tokens chunk by chunk, reducing time-to-first-byte.
        """
        try:
            # Retrieve context (same as non-streaming pipeline)
            query_embedding = await self._embedder.embed_query(request.query)

            vf = VectorFilter(
                must=[{"key": "team_id", "match": {"value": ctx.team_id}}]
            )
            search_results = await self._vectorstore.search(
                collection=request.namespace,
                vector=query_embedding,
                filter=vf,
                limit=request.max_results,
            )

            context_texts = [
                r.payload.get("content", "") for r in search_results if r.payload
            ]

            if not context_texts:
                yield "No relevant documents found for your query."
                return

            # Stream from LLM if supported
            if hasattr(self._llm, "generate_stream"):
                async for chunk in self._llm.generate_stream(
                    prompt=request.query, context=context_texts
                ):
                    yield chunk
            else:
                # Fallback to non-streaming
                response = await self.retrieve(request, ctx)
                yield response.answer

        except asyncio.CancelledError:
            logger.warning("stream_aborted_by_client", request_id=ctx.request_id)
            raise
```

### 2.3 search_documents MCP Tool
**Bug**: `search_documents` called `rag_engine.retrieve()` — the full pipeline including LLM generation — defeating its purpose as a "search-only" tool.

**Fix**: Replaced with direct `embedder.embed_query()` → `vectorstore.search()`, completely bypassing reranking and LLM.

```diff:rag_as_mcp_tool.py
"""
RAG-as-MCP-Tool — Expose the CentRAG pipeline as MCP tools.

Pattern 1: AI agents (Claude, GPT, etc.) call CentRAG through MCP.

Instead of hardcoding the RAG pipeline into application logic,
we wrap it in an MCP Server. The AI agent calls tools like:
  - query_knowledge_base(query, namespace) → answer + sources
  - list_namespaces(team_id) → available document collections
  - search_documents(query, filters) → raw search results
  - get_extraction_status(doc_id) → processing status

This turns CentRAG into a "plug-and-play" knowledge backend
for any MCP-compatible AI host.

Design Standards:
  - Tools MUST have strongly typed inputs/outputs (JSON Schema)
  - Tools MUST be narrowly scoped (no generic "execute" commands)
  - Tools MUST be idempotent (safe to retry)
  - Tools MUST respect team_id for multi-tenant isolation
  - Tool descriptions MUST be LLM-friendly (clear, unambiguous)
"""
from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger("mcp_bridge.rag_tools")


def register_rag_tools(mcp_server: Any, rag_engine: Any) -> None:
    """
    Register CentRAG retrieval tools on an MCP server.

    This function takes a FastMCP server instance and a RetrievalEngine,
    then registers the following tools:

    Args:
        mcp_server: A FastMCP server instance (from mcp.server.fastmcp)
        rag_engine: A RetrievalEngine instance with injected dependencies

    Design Standard: Each tool follows MCP best practices:
        - Clear, LLM-friendly name and description
        - Strongly typed parameters with validation
        - Structured return format (not raw text)
        - Multi-tenant isolation via team_id
    """

    @mcp_server.tool(
        name="query_knowledge_base",
        description=(
            "Search the CentRAG knowledge base and get an AI-generated answer "
            "grounded in source documents. The answer includes citation references "
            "to the specific documents and chunks used. Use this when you need "
            "factual answers backed by an organization's internal documents."
        ),
    )
    async def query_knowledge_base(
        query: str,
        namespace: str = "default",
        max_results: int = 5,
        team_id: str = "default",
    ) -> dict[str, Any]:
        """
        Query the knowledge base with full RAG pipeline.

        Args:
            query:       Natural language question (1-5000 chars).
            namespace:   Document collection to search within.
            max_results: Maximum number of source chunks to return (1-20).
            team_id:     Team identifier for multi-tenant isolation.

        Returns:
            dict with keys:
              - answer: str — AI-generated answer grounded in sources
              - sources: list — Source chunks with content, doc_id, relevance
              - query_complexity: str — "simple" | "moderate" | "complex"
              - cache_tier: str — Which cache served (L1/L2/L3/MISS)
        """
        from centrag.retrieval.engine import RetrievalRequest
        from centrag.middleware import RequestContext

        ctx = RequestContext(
            team_id=team_id,
            team_name=team_id,
            api_key_id="mcp-bridge",
            tier="enterprise",
            rate_limit=100,
        )

        request = RetrievalRequest(
            query=query,
            namespace=namespace,
            max_results=min(max_results, 20),
        )

        response = await rag_engine.retrieve(request, ctx)

        return {
            "answer": response.answer,
            "sources": [
                {
                    "content": s.content[:500],  # Cap content length
                    "document_id": s.document_id,
                    "chunk_index": s.chunk_index,
                    "relevance_score": round(s.relevance_score, 3),
                }
                for s in response.sources
            ],
            "query_complexity": response.query_complexity.value,
            "cache_tier": response.cache_tier.value,
        }

    @mcp_server.tool(
        name="search_documents",
        description=(
            "Search for relevant document chunks without generating an answer. "
            "Use this when you need to browse or explore document content "
            "without an AI-synthesized response."
        ),
    )
    async def search_documents(
        query: str,
        namespace: str = "default",
        max_results: int = 10,
        team_id: str = "default",
    ) -> dict[str, Any]:
        """
        Raw document search — returns chunks without LLM synthesis.

        Returns:
            dict with keys:
              - results: list of matching chunks with metadata
              - total_found: int
        """
        from centrag.retrieval.engine import RetrievalRequest
        from centrag.middleware import RequestContext

        ctx = RequestContext(
            team_id=team_id,
            team_name=team_id,
            api_key_id="mcp-bridge",
            tier="enterprise",
            rate_limit=100,
        )

        request = RetrievalRequest(
            query=query,
            namespace=namespace,
            max_results=max_results,
            mode="rag",  # Search-only mode
        )

        response = await rag_engine.retrieve(request, ctx)

        return {
            "results": [
                {
                    "content": s.content,
                    "document_id": s.document_id,
                    "chunk_index": s.chunk_index,
                    "relevance_score": round(s.relevance_score, 3),
                    "metadata": s.metadata,
                }
                for s in response.sources
            ],
            "total_found": len(response.sources),
        }

    @mcp_server.resource(
        uri="centrag://namespaces",
        name="Available Namespaces",
        description="List all document namespaces available for search.",
    )
    async def list_namespaces() -> str:
        """List available document namespaces."""
        # In production, query the database for team-specific namespaces
        return (
            "Available namespaces:\\n"
            "- default: General documents\\n"
            "- engineering: Technical documentation\\n"
            "- legal: Legal and compliance documents\\n"
            "- finance: Financial reports and data"
        )

    logger.info(
        "rag_tools_registered",
        tools=["query_knowledge_base", "search_documents"],
        resources=["centrag://namespaces"],
    )
===
"""
RAG-as-MCP-Tool — Expose the CentRAG pipeline as MCP tools.

Pattern 1: AI agents (Claude, GPT, etc.) call CentRAG through MCP.

Instead of hardcoding the RAG pipeline into application logic,
we wrap it in an MCP Server. The AI agent calls tools like:
  - query_knowledge_base(query, namespace) → answer + sources
  - list_namespaces(team_id) → available document collections
  - search_documents(query, filters) → raw search results
  - get_extraction_status(doc_id) → processing status

This turns CentRAG into a "plug-and-play" knowledge backend
for any MCP-compatible AI host.

Design Standards:
  - Tools MUST have strongly typed inputs/outputs (JSON Schema)
  - Tools MUST be narrowly scoped (no generic "execute" commands)
  - Tools MUST be idempotent (safe to retry)
  - Tools MUST respect team_id for multi-tenant isolation
  - Tool descriptions MUST be LLM-friendly (clear, unambiguous)
"""
from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger("mcp_bridge.rag_tools")


def register_rag_tools(mcp_server: Any, rag_engine: Any) -> None:
    """
    Register CentRAG retrieval tools on an MCP server.

    This function takes a FastMCP server instance and a RetrievalEngine,
    then registers the following tools:

    Args:
        mcp_server: A FastMCP server instance (from mcp.server.fastmcp)
        rag_engine: A RetrievalEngine instance with injected dependencies

    Design Standard: Each tool follows MCP best practices:
        - Clear, LLM-friendly name and description
        - Strongly typed parameters with validation
        - Structured return format (not raw text)
        - Multi-tenant isolation via team_id
    """

    @mcp_server.tool(
        name="query_knowledge_base",
        description=(
            "Search the CentRAG knowledge base and get an AI-generated answer "
            "grounded in source documents. The answer includes citation references "
            "to the specific documents and chunks used. Use this when you need "
            "factual answers backed by an organization's internal documents."
        ),
    )
    async def query_knowledge_base(
        query: str,
        namespace: str = "default",
        max_results: int = 5,
        team_id: str = "default",
    ) -> dict[str, Any]:
        """
        Query the knowledge base with full RAG pipeline.

        Args:
            query:       Natural language question (1-5000 chars).
            namespace:   Document collection to search within.
            max_results: Maximum number of source chunks to return (1-20).
            team_id:     Team identifier for multi-tenant isolation.

        Returns:
            dict with keys:
              - answer: str — AI-generated answer grounded in sources
              - sources: list — Source chunks with content, doc_id, relevance
              - query_complexity: str — "simple" | "moderate" | "complex"
              - cache_tier: str — Which cache served (L1/L2/L3/MISS)
        """
        from centrag.retrieval.engine import RetrievalRequest
        from centrag.middleware import RequestContext

        ctx = RequestContext(
            team_id=team_id,
            team_name=team_id,
            api_key_id="mcp-bridge",
            tier="enterprise",
            rate_limit=100,
        )

        request = RetrievalRequest(
            query=query,
            namespace=namespace,
            max_results=min(max_results, 20),
        )

        response = await rag_engine.retrieve(request, ctx)

        return {
            "answer": response.answer,
            "sources": [
                {
                    "content": s.content[:500],  # Cap content length
                    "document_id": s.document_id,
                    "chunk_index": s.chunk_index,
                    "relevance_score": round(s.relevance_score, 3),
                }
                for s in response.sources
            ],
            "query_complexity": response.query_complexity.value,
            "cache_tier": response.cache_tier.value,
        }

    @mcp_server.tool(
        name="search_documents",
        description=(
            "Search for relevant document chunks without generating an answer. "
            "Use this when you need to browse or explore document content "
            "without an AI-synthesized response."
        ),
    )
    async def search_documents(
        query: str,
        namespace: str = "default",
        max_results: int = 10,
        team_id: str = "default",
    ) -> dict[str, Any]:
        """
        Raw document search — returns chunks without LLM synthesis.

        Uses vector search directly, bypassing reranking and generation.

        Returns:
            dict with keys:
              - results: list of matching chunks with metadata
              - total_found: int
        """
        # Use the engine's embedder + vectorstore directly (no LLM)
        from centrag.abstractions.vectorstore import VectorFilter

        embedder = rag_engine._embedder
        vectorstore = rag_engine._vectorstore

        query_embedding = await embedder.embed_query(query)

        search_filter = VectorFilter(
            must=[
                {"key": "team_id", "match": {"value": team_id}},
                {"key": "namespace", "match": {"value": namespace}},
            ]
        )

        raw_results = await vectorstore.search(
            collection="documents",
            vector=query_embedding,
            filter=search_filter,
            limit=max_results,
        )

        return {
            "results": [
                {
                    "content": r.payload.get("content", ""),
                    "document_id": r.payload.get("document_id", r.id),
                    "chunk_index": r.payload.get("chunk_index", 0),
                    "relevance_score": round(r.score, 3),
                    "metadata": {
                        k: v for k, v in r.payload.items()
                        if k not in ("content", "document_id", "chunk_index", "team_id")
                    },
                }
                for r in raw_results
            ],
            "total_found": len(raw_results),
        }

    @mcp_server.resource(
        uri="centrag://namespaces",
        name="Available Namespaces",
        description="List all document namespaces available for search.",
    )
    async def list_namespaces() -> str:
        """List available document namespaces."""
        # In production, query the database for team-specific namespaces
        return (
            "Available namespaces:\\n"
            "- default: General documents\\n"
            "- engineering: Technical documentation\\n"
            "- legal: Legal and compliance documents\\n"
            "- finance: Financial reports and data"
        )

    logger.info(
        "rag_tools_registered",
        tools=["query_knowledge_base", "search_documents"],
        resources=["centrag://namespaces"],
    )
```

### 2.4 L1 Cache Team-Scoped Invalidation
**Bug**: `invalidate()` called `self._cache.clear()` — nuking ALL teams' caches when one team's data changed.

**Fix**: Added `_team_keys: dict[str, set[str]]` tracking. On `set()`, register the key under the team. On `invalidate()`, delete only that team's keys.

```diff:l1_memory.py
"""
L1 In-Memory Cache — LRU with TTL.

Fastest cache tier (~0ms). In-process, so NOT shared across instances.
Best for: hot queries that repeat within a single server instance.

This moves the implementation logic that was mixed into
centrag/abstractions/cache.py (violating protocol/impl separation).
"""
from __future__ import annotations

import hashlib
import time
from typing import Any

from cachetools import TTLCache

from centrag.abstractions.cache import CacheProtocol, CacheResult, CacheTier

import structlog

logger = structlog.get_logger("cache.l1")


class L1InMemoryCache:
    """
    In-process LRU cache with TTL eviction.

    Implements CacheProtocol for the L1 tier.
    Uses cachetools.TTLCache for automatic expiry.
    """

    def __init__(
        self,
        maxsize: int = 1024,
        ttl_seconds: int = 300,  # 5 minutes default
    ) -> None:
        self._cache: TTLCache = TTLCache(maxsize=maxsize, ttl=ttl_seconds)
        self._default_ttl = ttl_seconds

    def _make_key(self, key: str, team_id: str) -> str:
        """Deterministic cache key scoped by team."""
        raw = f"{team_id}:{key}"
        return hashlib.sha256(raw.encode()).hexdigest()

    async def get(self, key: str, team_id: str) -> CacheResult:
        cache_key = self._make_key(key, team_id)
        value = self._cache.get(cache_key)
        if value is not None:
            logger.debug("l1_cache_hit", team_id=team_id, key_hash=cache_key[:12])
            return CacheResult(hit=True, tier=CacheTier.L1_IN_PROCESS, value=value)
        return CacheResult(hit=False, tier=CacheTier.MISS)

    async def set(
        self,
        key: str,
        value: Any,
        team_id: str,
        ttl_seconds: int = 3600,
    ) -> None:
        cache_key = self._make_key(key, team_id)
        self._cache[cache_key] = value
        logger.debug("l1_cache_set", team_id=team_id, key_hash=cache_key[:12])

    async def invalidate(self, team_id: str, namespace: str | None = None) -> int:
        """Invalidate all entries for a team (brute-force clear for L1)."""
        # TTLCache doesn't support prefix deletion, so we clear all
        count = len(self._cache)
        self._cache.clear()
        logger.info("l1_cache_invalidated", team_id=team_id, count=count)
        return count
===
"""
L1 In-Memory Cache — LRU with TTL.

Fastest cache tier (~0ms). In-process, so NOT shared across instances.
Best for: hot queries that repeat within a single server instance.

This moves the implementation logic that was mixed into
centrag/abstractions/cache.py (violating protocol/impl separation).
"""
from __future__ import annotations

import hashlib
import time
from collections import defaultdict
from typing import Any

from cachetools import TTLCache

from centrag.abstractions.cache import CacheProtocol, CacheResult, CacheTier

import structlog

logger = structlog.get_logger("cache.l1")


class L1InMemoryCache:
    """
    In-process LRU cache with TTL eviction.

    Implements CacheProtocol for the L1 tier.
    Uses cachetools.TTLCache for automatic expiry.
    Tracks team → keys mapping for scoped invalidation.
    """

    def __init__(
        self,
        maxsize: int = 1024,
        ttl_seconds: int = 300,  # 5 minutes default
    ) -> None:
        self._cache: TTLCache = TTLCache(maxsize=maxsize, ttl=ttl_seconds)
        self._default_ttl = ttl_seconds
        # Track which cache keys belong to which team for scoped invalidation
        self._team_keys: dict[str, set[str]] = defaultdict(set)

    def _make_key(self, key: str, team_id: str) -> str:
        """Deterministic cache key scoped by team."""
        raw = f"{team_id}:{key}"
        return hashlib.sha256(raw.encode()).hexdigest()

    async def get(self, key: str, team_id: str) -> CacheResult:
        cache_key = self._make_key(key, team_id)
        value = self._cache.get(cache_key)
        if value is not None:
            logger.debug("l1_cache_hit", team_id=team_id, key_hash=cache_key[:12])
            return CacheResult(hit=True, tier=CacheTier.L1_IN_PROCESS, value=value)
        return CacheResult(hit=False, tier=CacheTier.MISS)

    async def set(
        self,
        key: str,
        value: Any,
        team_id: str,
        ttl_seconds: int = 3600,
    ) -> None:
        cache_key = self._make_key(key, team_id)
        self._cache[cache_key] = value
        self._team_keys[team_id].add(cache_key)
        logger.debug("l1_cache_set", team_id=team_id, key_hash=cache_key[:12])

    async def invalidate(self, team_id: str, namespace: str | None = None) -> int:
        """Invalidate entries for a specific team (not the whole cache)."""
        keys_to_remove = self._team_keys.pop(team_id, set())
        count = 0
        for cache_key in keys_to_remove:
            if cache_key in self._cache:
                del self._cache[cache_key]
                count += 1
        logger.info("l1_cache_invalidated", team_id=team_id, count=count)
        return count
```

---

## Phase 3: Production Hardening

### 3.1 Alembic Migration
Created [001_initial_schema.py](file:///c:/Users/khars/PycharmProjects/scratch/alembic/versions/001_initial_schema.py) with:
- 6 tables: `teams`, `api_keys`, `documents`, `chunks`, `memory_entries`, `audit_logs`
- All indexes matching `models.py`
- RLS policies enabling row-level tenant isolation
- Full `downgrade()` for reversibility

### 3.2 Unit Tests
Created 4 test files in `tests/`:

| File | Coverage |
|------|----------|
| [test_implementations.py](file:///c:/Users/khars/PycharmProjects/scratch/tests/test_implementations.py) | All 4 NoOp implementations — determinism, dimension, batch, filtering |
| [test_cache.py](file:///c:/Users/khars/PycharmProjects/scratch/tests/test_cache.py) | L1 cache, orchestrator, `RetrievalResponse` serialization roundtrip |
| [test_guardrails.py](file:///c:/Users/khars/PycharmProjects/scratch/tests/test_guardrails.py) | All rails + PII detection/redaction + engine construction |
| [test_memory.py](file:///c:/Users/khars/PycharmProjects/scratch/tests/test_memory.py) | InMemoryStore — add/recall/forget, team isolation, temporal versioning |

### 3.3 LLM Streaming Protocol
Added `generate_stream()` to [LLMProtocol](file:///c:/Users/khars/PycharmProjects/scratch/centrag/abstractions/llm.py) (already implemented in NoOpLLM). Fixed `retrieve_stream()` in the engine to use real retrieved context instead of placeholder text.

---

## Remaining Lint Warnings

The `structlog`, `sqlalchemy`, `redis`, `qdrant_client`, and `cachetools` import warnings are **expected** — these packages are project dependencies that need to be installed in the active virtual environment:

```bash
pip install structlog sqlalchemy[asyncio] asyncpg redis qdrant-client cachetools pydantic-settings
```

---

## Files Modified/Created

### New Files (10)
- `centrag/implementations/__init__.py`
- `centrag/implementations/noop_embedder.py`
- `centrag/implementations/noop_vectorstore.py`
- `centrag/implementations/noop_llm.py`
- `centrag/implementations/noop_reranker.py`
- `centrag/wiring.py`
- `alembic/versions/001_initial_schema.py`
- `tests/test_implementations.py`
- `tests/test_cache.py`
- `tests/test_guardrails.py`
- `tests/test_memory.py`

### Modified Files (7)
- `centrag/app.py` — full lifespan wiring
- `centrag/routes/retrieve.py` — DI from app.state
- `centrag/retrieval/engine.py` — serialization, cache reconstruction, streaming
- `centrag/extraction/chunkers/semantic.py` — deadlock fix
- `centrag/mcp_bridge/rag_as_mcp_tool.py` — search-only mode
- `centrag/cache/l1_memory.py` — team-scoped invalidation
- `centrag/abstractions/llm.py` — generate_stream protocol

### Deleted Files (1)
- `centrag/guardrails_legacy.py`
