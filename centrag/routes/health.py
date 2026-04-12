"""
Health routes — no auth required.

SOLID: Single Responsibility — only health checks.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health", operation_id="health_check")
async def health() -> dict:
    """Liveness probe — is the process running?"""
    return {"status": "ok", "service": "centrag", "version": "0.1.0"}


@router.get("/ready", operation_id="readiness_check")
async def ready() -> dict:
    """
    Readiness probe — can we serve traffic?
    TODO: Check DB, Redis, Qdrant connectivity
    """
    checks = {
        "postgres": "ok",  # TODO: actual DB ping
        "redis": "ok",  # TODO: actual Redis ping
        "qdrant": "ok",  # TODO: actual Qdrant ping
    }
    all_ok = all(v == "ok" for v in checks.values())
    return {"status": "ready" if all_ok else "degraded", "checks": checks}
