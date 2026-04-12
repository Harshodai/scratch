"""
Request Context — Immutable per-request context injected at auth layer.

┌─────────────────────────────────────────────────────────────────────┐
│  CRITICAL SECURITY PATTERN: Immutable Request Context               │
│                                                                     │
│  Once created at the auth middleware, this object CANNOT be         │
│  modified. team_id flows through every layer (retrieval, cache,     │
│  memory, audit) without any code being able to tamper with it.      │
│                                                                     │
│  This is the FOUNDATION of namespace isolation.                     │
│  Every database query, every vector search, every cache key         │
│  MUST use ctx.team_id. If they don't, you have a security bug.     │
└─────────────────────────────────────────────────────────────────────┘

Design Pattern: VALUE OBJECT (DDD) — identity-less, immutable, equality by value.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timezone


@dataclass(frozen=True)
class RequestContext:
    """
    Immutable context created at the auth boundary.
    frozen=True prevents ANY code from modifying team_id after creation.
    """

    team_id: str
    team_name: str
    api_key_id: str
    tier: str = "standard"  # "standard" | "premium" | "enterprise"
    rate_limit: int = 60  # requests/minute for this team
    request_id: str = ""  # unique per request (for tracing)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        """Validation — fail fast if context is invalid."""
        if not self.team_id:
            raise ValueError("team_id cannot be empty")
        if not self.api_key_id:
            raise ValueError("api_key_id cannot be empty")
