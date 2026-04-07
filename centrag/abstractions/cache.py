"""
Cache abstraction — tiered caching backend.

SOLID: Interface Segregation — cache only does get/set/invalidate.
       No retrieval logic, no embedding logic.

Design Pattern: STRATEGY PATTERN (each tier is a strategy)
    + CHAIN OF RESPONSIBILITY (tiers checked L1 → L2 → L3 in order)
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol, runtime_checkable


class CacheTier(str, Enum):
    """Which cache layer served the response (for metrics)."""

    L1_IN_PROCESS = "L1"   # LRU in-memory — ~0ms
    L2_EXACT = "L2"        # Redis SHA256 key — ~2ms
    L3_SEMANTIC = "L3"     # Qdrant similarity — ~15ms
    MISS = "MISS"          # Full RAG pipeline — ~2000ms


@dataclass(frozen=True)
class CacheResult:
    """Immutable cache lookup result."""

    hit: bool
    tier: CacheTier
    value: Any | None = None


@runtime_checkable
class CacheProtocol(Protocol):
    """Contract for individual cache backends (each tier implements this)."""

    async def get(self, key: str, team_id: str) -> CacheResult:
        """Look up a cached response."""
        ...

    async def set(
        self,
        key: str,
        value: Any,
        team_id: str,
        ttl_seconds: int = 3600,
    ) -> None:
        """Store a response in cache."""
        ...

    async def invalidate(self, team_id: str, namespace: str | None = None) -> int:
        """
        Invalidate cache entries for a team (optionally scoped to namespace).
        Returns count of entries invalidated.

        Called when: documents are re-ingested, team settings change.
        """
        ...

