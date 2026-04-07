"""
TieredCacheOrchestrator — chains L1→L2→L3 cache lookups.

This is the concrete class injected into RetrievalEngine as CacheProtocol.

Design: CHAIN OF RESPONSIBILITY
  - On GET: try L1 → L2 → L3 → return MISS
  - On SET: write to ALL tiers (write-through)
  - On INVALIDATE: clear ALL tiers

This replaces the mixed protocol+implementation in abstractions/cache.py.
"""
from __future__ import annotations

from typing import Any

import structlog

from centrag.abstractions.cache import CacheProtocol, CacheResult, CacheTier

logger = structlog.get_logger("cache.orchestrator")


class TieredCacheOrchestrator:
    """
    Orchestrates tiered cache lookups.

    Usage:
        from centrag.cache.l1_memory import L1InMemoryCache
        from centrag.cache.l2_redis import L2RedisCache

        orchestrator = TieredCacheOrchestrator(
            tiers=[
                L1InMemoryCache(maxsize=512, ttl_seconds=300),
                L2RedisCache(redis_client=redis),
            ]
        )

        # Inject as CacheProtocol into RetrievalEngine
        engine = RetrievalEngine(cache=orchestrator, ...)
    """

    def __init__(self, tiers: list[CacheProtocol] | None = None) -> None:
        self._tiers = tiers or []

    def add_tier(self, cache: CacheProtocol) -> None:
        """Add a cache tier to the chain."""
        self._tiers.append(cache)

    async def get(self, key: str, team_id: str) -> CacheResult:
        """
        Try each tier in order. Return on first hit.

        On HIT at a lower tier (L2/L3), backfill higher tiers (L1)
        for faster subsequent lookups.
        """
        for i, tier in enumerate(self._tiers):
            result = await tier.get(key, team_id)
            if result.hit:
                logger.info(
                    "cache_hit",
                    tier=result.tier.value,
                    tier_index=i,
                    team_id=team_id,
                )
                # Backfill higher tiers
                for j in range(i):
                    await self._tiers[j].set(key, result.value, team_id)
                return result

        return CacheResult(hit=False, tier=CacheTier.MISS)

    async def set(
        self,
        key: str,
        value: Any,
        team_id: str,
        ttl_seconds: int = 3600,
    ) -> None:
        """Write-through: set in ALL tiers."""
        for tier in self._tiers:
            try:
                await tier.set(key, value, team_id, ttl_seconds)
            except Exception as e:
                logger.warning(
                    "cache_set_error",
                    tier=type(tier).__name__,
                    error=str(e),
                )

    async def invalidate(self, team_id: str, namespace: str | None = None) -> int:
        """Invalidate across ALL tiers."""
        total = 0
        for tier in self._tiers:
            try:
                count = await tier.invalidate(team_id, namespace)
                total += count
            except Exception as e:
                logger.warning(
                    "cache_invalidate_error",
                    tier=type(tier).__name__,
                    error=str(e),
                )
        logger.info("cache_invalidated", team_id=team_id, total=total)
        return total
