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
import time
from collections.abc import AsyncIterator, Callable
from typing import Any

from centrag.abstractions import (
    CacheProtocol,
    EmbedderProtocol,
    LLMProtocol,
    MemoryProtocol,
    RerankerProtocol,
    VectorStoreProtocol,
)
from centrag.abstractions.cache import CacheTier
from centrag.abstractions.embedder import SparseEmbedderProtocol
from centrag.abstractions.guardrail import (
    InputRailProtocol,
    OutputRailProtocol,
    RailContext,
)
from centrag.abstractions.retrieval import RetrievalRequest, RetrievalResponse, SourceChunk
from centrag.abstractions.vectorstore import VectorFilter
from centrag.config import get_settings
from centrag.middleware import RequestContext
from centrag.observability import (
    CostTrackingProtocol,
    MetricsProtocol,
    SpanKind,
    TracingProtocol,
)
from centrag.retrieval.generator import TwoPassGenerator
from centrag.utils.logger import get_logger

logger = get_logger()


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
            cost = len(chunk.content.split()) * 1.3  # simple estimation
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
        memory: MemoryProtocol,
        sparse_embedder_factory: Callable[[], SparseEmbedderProtocol] | None = None,
        input_rails: list[InputRailProtocol] | None = None,
        output_rails: list[OutputRailProtocol] | None = None,
        # --- OBSERVABILITY ---
        tracing: TracingProtocol | None = None,
        metrics: MetricsProtocol | None = None,
        cost_tracker: CostTrackingProtocol | None = None,
        # --- VECTORLESS path (PageIndex) ---
        pageindex_retriever: Any | None = None,
        document_store: Any | None = None,
        # --- SHARED: Dual-path routing (Day 3) ---
        query_router: Any | None = None,
        hybrid_retriever: Any | None = None,
        # --- QUERY TRANSFORMATION ---
        query_transformer: Any | None = None,
        # --- TWO-PASS GENERATION ---
        generator: TwoPassGenerator | None = None,
    ) -> None:
        # Pattern 3: Pervasive Lazy Loading
        # SDKs (boto3, transformers) only initialize when their property is first accessed.
        self._embedder_factory = embedder_factory
        self._sparse_embedder_factory = sparse_embedder_factory
        self._vectorstore_factory = vectorstore_factory
        self._reranker_factory = reranker_factory
        self._llm_factory = llm_factory
        self._cache = cache
        self._memory = memory
        self._input_rails = input_rails or []
        self._output_rails = output_rails or []

        # Observability (Injected abstractions)
        from centrag.observability.console import ConsoleCostTracker, ConsoleMetrics, ConsoleTracer

        self._tracing = tracing or ConsoleTracer()
        self._metrics = metrics or ConsoleMetrics()
        self._cost_tracker = cost_tracker or ConsoleCostTracker()

        # VECTORLESS path components
        self._pageindex_retriever = pageindex_retriever
        self._document_store = document_store

        # SHARED: Dual-path routing
        self._query_router = query_router
        self._hybrid_retriever = hybrid_retriever
        self._query_transformer = query_transformer
        self._generator = generator

        self.__embedder = None
        self.__vectorstore = None
        self.__reranker = None
        self.__llm = None
        self._sparse_embedder_instance = None

        self.budget_manager = TokenBudgetManager()

    @property
    def _embedder(self) -> EmbedderProtocol:
        if not self.__embedder:
            self.__embedder = self._embedder_factory()
        return self.__embedder

    @property
    def _sparse_embedder(self) -> SparseEmbedderProtocol | None:
        if self._sparse_embedder_instance is None:
            self._sparse_embedder_instance = self._sparse_embedder_factory() if self._sparse_embedder_factory else None
        return self._sparse_embedder_instance

    @property
    def _vectorstore(self) -> VectorStoreProtocol:
        if not self.__vectorstore:
            self.__vectorstore = self._vectorstore_factory()
        return self.__vectorstore

    @property
    def _reranker(self) -> RerankerProtocol:
        if not self.__reranker:
            self.__reranker = self._reranker_factory()
        return self.__reranker

    @property
    def _llm(self) -> LLMProtocol:
        if not self.__llm:
            self.__llm = self._llm_factory()
        return self.__llm

    async def retrieve(
        self,
        request: RetrievalRequest,
        ctx: RequestContext,
    ) -> RetrievalResponse:
        """
        7. GENERATE: LLM produces answer with citations
        8. GUARDRAILS: Validate response, redact PII
        9. REPORT: Audit trail with latency + cost tracking
        10. CACHE WRITE: Store result for future queries
        """
        async with self._tracing.span("centrag.retrieve", SpanKind.RETRIEVAL) as span:
            span.attributes.update(
                {
                    "team_id": ctx.team_id,
                    "request_mode": request.mode,
                    "namespace": request.namespace,
                }
            )

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

            # --- Step 2.5: Query Transformation (Metadata Extraction) ---
            query_filter: VectorFilter | None = None
            if self._query_transformer:
                intent = await self._query_transformer.transform(sanitized_query, ctx.team_id)
                sanitized_query = intent.optimized_query
                query_filter = intent.extracted_filter
                log.info("query_transformed", optimized_query=sanitized_query, has_filters=bool(query_filter))

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
                sparse_vector = (
                    await self._sparse_embedder.embed_sparse(sanitized_query) if self._sparse_embedder else None
                )
                embed_token_estimate = len(sanitized_query.split()) * 2
                # Ensure team-isolation is ALWAYS the baseline filter before merging LLM extractions
                search_filter = VectorFilter.for_team(ctx.team_id)
                if query_filter:
                    search_filter.must.extend(query_filter.must)
                    search_filter.must_not.extend(query_filter.must_not)
                search_filter = search_filter.with_condition("namespace", request.namespace)
                raw_results = await self._vectorstore.search(
                    collection="documents",
                    vector=query_embedding,
                    filter=search_filter,
                    limit=request.max_results * 3,
                    sparse_vector=sparse_vector,
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
                crag_retried = False
                fallback_reranked = None

                if not confident_chunks and self._query_transformer:
                    log.warning(
                        "crag_low_confidence",
                        message="Advisor intercepting bad context. Triggering CRAG rewrite fallback.",
                    )
                    intent = await self._query_transformer.transform(
                        f"Abstract synonym generation for: {sanitized_query}", ctx.team_id
                    )
                    fallback_query = " ".join(intent.expansions) if intent.expansions else intent.optimized_query

                    fallback_embedding = await self._embedder.embed_query(fallback_query)
                    fallback_sparse = (
                        await self._sparse_embedder.embed_sparse(fallback_query) if self._sparse_embedder else None
                    )
                    embed_token_estimate += len(fallback_query.split()) * 2

                    fallback_results = await self._vectorstore.search(
                        collection="documents",
                        vector=fallback_embedding,
                        filter=search_filter,
                        limit=request.max_results,
                        sparse_vector=fallback_sparse,
                    )

                    if fallback_results:
                        fallback_reranked = await self._reranker.rerank(
                            query=request.query,
                            documents=[r.payload.get("content", "") for r in fallback_results],
                            top_n=request.max_results,
                        )
                        confident_chunks = [r for r in fallback_reranked if r.is_confident]
                        raw_results = fallback_results
                        crag_retried = True
                        log.info("crag_fallback_complete", recovered_chunks=len(confident_chunks))

                if not confident_chunks:
                    log.warning(
                        "crag_fallback_failed",
                        message="No confident context available even after rewrite. Returning top 3.",
                    )
                    if crag_retried and fallback_reranked is not None:
                        confident_chunks = fallback_reranked[:3]
                    else:
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

            # --- Step 5.5: Contextual Compression (LLM-based refinement) ---
            settings = get_settings()
            if settings.enable_contextual_compression and sources:
                log.info("compressing_context", source_count=len(sources))
                sources = await self._compress_context(request.query, sources)
                log.info("compression_complete", source_count=len(sources))

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
                source_count=len(sources) if "sources" in locals() else 0,
                success=(error_msg is None),
                error=error_msg,
            )

    async def _compress_context(self, query: str, sources: list[SourceChunk]) -> list[SourceChunk]:
        """
        Use the LLM to extract only relevant fragments from retrieved chunks
        relative to the query.
        """
        compressed_sources = []
        # In production, this would be parallelized
        for chunk in sources:
            prompt = f"""
            You are a helpful assistant that compresses text for a RAG system.
            
            Query: {query}
            
            Chunk Content:
            {chunk.content}
            
            Task:
            Review the chunk content above. Extract only the sentences that are directly relevant 
            to answering the query. If the entire chunk is relevant, return it as is. 
            If none of it is relevant, respond with "NO_RELEVANT_CONTENT".
            Respond only with the compressed text or "NO_RELEVANT_CONTENT".
            """

            try:
                resp = await self._llm.generate(prompt, context=[chunk.content])
                content = resp.content.strip()
                if content != "NO_RELEVANT_CONTENT":
                    from dataclasses import replace

                    compressed_sources.append(replace(chunk, content=content))
            except Exception as e:
                logger.warning("compression_failed_for_chunk", error=str(e))
                compressed_sources.append(chunk)

        return compressed_sources

    async def retrieve_stream(
        self,
        request: RetrievalRequest,
        ctx: RequestContext,
    ) -> AsyncIterator[str]:
        """
        Streaming retrieval -- retrieve context first, then stream LLM generation.
        Yields response tokens chunk by chunk, reducing time-to-first-byte.
        """
        try:
            # Retrieve context (same as non-streaming pipeline)
            query_embedding = await self._embedder.embed_query(request.query)

            vf = VectorFilter(must=[{"key": "team_id", "match": {"value": ctx.team_id}}])
            search_results = await self._vectorstore.search(
                collection=request.namespace,
                vector=query_embedding,
                filter=vf,
                limit=request.max_results,
            )

            context_texts = [r.payload.get("content", "") for r in search_results if r.payload]

            if not context_texts:
                yield "No relevant documents found for your query."
                return

            # Stream from LLM if supported
            if hasattr(self._llm, "generate_stream"):
                async for chunk in self._llm.generate_stream(prompt=request.query, context=context_texts):
                    yield chunk
            else:
                # Fallback to non-streaming
                response = await self.retrieve(request, ctx)
                yield response.answer

        except asyncio.CancelledError:
            logger.warning("stream_aborted_by_client", request_id=ctx.request_id)
            raise
