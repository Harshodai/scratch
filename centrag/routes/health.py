"""Health and Readiness API — The Platform Heartbeat.

The WHY:
    In a high-availability production environment (Kubernetes, AWS ECS,
    Railway), the infrastructure needs to know when to "Kill" and
    "Restart" a service. These endpoints provide automated probes
    that verify if the process is alive (Liveness) and if all its
    dependencies (Postgres, Qdrant, Bedrock) are connected
    (Readiness). This enables zero-downtime rolling deployments
    and self-healing infrastructure.

Required: pydantic, structlog, fastapi, uvicorn
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
