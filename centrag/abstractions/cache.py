"""
Cache abstraction — tiered caching backend.

SOLID: Interface Segregation — cache only does get/set/invalidate.
       No retrieval logic, no embedding logic.

Design Pattern: STRATEGY PATTERN (each tier is a strategy)
    + CHAIN OF RESPONSIBILITY (tiers checked L1 → L2 → L3 in order)
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable


class CacheTier(StrEnum):
    """Which cache layer served the response (for metrics).

    The WHY:
        Performance profiling in RAG requires knowing exactly where
        latency "savings" come from. By tagging every hit with a tier,
        we can visualize the efficiency of L1 vs L2 in the AgentsView dashboard.

    Levels:
        L1_IN_PROCESS: The fastest tier, stored in local RAM.
        L2_EXACT: Distributed Redis storage for exact query matches.
        L3_SEMANTIC: High-fidelity similarity matching via Vector DB.
    """

    L1_IN_PROCESS = "L1"  # LRU in-memory — ~0ms
    L2_EXACT = "L2"  # Redis SHA256 key — ~2ms
    L3_SEMANTIC = "L3"  # Qdrant similarity — ~15ms
    MISS = "MISS"  # Full RAG pipeline — ~2000ms


@dataclass(frozen=True)
class CacheResult:
    """Immutable cache lookup result.

    The WHY:
        Using a dedicated Result object instead of returning None
        allows us to distinguish between a "Null value stored in cache"
        and a "Cache Miss," ensuring pipeline stability.

    Attributes:
        hit: Whether the data was found in the cache.
        tier: The specific tier that provided the data (or MISS).
        value: The actual cached data (if hit is True).
    """

    hit: bool
    tier: CacheTier
    value: Any | None = None


@runtime_checkable
class CacheProtocol(Protocol):
    """Contract for individual cache backends.

    The WHY:
        Allows the CacheOrchestrator to treat L1 (Local) and L2 (Redis)
        identically. This implementation of the STRATEGY PATTERN
        enables "Chain of Responsibility" logic for multi-tier fallthrough.

    Isolation:
        All operations are team-scoped to ensure no data leakage
        between different tenants in the CentRAG platform.
    """

    async def get(self, key: str, team_id: str, namespace: str | None = None) -> CacheResult:
        """Look up a cached response by key.

        Args:
            key: The unique identifier (usually a SHA256 hash of the prompt).
            team_id: The unique tenant UUID for isolation.
            namespace: Optional grouping (e.g., 'embeddings', 'generator').

        Returns:
            CacheResult: A result object indicating hit/miss and the value.
        """
        ...

    async def set(
        self,
        key: str,
        value: Any,
        team_id: str,
        ttl_seconds: int = 3600,
        namespace: str | None = None,
    ) -> None:
        """Store a response in the cache with a specific TTL.

        Args:
            key: Unique identifier for the data.
            value: The serializable data to store.
            team_id: Tenant ID for scope isolation.
            ttl_seconds: Time-to-Live in seconds (Default: 1 hour).
            namespace: Optional logical category.
        """
        ...

    async def invalidate(self, team_id: str, namespace: str | None = None) -> int:
        """Invalidate cache entries for a team to maintain data freshness.

        The WHY:
            When a team updates their documents or settings, the old
            cached knowledge becomes "stale." This method clears that
            knowledge to force the system to regenerate grounded answers.

        Args:
            team_id: The tenant whose cache should be cleared.
            namespace: Optional category to clear without affecting others.

        Returns:
            int: The number of entries successfully invalidated.
        """
        ...
