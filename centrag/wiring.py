"""
Dependency Wiring — Constructs the complete retrieval + ingestion stack.

Design Pattern: COMPOSITION ROOT
    - This is the ONE place where concrete implementations are selected
    - Every other module depends on abstractions (Protocols), not concrete classes
    - Swap implementations by changing this file only

┌─────────────────────────────────────────────────────────────────────┐
│  DUAL-PATH WIRING:                                                  │
│                                                                     │
│  VECTORLESS path (PageIndex):                                       │
│    PageIndexTreeBuilder → PageIndexRetriever → RetrievalEngine     │
│                                                                     │
│  VECTOR path (Qdrant):                                              │
│    EmbedderProtocol → QdrantVectorStore → RetrievalEngine          │
│    Fallback: NoOpEmbedder → NoOpVectorStore                        │
│                                                                     │
│  SHARED:                                                            │
│    DocumentStore ← both paths read/write here                      │
│    QueryRouter ← decides pageindex vs vector vs hybrid              │
│    HybridRetriever ← fuses both paths via RRF                      │
│    LLMProtocol ← used by both generation AND tree navigation       │
│    IngestionService ← feeds both paths from a single upload        │
└─────────────────────────────────────────────────────────────────────┘

Usage:
    components = build_components(settings)
    engine = components["retrieval_engine"]
    ingestion = components["ingestion_service"]
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from centrag.abstractions.chunker import ChunkingConfig, ChunkingStrategy
from centrag.cache.l1_memory import L1InMemoryCache
from centrag.cache.l2_redis import L2RedisCache
from centrag.cache.semantic import SemanticCache
from centrag.cache.orchestrator import TieredCacheOrchestrator
from centrag.mcp.bridge import MCPBridge
from centrag.retrieval.engine import RetrievalEngine
from centrag.extraction.chunkers.proposition import PropositionChunker
from centrag.extraction.parsers.base import ParserRegistry
from centrag.extraction.pipeline import ExtractionPipeline
from centrag.guardrails.engine import GuardrailEngine, GuardrailsConfig
from centrag.implementations.bedrock_embedder import BedrockEmbedder
from centrag.implementations.bm25_sparse_embedder import BM25SparseEmbedder
from centrag.implementations.cohere_reranker import CohereReranker
from centrag.implementations.hyde_transformer import HyDETransformer
from centrag.implementations.llm_query_extractor import LLMQueryExtractor

# --- VECTOR path implementations (similarity-based) ---
from centrag.implementations.noop_embedder import NoOpEmbedder

# --- Shared implementations ---
from centrag.implementations.noop_llm import NoOpLLM
from centrag.implementations.noop_reranker import NoOpReranker
from centrag.implementations.noop_vectorstore import NoOpVectorStore
from centrag.implementations.openai_embedder import OpenAIEmbedder

# --- VECTORLESS path implementations (reasoning-based) ---
from centrag.implementations.pageindex_tree import PageIndexTreeBuilder
from centrag.ingestion.cleaner import DocumentCleaner, DocumentCleanerConfig

# --- Ingestion (feeds both paths) ---
from centrag.ingestion.service import IngestionService
from centrag.memory.in_memory_store import InMemoryStore
from centrag.retrieval.engine import RetrievalEngine
from centrag.retrieval.hybrid import HybridRetriever
from centrag.retrieval.pageindex_retriever import PageIndexRetriever
from centrag.retrieval.query_router import QueryRouter

# --- SHARED: Dual-path routing & PHASE 4 ---
from centrag.storage.document_store import DocumentStore
from centrag.implementations.qdrant_graph_store import QdrantGraphStore
from centrag.retrieval.graph_retriever import GraphRetriever
from centrag.retrieval.multivector_retriever import MultivectorRetriever
from centrag.retrieval.cag_manager import CAGManager
from centrag.evaluation.failure_store import FailureStore
from centrag.evaluation.judges import FaithfulnessJudge, RelevanceJudge, CoverageJudge
from centrag.utils.logger import get_logger

if TYPE_CHECKING:
    from centrag.config import Settings

logger = get_logger("wiring")


def _build_vector_components(settings: Settings):
    """Internal helper to select embedder and vectorstore."""
    # Provider strategy: "bedrock", "openai", "noop"
    if settings.embedder_provider == "bedrock":

        def embedder_factory():
            return BedrockEmbedder(model=settings.bedrock_embed_model, region=settings.aws_region)

        emb_name = "BedrockEmbedder"
    elif settings.embedder_provider == "openai":

        def embedder_factory():
            return OpenAIEmbedder()

        emb_name = "OpenAIEmbedder"
    else:

        def embedder_factory():
            return NoOpEmbedder(dimension=1024)

        emb_name = "NoOpEmbedder"

    if settings.enable_vector:
        try:
            from centrag.implementations.qdrant_vectorstore import QdrantVectorStore

            qdrant_store = QdrantVectorStore(
                url=settings.qdrant_url if not settings.qdrant_local_path else None,
                api_key=settings.qdrant_api_key or None,
                collection_name=settings.qdrant_collection,
                dimension=1024,
                path=settings.qdrant_local_path or None,
            )

            logger.info(
                "qdrant_wired",
                url=settings.qdrant_url,
                collection=settings.qdrant_collection,
            )

            return (
                embedder_factory,
                lambda: qdrant_store,
                emb_name,
                "QdrantVectorStore",
            )
        except ImportError:
            logger.warning(
                "qdrant_client_not_installed",
                message="Falling back to NoOp VectorStore. pip install qdrant-client",
            )

    # Fallback: NoOp VectorStore
    return (
        embedder_factory,
        NoOpVectorStore,
        emb_name,
        "NoOpVectorStore",
    )


def _build_llm_factory(settings: Settings):
    """Factory for selecting production or dev LLM provider."""
    if settings.llm_provider == "bedrock":
        try:
            from centrag.implementations.bedrock_llm import BedrockLLM

            def llm_factory():
                return BedrockLLM(model=settings.bedrock_llm_model, region=settings.aws_region)

            return llm_factory, "BedrockLLM"
        except ImportError:
            logger.warning("bedrock_not_installed", message="pip install boto3")

    elif settings.llm_provider == "openai":
        try:
            from centrag.implementations.openai_llm import OpenAILLM

            def llm_factory():
                return OpenAILLM(api_key=settings.openai_api_key)

            return llm_factory, "OpenAILLM"
        except ImportError:
            logger.warning("openai_not_installed", message="pip install openai")

    # Default/Fallback
    def llm_factory():
        return NoOpLLM(model_name="noop-llm-v1")

    return llm_factory, "NoOpLLM"


def build_retrieval_engine(
    settings: Settings,
    redis_client=None,
    document_store: DocumentStore | None = None,
) -> RetrievalEngine:
    """
    Build a fully wired RetrievalEngine with dual-path retrieval.

    VECTOR path: Embedder → VectorStore (Qdrant or NoOp)
    VECTORLESS path: PageIndexRetriever (DocumentStore + LLM)

    Args:
        settings: Application config.
        redis_client: Optional Redis client for L2 cache. None = L2 noop.
        document_store: Shared DocumentStore instance.
    """
    # --- Shared: DocumentStore ---
    if document_store is None:
        document_store = DocumentStore(base_path=settings.data_dir)

    # --- VECTOR path: conditional Qdrant ---
    embedder_factory, vectorstore_factory, emb_name, vs_name = _build_vector_components(settings)
    engine_embedder = embedder_factory()
    engine_vectorstore = vectorstore_factory()

    # --- Cache: L1 (in-process) → L2 (Redis Exact) → L3 (Semantic, gated) ---
    l2_cache = L2RedisCache(redis_client=redis_client)

    cache_tiers: list = [
        L1InMemoryCache(maxsize=512, ttl_seconds=300),
        l2_cache,
    ]

    # Gate L3 Semantic Cache on config flag (CENTRAG_ENABLE_SEMANTIC_CACHE)
    if getattr(settings, "enable_semantic_cache", True):
        semantic_cache = SemanticCache(
            vector_store=engine_vectorstore,
            scalar_store=l2_cache,
            embedder=engine_embedder,
            collection_name=f"{settings.qdrant_collection}_semantic_cache",
            similarity_threshold=getattr(settings, "semantic_cache_threshold", 0.95),
        )
        cache_tiers.append(semantic_cache)
        logger.info("semantic_cache_enabled", threshold=getattr(settings, "semantic_cache_threshold", 0.95))
    else:
        logger.info("semantic_cache_disabled")

    cache = TieredCacheOrchestrator(tiers=cache_tiers)

    # --- MCP (Model Context Protocol) Bridge ---
    mcp_bridge = MCPBridge() if settings.enable_mcp else None
    if mcp_bridge:
        logger.info("mcp_bridge_created")

    # --- Evaluation & Self-Audit (Self-Evaluation) ---
    failure_store = FailureStore(output_dir="evaluate/reports")
    self_eval_judges = [
        FaithfulnessJudge(),
        RelevanceJudge(),
        CoverageJudge(),
    ]

    # --- Memory: In-memory for dev ---
    memory = InMemoryStore()

    # --- Observability ---
    tracing = None
    metrics = None
    if settings.observability_provider == "otel":
        from centrag.observability.otel_provider import OTelMetrics, OTelTracer

        tracing = OTelTracer(service_name="centrag")
        metrics = OTelMetrics(service_name="centrag")
    else:
        from centrag.observability.console import ConsoleMetrics, ConsoleTracer

        tracing = ConsoleTracer()
        metrics = ConsoleMetrics()

    from centrag.observability.console import ConsoleCostTracker

    cost_tracker = ConsoleCostTracker()

    # --- Guardrails ---
    guardrail_engine = GuardrailEngine(GuardrailsConfig())

    # --- VECTOR path: conditional Qdrant ---
    embedder_factory, vectorstore_factory, emb_name, vs_name = _build_vector_components(settings)

    # --- VECTORLESS path: PageIndex ---
    pageindex_retriever = None
    if settings.enable_pageindex:
        tree_builder = PageIndexTreeBuilder(
            model=settings.pageindex_model,
            add_summaries=settings.pageindex_add_summaries,
            add_node_text=settings.pageindex_add_node_text,
        )
        pageindex_retriever = PageIndexRetriever(
            document_store=document_store,
            tree_builder=tree_builder,
            llm=None,  # Will be set after LLM factory resolves
        )

    # --- SHARED: QueryRouter + HybridRetriever ---
    query_router = QueryRouter(document_store=document_store)
    hybrid_retriever = HybridRetriever(k=60)

    # --- LLM Selection ---
    llm_factory, llm_name = _build_llm_factory(settings)

    # --- QUERY TRANSFORMATION & SPARSE EMBEDDING ---
    # Strategy pattern: select transformer based on config
    llm_for_transform = llm_factory()
    if settings.query_transformer_strategy == "hyde":
        query_transformer = HyDETransformer(llm=llm_for_transform)
        logger.info("using_hyde_transformer")
    else:
        query_transformer = LLMQueryExtractor(llm=llm_for_transform)
        logger.info("using_llm_extractor_transformer")

    # --- REASONING GENERATOR (Two-Pass) ---
    from centrag.retrieval.generator import TwoPassGenerator

    generator = TwoPassGenerator(llm=None, cache=cache)  # LLM injected lazily by engine

    # --- PHASE 4: Relational, Facet, & CAG paths ---
    # QdrantGraphStore needs the shared store and embedder
    # (Reusing engine_embedder and engine_vectorstore built above)
    
    graph_store = QdrantGraphStore(
        vector_store=engine_vectorstore,
        embedder=engine_embedder,
        collection_name=f"{settings.qdrant_collection}_graph"
    )
    graph_retriever = GraphRetriever(graph_store=graph_store, document_store=document_store)
    
    multivector_retriever = MultivectorRetriever(vectorstore=engine_vectorstore, embedder=engine_embedder)
    cag_manager = CAGManager(document_store=document_store)

    # --- RERANKER: Cohere (production) → FlashRank (local) → NoOp (dev) ---
    if settings.cohere_api_key:
        reranker_factory = lambda: CohereReranker(api_key=settings.cohere_api_key)  # noqa: E731
        reranker_name = "CohereReranker"
    else:
        try:
            import FlagEmbedding as _fe  # noqa: F401

            from centrag.implementations.bge_reranker import BGEV2Reranker
            reranker_factory = BGEV2Reranker
            reranker_name = "BGEV2Reranker"
            logger.info("using_bge_v2_reranker")
        except ImportError:
            try:
                import flashrank as _fr  # noqa: F401

                from centrag.implementations.flashrank_reranker import FlashRankReranker
                reranker_factory = FlashRankReranker  # type: ignore[assignment]
                reranker_name = "FlashRankReranker"
            except ImportError:
                reranker_factory = NoOpReranker  # type: ignore[assignment]
                reranker_name = "NoOpReranker"

    # Re-build the engine with FULL Phase 4 stack
    engine = RetrievalEngine(
        embedder_factory=embedder_factory,
        vectorstore_factory=vectorstore_factory,
        reranker_factory=reranker_factory,
        llm_factory=llm_factory,
        cache=cache,
        memory=memory,
        tracing=tracing,
        metrics=metrics,
        cost_tracker=cost_tracker,
        input_rails=guardrail_engine.input_rails,
        output_rails=guardrail_engine.output_rails,
        pageindex_retriever=pageindex_retriever,
        document_store=document_store,
        query_router=query_router,
        hybrid_retriever=hybrid_retriever,
        # Phase 4 injection
        graph_retriever=graph_retriever,
        multivector_retriever=multivector_retriever,
        cag_manager=cag_manager,
        query_transformer=query_transformer,
        sparse_embedder_factory=lambda: BM25SparseEmbedder() if settings.enable_vector else None,
        generator=generator,
        failure_store=failure_store,
        self_eval_judges=self_eval_judges,
        mcp_bridge=mcp_bridge,
        collection_name=settings.qdrant_collection,
    )

    # Wire LLM into PageIndex retriever (same lazy instance)
    if pageindex_retriever is not None:
        pageindex_retriever._llm = engine._llm

    logger.info(
        "retrieval_engine_built",
        embedder=emb_name,
        vectorstore=vs_name,
        reranker=reranker_name,
        vector_enabled=settings.enable_vector,
        pageindex_enabled=settings.enable_pageindex,
        pageindex_model=settings.pageindex_model if settings.enable_pageindex else "disabled",
        llm="NoOpLLM",
        cache_tiers=3,
        query_router="QueryRouter",
        hybrid_retriever="HybridRetriever(k=60)",
        input_rails=len(guardrail_engine.input_rails),
        output_rails=len(guardrail_engine.output_rails),
        graph_rag_enabled=settings.enable_graph_retrieval,
        multivector_enabled=settings.enable_multivector_retrieval,
    )

    return engine


def build_ingestion_service(
    settings: Settings,
    document_store: DocumentStore | None = None,
) -> IngestionService:
    """
    Build the IngestionService that feeds BOTH retrieval paths.

    Separate from build_retrieval_engine because ingestion and retrieval
    have different lifecycles — ingestion may run in a background worker.
    """
    if document_store is None:
        document_store = DocumentStore(base_path=settings.data_dir)

    # --- LLM Selection ---
    llm_factory, llm_name = _build_llm_factory(settings)

    # --- Parser registry (existing parsers) ---
    registry = ParserRegistry()
    try:
        from centrag.extraction.parsers.pdf import PDFParser

        registry.register(PDFParser())
    except ImportError:
        logger.warning("pdf_parser_unavailable")

    try:
        from centrag.extraction.parsers.text import (
            HTMLParser,
            PlainTextParser,
        )

        registry.register(PlainTextParser())
        registry.register(HTMLParser())
    except ImportError:
        logger.warning("text_parsers_unavailable")

    # --- High-Fidelity Extraction (LlamaParse) ---
    if settings.llama_cloud_api_key:
        try:
            from centrag.implementations.llama_parse_extractor import LlamaParseExtractor
    
            llamaparse = LlamaParseExtractor(api_key=settings.llama_cloud_api_key)
            registry.register(llamaparse)
            logger.info("llamaparse_wired")
        except (ImportError, ValueError) as e:
            logger.warning("llamaparse_unavailable", error=str(e))
    else:
        logger.info("llamaparse_skipped_missing_key")

    # --- Layout-Aware Extraction (Docling) ---
    try:
        from centrag.extraction.parsers.docling_parser import DoclingParser

        docling = DoclingParser(settings=settings)
        registry.register(docling)
        logger.info("docling_wired")
    except ImportError:
        logger.warning("docling_unavailable")

    # --- Extraction Pipeline with LLM support (Anthropic 2024 Contextual Retrieval) ---
    default_strategy = ChunkingStrategy.RECURSIVE
    if settings.enable_hierarchical_retrieval:
        default_strategy = ChunkingStrategy.HIERARCHICAL

    pipeline = ExtractionPipeline(
        parser_registry=registry,
        default_chunking=ChunkingConfig(
            strategy=default_strategy,
            enable_contextual_retrieval=settings.enable_contextual_retrieval,
        ),
        llm_factory=llm_factory,
    )

    # --- Proposition Chunking (PoC) ---
    # In production, this would use a production LLM from LLMGateway
    from centrag.implementations.noop_llm import NoOpLLM

    ingestion_llm = NoOpLLM(model_name="proposition-llm-v1")
    proposition_chunker = PropositionChunker(llm=ingestion_llm)
    pipeline.register_chunker(ChunkingStrategy.PROPOSITION, proposition_chunker)

    # --- VECTORLESS path: Tree builder ---
    tree_builder = PageIndexTreeBuilder(
        model=settings.pageindex_model,
        add_summaries=settings.pageindex_add_summaries,
        add_node_text=settings.pageindex_add_node_text,
    )

    # --- Cleaner ---
    cleaner = DocumentCleaner(DocumentCleanerConfig())

    # --- VECTOR path components ---
    embedder_factory, vectorstore_factory, emb_name, vs_name = _build_vector_components(settings)

    service = IngestionService(
        extraction_pipeline=pipeline,
        tree_builder=tree_builder,
        document_store=document_store,
        embedder_factory=embedder_factory,
        vectorstore_factory=vectorstore_factory,
        sparse_embedder_factory=lambda: BM25SparseEmbedder() if settings.enable_vector else None,
        graph_store_factory=lambda: QdrantGraphStore(
            vector_store=vectorstore_factory(),
            embedder=embedder_factory(),
            collection_name=f"{settings.qdrant_collection}_graph"
        ),
        cleaner=cleaner,
        collection_name=settings.qdrant_collection,
    )

    logger.info(
        "ingestion_service_built",
        parsers=registry.supported_types(),
        pageindex_model=settings.pageindex_model,
        pii_redaction=True,
        llm=llm_name,
    )

    return service
