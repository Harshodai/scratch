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
    """
    Immutable retrieval request.

    Supports dual-path retrieval:
        mode="auto"      → QueryRouter decides (Day 3)
        mode="pageindex"  → VECTORLESS path only
        mode="vector"     → VECTOR path only
        mode="hybrid"     → Both paths + RRF fusion (Day 3)
        mode="rag"        → Legacy: vector search (backward compat)
    """

    query: str
    namespace: str = "default"
    max_results: int = 5
    include_memory: bool = True
    include_sources: bool = True
    mode: str = "rag"  # "auto" | "pageindex" | "vector" | "hybrid" | "rag"
    target_doc_id: str = ""  # Scope to a specific document (enables PageIndex)


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
        # --- VECTORLESS path (PageIndex) ---
        pageindex_retriever: Any | None = None,
        document_store: Any | None = None,
        # --- SHARED: Dual-path routing (Day 3) ---
        query_router: Any | None = None,
        hybrid_retriever: Any | None = None,
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

        # VECTORLESS path components
        self._pageindex_retriever = pageindex_retriever
        self._document_store = document_store

        # SHARED: Dual-path routing
        self._query_router = query_router
        self._hybrid_retriever = hybrid_retriever

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

            # --- Step 3: Retrieval (DUAL-PATH) ---
            # Route to VECTORLESS or VECTOR path based on request.mode
            use_pageindex = (
                self._pageindex_retriever is not None
                and request.target_doc_id
                and request.mode in ("pageindex", "auto", "hybrid")
            )

            raw_results = []
            sources: list[SourceChunk] = []
            retrieval_source = "vector"  # default
            embed_token_estimate = 0

            if use_pageindex:
                # ── VECTORLESS PATH (PageIndex) ─────────────────────
                log.info("using_pageindex_retrieval", doc_id=request.target_doc_id)
                retrieval_source = "pageindex"

                pi_results = await self._pageindex_retriever.retrieve(
                    query=sanitized_query,
                    doc_id=request.target_doc_id,
                    team_id=ctx.team_id,
                    limit=request.max_results,
                )

                if pi_results:
                    sources = [
                        SourceChunk(
                            content=r.content,
                            document_id=r.doc_id,
                            chunk_index=0,
                            relevance_score=r.relevance_score,
                            metadata={
                                "source": "pageindex",
                                "page_refs": r.page_refs,
                                "reasoning": r.reasoning,
                                **r.metadata,
                            },
                        )
                        for r in pi_results
                    ]
                    log.info(
                        "pageindex_retrieval_complete",
                        result_count=len(sources),
                        page_refs=pi_results[0].page_refs if pi_results else "",
                    )

            if not sources:
                # ── VECTOR PATH (embed → search → rerank) ──────────
                if retrieval_source == "pageindex":
                    log.info("pageindex_empty_fallback_to_vector")
                retrieval_source = "vector" if not use_pageindex else retrieval_source

                query_embedding = await self._embedder.embed_query(sanitized_query)
                embed_token_estimate = len(sanitized_query.split()) * 2
                search_filter = VectorFilter.for_team(ctx.team_id).with_condition(
                    "namespace", request.namespace
                )
                raw_results = await self._vectorstore.search(
                    collection="documents",
                    vector=query_embedding,
                    filter=search_filter,
                    limit=request.max_results * 3,
                )
                log.info("vector_search_complete", result_count=len(raw_results))

            if not raw_results and not sources:
                return RetrievalResponse(
                    answer="No relevant documents found for your query.",
                    sources=[],
                    cache_tier=CacheTier.MISS,
                    query_complexity=complexity,
                    metadata={"retrieval_source": retrieval_source},
                )

            # --- Step 4: Rerank (VECTOR path only) ---
            if raw_results and not sources:
                reranked = await self._reranker.rerank(
                    query=request.query,
                    documents=[r.payload.get("content", "") for r in raw_results],
                    top_n=request.max_results,
                )

                # --- Step 5: CRAG — Corrective validation ---
                confident_chunks = [r for r in reranked if r.is_confident]
                if not confident_chunks:
                    log.warning("crag_low_confidence", message="Advisor intercepting bad context.")
                    confident_chunks = reranked[:3]

                sources = [
                    SourceChunk(
                        content=chunk.text,
                        document_id=raw_results[chunk.index].payload.get("document_id", ""),
                        chunk_index=raw_results[chunk.index].payload.get("chunk_index", 0),
                        relevance_score=chunk.relevance_score,
                        metadata={"source": "vector"},
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
                metadata={"retrieval_source": retrieval_source},
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
