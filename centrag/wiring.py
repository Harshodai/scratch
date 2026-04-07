"""
Dependency Wiring — Constructs the complete RetrievalEngine with all dependencies.

Design Pattern: COMPOSITION ROOT
    - This is the ONE place where concrete implementations are selected
    - Every other module depends on abstractions (Protocols), not concrete classes
    - Swap implementations by changing this file only

Usage:
    engine = build_retrieval_engine(settings)
    response = await engine.retrieve(request, ctx)
"""
from __future__ import annotations

import structlog

from centrag.config import Settings
from centrag.retrieval.engine import RetrievalEngine
from centrag.implementations.noop_embedder import NoOpEmbedder
from centrag.implementations.noop_vectorstore import NoOpVectorStore
from centrag.implementations.noop_llm import NoOpLLM
from centrag.implementations.noop_reranker import NoOpReranker
from centrag.cache.l1_memory import L1InMemoryCache
from centrag.cache.l2_redis import L2RedisCache
from centrag.cache.orchestrator import TieredCacheOrchestrator
from centrag.memory.in_memory_store import InMemoryStore
from centrag.guardrails.engine import GuardrailEngine, GuardrailsConfig

logger = structlog.get_logger("wiring")


def build_retrieval_engine(
    settings: Settings,
    redis_client=None,
) -> RetrievalEngine:
    """
    Build a fully wired RetrievalEngine.

    Currently uses NoOp implementations for development.
    Replace with real implementations when infrastructure is available:
        - NoOpEmbedder → BedrockEmbedder
        - NoOpVectorStore → QdrantVectorStore
        - NoOpLLM → BedrockLLM / OpenAILLM
        - NoOpReranker → CohereReranker

    Args:
        settings: Application config.
        redis_client: Optional Redis client for L2 cache. None = L2 noop.
    """
    # --- Cache: L1 (in-process) → L2 (Redis) ---
    cache = TieredCacheOrchestrator(
        tiers=[
            L1InMemoryCache(maxsize=512, ttl_seconds=300),
            L2RedisCache(redis_client=redis_client),
        ]
    )

    # --- Memory: In-memory for dev, PostgreSQL for prod ---
    memory = InMemoryStore()

    # --- Guardrails ---
    guardrail_engine = GuardrailEngine(GuardrailsConfig())

    # --- Build the engine with lazy factories ---
    engine = RetrievalEngine(
        embedder_factory=lambda: NoOpEmbedder(dimension=1024),
        vectorstore_factory=NoOpVectorStore,
        reranker_factory=NoOpReranker,
        llm_factory=lambda: NoOpLLM(model_name="noop-llm-v1"),
        cache=cache,
        memory=memory,
        input_rails=guardrail_engine.input_rails,
        output_rails=guardrail_engine.output_rails,
    )

    logger.info(
        "retrieval_engine_built",
        embedder="NoOpEmbedder",
        vectorstore="NoOpVectorStore",
        llm="NoOpLLM",
        reranker="NoOpReranker",
        cache_tiers=2,
        input_rails=len(guardrail_engine.input_rails),
        output_rails=len(guardrail_engine.output_rails),
    )

    return engine
