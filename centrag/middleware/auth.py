"""
Auth Middleware — Resolves API key to team context.

SOLID: Single Responsibility — ONLY does auth. No business logic.

Design Pattern: CHAIN OF RESPONSIBILITY
    - This middleware is ONE link in the chain:
      Request → Auth → RateLimit → [Route Handler] → PIIRedact → AuditLog → Response

Agentic Pattern: GOVERNANCE-AS-CODE
    - Auth is hardwired into the middleware chain, not optional
    - Even if an agent calls the API, it MUST present a valid API key
    - The team_id is injected into RequestContext and flows through everything
"""
from __future__ import annotations

import hashlib
import secrets
import uuid
from typing import TYPE_CHECKING

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader

from centrag.config import Settings, get_settings
from centrag.middleware import RequestContext

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

# --- API Key Header ---
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=True)


def hash_api_key(raw_key: str, pepper: str) -> str:
    """
    Hash an API key for storage.
    Uses SHA256 + pepper (NOT argon2 — we need fast lookup, not slow brute-force resistance).
    The pepper adds entropy beyond the key itself.
    """
    return hashlib.sha256(f"{pepper}:{raw_key}".encode()).hexdigest()


def generate_api_key() -> str:
    """Generate a cryptographically secure API key."""
    return f"centrag_{secrets.token_urlsafe(32)}"


async def resolve_api_key(
    api_key: str = Security(api_key_header),
    settings: Settings = Depends(get_settings),
) -> RequestContext:
    """
    FastAPI dependency: resolve X-API-Key header → RequestContext.

    This is called automatically by FastAPI's DI for every protected route.
    The returned RequestContext is immutable and flows through the entire request.

    In production, this queries PostgreSQL. For scaffolding, it returns a dev context.
    """
    # TODO: Replace with actual DB lookup when models are wired
    # key_hash = hash_api_key(api_key, settings.api_key_hash_pepper)
    # row = await db.execute(
    #     select(ApiKey).join(Team).where(ApiKey.key_hash == key_hash, ApiKey.is_active)
    # )
    # if not row: raise HTTPException(401)

    # --- Dev mode: accept any key starting with "centrag_" ---
    if settings.env == "development" and api_key.startswith("centrag_"):
        return RequestContext(
            team_id="dev-team-001",
            team_name="Development Team",
            api_key_id="dev-key-001",
            tier="enterprise",
            rate_limit=settings.rate_limit_default,
            request_id=str(uuid.uuid4()),
        )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired API key",
    )
