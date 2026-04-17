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
from typing import TYPE_CHECKING, Any

from centrag.abstractions.cache import CacheTier
from centrag.abstractions.guardrail import (
    InputRailProtocol,
    OutputRailProtocol,
    RailContext,
)
from centrag.abstractions.retrieval import RetrievalRequest, RetrievalResponse, SourceChunk
from centrag.abstractions.vectorstore import VectorFilter
from centrag.config import get_settings
from centrag.observability import (
    CostTrackingProtocol,
    MetricsProtocol,
    SpanKind,
    TracingProtocol,
)
from centrag.utils.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

    from centrag.abstractions import (
        CacheProtocol,
        EmbedderProtocol,
        LLMProtocol,
        MemoryProtocol,
        RerankerProtocol,
        VectorStoreProtocol,
    )
    from centrag.abstractions.embedder import SparseEmbedderProtocol
    from centrag.evaluation.failure_store import FailureStore
    from centrag.evaluation.judges import JudgeProtocol
    from centrag.middleware import RequestContext
    from centrag.mcp.bridge import MCPBridge
    from centrag.retrieval.generator import TwoPassGenerator

logger = get_logger()


# =============================================================================
# Agentic Design Patterns
# =============================================================================


class TokenBudgetManager:
    """Agentic Context Compression (Pattern 8).

    The WHY:
        LLMs have hard physical limits on context window size (e.g., 128k
        tokens). However, sending too much noise degrades retrieval
        quality. This manager ensures we only pack the highest-value
        chunks into the prompt, preventing API truncation errors and
        reducing inference costs.
    """

    def __init__(self, max_budget: int = 3000):
        self.max_budget = max_budget

    def fit_context(self, sources: list[SourceChunk]) -> list[SourceChunk]:
        """Prunes the source list to fit within the token budget.

        Highest relevance chunks are preserved first.
        """
        # Sort by relevance to ensure budget is spent on high-value context
        sorted_sources = sorted(sources, key=lambda x: x.relevance_score, reverse=True)

        fitted = []
        current_cost = 0.0
        for chunk in sorted_sources:
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
    """Core RAG Orchestrator implementing Adaptive & Corrective patterns.

    The WHY:
        This is the central nervous system of CentRAG. It doesn't
        implement retrieval logic; it orchestrates swappable strategies.
        It integrates Input/Output Guardrails, Tiered Caching, and
        Corrective RAG (CRAG) fallbacks to ensure that even if the
        initial search fails, the system "re-thinks" the query to
        recover relevant data.

    Design Patterns:
        - CHAIN OF RESPONSIBILITY: Middleware pipeline execution.
        - STRATEGY: Swappable Embedders, LLMs, and VectorStores.
        - FACADE: Provides a single `retrieve()` entry point for agents.

    Usage:
        engine = RetrievalEngine(...)
        response = await engine.retrieve(request, context)
        print(f"Answer: {response.answer}")
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
        # --- PHASE 4: Relational & Facet paths ---
        graph_retriever: Any | None = None,
        multivector_retriever: Any | None = None,
        cag_manager: Any | None = None,
        # --- QUERY TRANSFORMATION ---
        query_transformer: Any | None = None,
        # --- TWO-PASS GENERATION ---
        generator: TwoPassGenerator | None = None,
        failure_store: FailureStore | None = None,
        self_eval_judges: list[Any] | None = None,
        mcp_bridge: MCPBridge | None = None,
        collection_name: str = "centrag",
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

        # PHASE 4 components
        self._graph_retriever = graph_retriever
        self._multivector_retriever = multivector_retriever
        self._cag_manager = cag_manager

        self._query_transformer = query_transformer
        self._generator = generator
        self._failure_store = failure_store
        self._self_eval_judges = self_eval_judges or []
        self._mcp_bridge = mcp_bridge
        self._collection = collection_name

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
    def mcp_bridge(self) -> MCPBridge | None:
        """The Model Context Protocol bridge for tool-use."""
        return self._mcp_bridge

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
        
        settings = get_settings()
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

            # --- Step 2.5: Query Transformation (Intent & Metadata Extraction) ---
            query_filter: VectorFilter | None = None
            query_intent = None
            if self._query_transformer:
                query_intent = await self._query_transformer.transform(sanitized_query, ctx.team_id)
                sanitized_query = query_intent.optimized_query
                query_filter = query_intent.extracted_filter
                log.info("query_transformed", optimized_query=sanitized_query, has_filters=bool(query_filter), hops=query_intent.reasoning_hops)

            # Update request with intent for downstream sub-retrievers (Graph, Multivector)
            from dataclasses import replace
            request = replace(request, query=sanitized_query, query_intent=query_intent)

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
                # ── Step 3.1: RELATIONAL PATH — Graph RAG (Phase 4) ────────────────
                if settings.enable_graph_retrieval and self._graph_retriever:
                    log.info("triggering_graph_retrieval", hops=request.query_intent.reasoning_hops if request.query_intent else 1)
                    graph_resp = await self._graph_retriever.retrieve(request)
                    if graph_resp.results:
                        graph_sources = [
                            SourceChunk(
                                content=r.content,
                                document_id=r.doc_id,
                                chunk_index=0,
                                relevance_score=r.score,
                                metadata={**r.metadata, "source": "graph"}
                            ) for r in graph_resp.results
                        ]
                        sources.extend(graph_sources)
                        log.info("graph_retrieval_hits", count=len(graph_sources))

                # ── Step 3.2: FACET PATH — Multivector RAG (Phase 4) ─────────────
                if settings.enable_multivector_retrieval and self._multivector_retriever:
                    log.info("triggering_multivector_retrieval")
                    mv_resp = await self._multivector_retriever.retrieve(
                        RetrievalRequest(
                            query=sanitized_query,
                            team_id=ctx.team_id,
                            namespace=request.namespace,
                            limit=request.max_results
                        )
                    )
                    if mv_resp.results:
                        mv_sources = [
                            SourceChunk(
                                content=r.content,
                                document_id=r.doc_id,
                                chunk_index=r.metadata.get("chunk_index", 0),
                                relevance_score=r.score,
                                metadata={**r.metadata, "source": "multivector"}
                            ) for r in mv_resp.results
                        ]
                        sources.extend(mv_sources)
                        log.info("multivector_retrieval_hits", count=len(mv_sources))

                # ── Step 3.3: STANDARD VECTOR PATH (embed → search → rerank) ──────────
                if not sources:
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
                    
                    # 1. Merge LLM-extracted filters (Adaptive RAG)
                    if query_filter:
                        search_filter.must.extend(query_filter.must)
                        search_filter.must_not.extend(query_filter.must_not)
                        
                    # 2. Merge explicit API-provided filters
                    if request.metadata_filter:
                        for k, v in request.metadata_filter.items():
                            search_filter = search_filter.with_condition(k, v)
                            
                    # 3. Apply namespace scoping
                    search_filter = search_filter.with_condition("namespace", request.namespace)
                    
                    raw_results = await self._vectorstore.search(
                        collection=self._collection_name,
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
                        metadata={
                            "source": "vector",
                            "parent_chunk_id": raw_results[chunk.index].payload.get("parent_chunk_id"),
                        },
                    )
                    for chunk in confident_chunks
                ]

                # --- Step 5.2: Hierarchical Context Expansion ---
                if settings.enable_hierarchical_retrieval:
                    log.info("expanding_hierarchical_context", source_count=len(sources))
                    sources = await self._expand_hierarchical_context(sources, ctx.team_id)

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

            # --- Step 6.1: CAG Static Context (Phase 4) ---
            static_context = ""
            if self._cag_manager:
                static_context = await self._cag_manager.get_static_context(ctx.team_id, request.namespace)
                if static_context:
                    log.info("cag_context_injected", length=len(static_context))

            # --- Step 7: Generate ---
            # Pattern 8: Dynamic Context Compression via TokenBudgetManager
            sources = self.budget_manager.fit_context(sources)
            context_texts = [s.content for s in sources]
            if memory_context:
                context_texts = memory_context + context_texts
            
            if static_context:
                # CAG context goes at the top as 'Base Knowledge'
                context_texts = [f"### BASE KNOWLEDGE (CAG)\n{static_context}"] + context_texts

            # Pattern 10: Adaptive Thinking Prompting
            adaptive_prompt = (
                f"{sanitized_query}\n\n"
                "<search_strategy>Explain your retrieval rationale here.</search_strategy>\n"
                "<evaluation>Evaluate the context here.</evaluation>\n"
            )

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
            if self._cache:
                asyncio.create_task(self._cache.set(request, ctx.team_id, response))

            # --- Step 11: Self-Evaluation Audit Trail (Background) ---
            settings = get_settings()
            # Conditional Optimization: Skip evaluation for SIMPLE queries
            should_eval = (
                settings.enable_self_evaluation 
                and self._self_eval_judges 
                and complexity.value != "simple"
            )

            if should_eval:
                log.info("self_evaluation_triggered", complexity=complexity.value)
                asyncio.create_task(
                    self._run_self_evaluation(
                        query=request.query,
                        response=response,
                        ctx=ctx,
                    )
                )
            else:
                log.info("self_evaluation_skipped", complexity=complexity.value)

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

    async def _expand_hierarchical_context(
        self,
        sources: list[SourceChunk],
        team_id: str,
    ) -> list[SourceChunk]:
        """
        Recursive Shadow Retrieval: Expand leaf chunks to parents/sections.
        
        The WHY:
            Retrieval needs small chunks (precision). LLMs need large chunks (context).
            If a leaf chunk was retrieved, we fetch its parent from the DocumentStore
            to provide the LLM with the full semantic block.
        """
        if not self._document_store:
            return sources

        expanded_chunks = []
        for chunk in sources:
            parent_id = chunk.metadata.get("parent_chunk_id")
            if not parent_id:
                expanded_chunks.append(chunk)
                continue

            try:
                # Fetch full chunk list for this doc from store
                doc_chunks = await self._document_store.get_chunks(team_id, chunk.document_id)
                if not doc_chunks:
                    expanded_chunks.append(chunk)
                    continue

                # Create a map for fast lookup
                chunk_map = {c["chunk_id"]: c for c in doc_chunks if "chunk_id" in c}
                
                # Climb the tree (Limited to 2 levels for now to prevent bloating)
                current_id = parent_id
                depth = 0
                final_content = chunk.content
                
                while current_id in chunk_map and depth < 2:
                    parent = chunk_map[current_id]
                    final_content = parent.get("content", final_content)
                    current_id = parent.get("parent_chunk_id")
                    depth += 1

                from dataclasses import replace
                expanded_chunks.append(replace(
                    chunk, 
                    content=f"[Context Expanded]\n{final_content}",
                    metadata={**chunk.metadata, "expansion_depth": depth}
                ))
            except Exception as e:
                logger.warning("hierarchical_expansion_failed", error=str(e), doc_id=chunk.document_id)
                expanded_chunks.append(chunk)

        return expanded_chunks

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
    async def _run_self_evaluation(
        self,
        query: str,
        response: RetrievalResponse,
        ctx: RequestContext,
    ) -> None:
        """Background task to audit response quality.

        The WHY:
            Detects hallucinations and relevance regressions in real-time
            without blocking the user's response. Failures are logged
            to the FailureStore for later analysis.
        """
        if not self._failure_store:
            return

        settings = get_settings()
        from centrag.evaluation.judges import JudgeResult
        from centrag.evaluation.metrics import CaseResult
        from centrag.evaluation.dataset import TestCase

        source_texts = [s.content for s in response.sources]
        judge_results: list[JudgeResult] = []

        for judge in self._self_eval_judges:
            try:
                # Heuristic judges are fast and sync
                result = judge.evaluate(
                    query=query,
                    generated_answer=response.answer,
                    expected_answer="",  # Not available in production
                    sources=source_texts,
                )
                judge_results.append(result)
            except Exception as e:
                logger.warning("self_eval_judge_failed", judge=type(judge).__name__, error=str(e))

        if not judge_results:
            return

        # Calculate composite score (heuristic-only)
        avg_score = sum(r.score for r in judge_results) / len(judge_results)

        if avg_score < settings.self_eval_threshold:
            # Create a CaseResult and log to FailureStore
            # TestCase is dummy since we don't have expected answer
            case = TestCase(
                id=f"live-{ctx.request_id}",
                query=query,
                expected_answer="N/A (Production)",
                difficulty="production",
            )
            
            case_result = CaseResult(
                case=case,
                judge_results=judge_results,
                generated_answer=response.answer,
                retrieval_path=response.metadata.get("retrieval_source", "unknown"),
                latency_ms=0.0, # Not strictly tracked for self-eval here
                retrieved_doc_ids=[s.document_id for s in response.sources],
            )

            self._failure_store.add_from_result(case_result)
            logger.info(
                "self_eval_failure_recorded",
                avg_score=round(avg_score, 3),
                request_id=ctx.request_id,
            )
