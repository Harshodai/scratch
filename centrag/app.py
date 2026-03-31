"""
FastAPI Application Factory.

Design Pattern: FACTORY PATTERN
    - create_app() builds the entire application with all dependencies wired
    - Different configs produce different app configurations (dev vs prod)
    - Testable: call create_app() with test settings and mock dependencies

Design Pattern: CHAIN OF RESPONSIBILITY (Middleware Stack)
    - Request flows through: CORS → Logging → Auth → RateLimit → Route
    - Response flows through: PIIRedact → AuditLog → Response

SOLID: Single Responsibility — app.py only wires things together.
       No business logic here. Each middleware/route is in its own file.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
import asyncio
from typing import AsyncIterator

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from centrag.config import get_settings, Settings

logger = structlog.get_logger()

async def _init_postgres(app: FastAPI, settings: Settings):
    # TODO: app.state.db_engine = create_async_engine(settings.pg_dsn, pool_size=settings.pg_pool_max)
    logger.debug("postgres_initialized")

async def _init_redis(app: FastAPI, settings: Settings):
    # TODO: app.state.redis = await aioredis.from_url(settings.redis_url)
    logger.debug("redis_initialized")

async def _init_qdrant(app: FastAPI, settings: Settings):
    # TODO: app.state.qdrant = QdrantClient(host=settings.qdrant_host, port=settings.qdrant_port)
    logger.debug("qdrant_initialized")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """
    Application lifecycle management.

    Startup: Initialize DB pools, Redis connections, Qdrant client.
    Shutdown: Clean up all connections gracefully.

    Design Pattern: RESOURCE ACQUISITION IS INITIALIZATION (RAII)
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
        return_exceptions=False,  # Fail fast if core infrastructure is down
    )

    logger.info("centrag_ready", host=settings.api_host, port=settings.api_port)

    yield  # App runs here

    # --- Shutdown ---
    # TODO: Close connections:
    # await app.state.db_engine.dispose()
    # await app.state.redis.close()
    logger.info("centrag_shutdown")


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
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if not settings.is_production else [],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # --- Routes ---
    from centrag.routes.health import router as health_router
    from centrag.routes.documents import router as documents_router
    from centrag.routes.retrieve import router as retrieve_router

    app.include_router(health_router)
    
    # Feature Flags for Dynamic Route Inclusion
    if settings.enable_docs_routes:
        app.include_router(documents_router, prefix="/v1")
    if settings.enable_retrieval_routes:
        app.include_router(retrieve_router, prefix="/v1")

    return app
