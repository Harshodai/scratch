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

from centrag.utils.logger import get_logger

from centrag.config import Settings

# --- Shared infrastructure ---
from centrag.storage.document_store import DocumentStore
from centrag.retrieval.engine import RetrievalEngine
from centrag.retrieval.query_router import QueryRouter
from centrag.retrieval.hybrid import HybridRetriever

# --- VECTOR path implementations (similarity-based) ---
from centrag.implementations.noop_embedder import NoOpEmbedder
from centrag.implementations.noop_vectorstore import NoOpVectorStore
from centrag.implementations.noop_reranker import NoOpReranker
from centrag.implementations.bm25_sparse_embedder import BM25SparseEmbedder
from centrag.implementations.llm_query_extractor import LLMQueryExtractor
from centrag.implementations.hyde_transformer import HyDETransformer

# --- VECTORLESS path implementations (reasoning-based) ---
from centrag.implementations.pageindex_tree import PageIndexTreeBuilder
from centrag.retrieval.pageindex_retriever import PageIndexRetriever

# --- Shared implementations ---
from centrag.implementations.noop_llm import NoOpLLM
from centrag.cache.l1_memory import L1InMemoryCache
from centrag.cache.l2_redis import L2RedisCache
from centrag.cache.orchestrator import TieredCacheOrchestrator
from centrag.memory.in_memory_store import InMemoryStore
from centrag.guardrails.engine import GuardrailEngine, GuardrailsConfig

# --- Ingestion (feeds both paths) ---
from centrag.ingestion.service import IngestionService
from centrag.ingestion.cleaner import DocumentCleaner, DocumentCleanerConfig
from centrag.extraction.pipeline import ExtractionPipeline
from centrag.extraction.parsers.base import ParserRegistry

logger = get_logger("wiring")


def _build_vector_components(settings: Settings):
    """
    Build VECTOR path components conditionally.

    Returns:
        (embedder_factory, vectorstore_factory, embedder_name, store_name)
    """
    if settings.enable_vector:
        try:
            from centrag.implementations.qdrant_vectorstore import QdrantVectorStore

            qdrant_store = QdrantVectorStore(
                url=settings.qdrant_url,
                api_key=settings.qdrant_api_key or None,
                collection_name=settings.qdrant_collection,
                dimension=1024,
            )

            logger.info(
                "qdrant_wired",
                url=settings.qdrant_url,
                collection=settings.qdrant_collection,
            )

            return (
                lambda: NoOpEmbedder(dimension=1024),  # Day 4: OpenAI/Bedrock
                lambda: qdrant_store,
                "NoOpEmbedder",
                "QdrantVectorStore",
            )
        except ImportError:
            logger.warning(
                "qdrant_client_not_installed",
                message="Falling back to NoOp. pip install qdrant-client",
            )

    # Fallback: NoOp implementations
    return (
        lambda: NoOpEmbedder(dimension=1024),
        NoOpVectorStore,
        "NoOpEmbedder",
        "NoOpVectorStore",
    )


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

    # --- Cache: L1 (in-process) → L2 (Redis) ---
    cache = TieredCacheOrchestrator(
        tiers=[
            L1InMemoryCache(maxsize=512, ttl_seconds=300),
            L2RedisCache(redis_client=redis_client),
        ]
    )

    # --- Memory: In-memory for dev ---
    memory = InMemoryStore()

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

    # --- QUERY TRANSFORMATION & SPARSE EMBEDDING ---
    # Strategy pattern: select transformer based on config
    llm_for_transform = NoOpLLM(model_name="noop-llm-transformer")
    if settings.query_transformer_strategy == "hyde":
        query_transformer = HyDETransformer(llm=llm_for_transform)
        logger.info("using_hyde_transformer")
    else:
        query_transformer = LLMQueryExtractor(llm=llm_for_transform)
        logger.info("using_llm_extractor_transformer")

    # --- Build the engine ---
    engine = RetrievalEngine(
        embedder_factory=embedder_factory,
        vectorstore_factory=vectorstore_factory,
        reranker_factory=NoOpReranker,
        llm_factory=lambda: NoOpLLM(model_name="noop-llm-v1"),
        cache=cache,
        memory=memory,
        input_rails=guardrail_engine.input_rails,
        output_rails=guardrail_engine.output_rails,
        pageindex_retriever=pageindex_retriever,
        document_store=document_store,
        query_router=query_router,
        hybrid_retriever=hybrid_retriever,
        query_transformer=query_transformer,
        sparse_embedder_factory=lambda: BM25SparseEmbedder() if settings.enable_vector else None,
    )

    # Wire LLM into PageIndex retriever (same lazy instance)
    if pageindex_retriever is not None:
        pageindex_retriever._llm = engine._llm

    logger.info(
        "retrieval_engine_built",
        embedder=emb_name,
        vectorstore=vs_name,
        reranker="NoOpReranker",
        vector_enabled=settings.enable_vector,
        pageindex_enabled=settings.enable_pageindex,
        pageindex_model=settings.pageindex_model if settings.enable_pageindex else "disabled",
        llm="NoOpLLM",
        cache_tiers=2,
        query_router="QueryRouter",
        hybrid_retriever="HybridRetriever(k=60)",
        input_rails=len(guardrail_engine.input_rails),
        output_rails=len(guardrail_engine.output_rails),
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

    # --- Parser registry (existing parsers) ---
    registry = ParserRegistry()
    try:
        from centrag.extraction.parsers.pdf import PDFParser
        registry.register(PDFParser())
    except ImportError:
        logger.warning("pdf_parser_unavailable")

    try:
        from centrag.extraction.parsers.text import (
            PlainTextParser,
            MarkdownParser,
            HTMLParser,
        )
        registry.register(PlainTextParser())
        registry.register(MarkdownParser())
        registry.register(HTMLParser())
    except ImportError:
        logger.warning("text_parsers_unavailable")

    pipeline = ExtractionPipeline(parser_registry=registry)

    # --- VECTORLESS path: Tree builder ---
    tree_builder = PageIndexTreeBuilder(
        model=settings.pageindex_model,
        add_summaries=settings.pageindex_add_summaries,
        add_node_text=settings.pageindex_add_node_text,
    )

    # --- Cleaner ---
    cleaner = DocumentCleaner(DocumentCleanerConfig())

    service = IngestionService(
        extraction_pipeline=pipeline,
        tree_builder=tree_builder,
        document_store=document_store,
        cleaner=cleaner,
    )

    logger.info(
        "ingestion_service_built",
        parsers=registry.supported_types(),
        pageindex_model=settings.pageindex_model,
        pii_redaction=True,
    )

    return service
