"""
FastAPI Application Factory.

Design Pattern: FACTORY PATTERN
    - create_app() builds the entire application with all dependencies wired
    - Different configs produce different app configurations (dev vs prod)
    - Testable: call create_app() with test settings and mock dependencies

Design Pattern: CHAIN OF RESPONSIBILITY (Middleware Stack)
    - Request flows through: CORS → Logging → Auth → RateLimit → Route
    - Response flows through: PIIRedact → AuditLog → Response

Design Pattern: COMPOSITION ROOT
    - This is where the RetrievalEngine is built with all concrete dependencies
    - wiring.build_retrieval_engine() selects implementations (NoOp for dev)

SOLID: Single Responsibility — app.py only wires things together.
       No business logic here. Each middleware/route is in its own file.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from centrag.config import Settings, get_settings
from centrag.ingestion.worker import IngestionWorker, WorkerConfig
from centrag.middleware.rate_limiter import SimpleRateLimitMiddleware
from centrag.storage.document_store import DocumentStore
from centrag.utils.lifecycle import shutdown_registry
from centrag.utils.logger import get_logger
from centrag.wiring import build_ingestion_service, build_retrieval_engine

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = get_logger()


async def _init_postgres(app: FastAPI, settings: Settings):
    """Initialize PostgreSQL async engine and store on app.state."""
    try:
        from sqlalchemy.ext.asyncio import create_async_engine

        app.state.db_engine = create_async_engine(
            settings.pg_dsn,
            pool_size=settings.pg_pool_max,
            pool_pre_ping=True,
        )
        shutdown_registry.register(app.state.db_engine.dispose, priority=50)  # Close DB last
        logger.info("postgres_initialized", dsn_host=settings.pg_host)
    except Exception as e:
        logger.warning(
            "postgres_init_skipped", error=str(e), message="Running without PostgreSQL — using in-memory stores."
        )
        app.state.db_engine = None


async def _init_redis(app: FastAPI, settings: Settings):
    """Initialize Redis connection and store on app.state."""
    try:
        import redis.asyncio as aioredis

        app.state.redis = aioredis.from_url(settings.redis_url, decode_responses=True)
        await app.state.redis.ping()
        shutdown_registry.register(app.state.redis.close, priority=40)
        logger.info("redis_initialized", url=settings.redis_url)
    except Exception as e:
        logger.warning("redis_init_skipped", error=str(e), message="Running without Redis — L2 cache disabled.")
        app.state.redis = None


async def _init_qdrant(app: FastAPI, settings: Settings):
    """Initialize Qdrant client and store on app.state."""
    try:
        from qdrant_client import QdrantClient

        app.state.qdrant = QdrantClient(
            host=settings.qdrant_host,
            port=settings.qdrant_port,
        )
        logger.info("qdrant_initialized", host=settings.qdrant_host)
    except Exception as e:
        logger.warning(
            "qdrant_init_skipped", error=str(e), message="Running without Qdrant — using in-memory vector store."
        )
        app.state.qdrant = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """
    Application lifecycle management.

    Startup: Initialize DB pools, Redis, Qdrant, then build the RetrievalEngine.
    Shutdown: Clean up all connections gracefully.
    """
    settings = get_settings()
    logger.info(
        "centrag_starting",
        env=settings.env,
        debug=settings.debug,
    )

    # --- Startup (Parallel Resource Acquisition) ---
    await asyncio.gather(
        _init_postgres(app, settings),
        _init_redis(app, settings),
        _init_qdrant(app, settings),
        return_exceptions=True,  # Don't fail if infra is down in dev
    )

    # --- Shared: DocumentStore (used by BOTH paths) ---
    document_store = DocumentStore(base_path=settings.data_dir)
    app.state.document_store = document_store

    # --- Build the RetrievalEngine (dual-path: vector + vectorless) ---
    redis_client = getattr(app.state, "redis", None)
    app.state.retrieval_engine = build_retrieval_engine(
        settings=settings,
        redis_client=redis_client,
        document_store=document_store,
    )

    # --- Build IngestionService (feeds both paths) ---
    app.state.ingestion_service = build_ingestion_service(
        settings=settings,
        document_store=document_store,
    )

    # --- Start IngestionWorker (async background processor) ---
    if settings.sqs_queue_url:
        from centrag.ingestion.sqs_worker import AioSQSWorker

        worker = AioSQSWorker(
            sqs_queue_url=settings.sqs_queue_url,
            ingestion_service=app.state.ingestion_service,
            document_store=document_store,
            config=WorkerConfig(),
        )
        logger.info("using_sqs_ingestion_worker", queue=settings.sqs_queue_url)
    else:
        worker = IngestionWorker(
            ingestion_service=app.state.ingestion_service,
            document_store=document_store,
            config=WorkerConfig(),
        )
        logger.info("using_memory_ingestion_worker")

    await worker.start()
    shutdown_registry.register(worker.shutdown, priority=10)  # Drain worker first
    app.state.ingestion_worker = worker

    # --- Initialize MCP (Model Context Protocol) ---
    if settings.enable_mcp:
        engine = app.state.retrieval_engine
        bridge = engine.mcp_bridge

        if bridge:
            # 1. Load Declarative Config (Steal #2)
            from pathlib import Path

            config_path = Path(settings.mcp_tools_config_path)
            if config_path.exists():
                try:
                    summary = bridge.load_config(config_path)
                    logger.info("mcp_declarative_config_loaded", summary=summary)
                except Exception as e:
                    logger.error("mcp_config_load_failed", error=str(e))

            # 2. Register Legacy Internal DBs (backward compat)
            for db_name, conn_str in settings.mcp_internal_dbs.items():
                bridge.register_dynamic_db(db_name, conn_str)
                logger.info("mcp_bridge_db_registered", name=db_name)

            # 3. Launch External Servers (Managed Subprocesses)
            for srv_name, command in settings.mcp_external_servers.items():
                bridge.launch_external_server(srv_name, command)
                logger.info("mcp_bridge_server_launched", name=srv_name)

            # Ensure cleanup on shutdown
            shutdown_registry.register(bridge.shutdown, priority=1)

        try:
            from mcp.server.fastmcp import FastMCP

            from centrag.mcp_bridge.rag_as_mcp_tool import register_rag_tools

            mcp_server = FastMCP("CentRAG-Retriever")
            register_rag_tools(mcp_server, app.state.retrieval_engine)
            app.state.mcp_server = mcp_server
            logger.info("mcp_server_initialized", name="CentRAG-Retriever")
        except ImportError as e:
            logger.warning("mcp_init_failed", error=str(e), package="mcp")

    logger.info(
        "centrag_ready",
        host=settings.api_host,
        port=settings.api_port,
        pageindex_enabled=settings.enable_pageindex,
        data_dir=settings.data_dir,
        async_worker="running",
        mcp_enabled=settings.enable_mcp,
    )

    yield  # App runs here

    # --- Shutdown ---
    await shutdown_registry.shutdown()
    logger.info("centrag_shutdown_sequence_completed")


def create_app() -> FastAPI:
    """
    Application factory — builds the FastAPI app with all middleware and routes.

    Usage:
        uvicorn centrag.app:create_app --factory --reload
    """
    settings = get_settings()

    app = FastAPI(
        title="CentRAG",
        description="Secure, Multi-Tenant RAG-as-a-Service Platform",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
    )

    # --- Middleware Stack (Chain of Responsibility) ---
    # Top middleware executes FIRST on request

    # 1. CORS: Strict origins in production
    cors_origins = getattr(settings, "cors_origins", ["https://app.centrag.io"]) if settings.is_production else ["*"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "x-team-id"],
    )

    # 2. Rate Limiting (Defense in depth against DDoS)
    app.add_middleware(
        SimpleRateLimitMiddleware, max_requests=100 if settings.is_production else 1000, window_seconds=60
    )

    # --- Routes ---
    from centrag.routes.documents import router as documents_router
    from centrag.routes.evaluate import router as evaluate_router
    from centrag.routes.feedback import router as feedback_router
    from centrag.routes.health import router as health_router
    from centrag.routes.retrieve import router as retrieve_router

    app.include_router(health_router)
    app.include_router(feedback_router, prefix="/v1")

    # Feature Flags for Dynamic Route Inclusion
    if settings.enable_docs_routes:
        app.include_router(documents_router, prefix="/v1")
    if settings.enable_retrieval_routes:
        app.include_router(retrieve_router, prefix="/v1")

    # Evaluation — always available (gated by auth, not feature flag)
    app.include_router(evaluate_router, prefix="/v1")

    return app
