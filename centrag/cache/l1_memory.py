"""
L1 In-Memory Cache — LRU with TTL.

Fastest cache tier (~0ms). In-process, so NOT shared across instances.
Best for: hot queries that repeat within a single server instance.

This moves the implementation logic that was mixed into
centrag/abstractions/cache.py (violating protocol/impl separation).
"""
from __future__ import annotations

import hashlib
import time
from collections import defaultdict
from typing import Any

from cachetools import TTLCache

from centrag.abstractions.cache import CacheProtocol, CacheResult, CacheTier

import structlog

logger = structlog.get_logger("cache.l1")


class L1InMemoryCache:
    """
    In-process LRU cache with TTL eviction.

    Implements CacheProtocol for the L1 tier.
    Uses cachetools.TTLCache for automatic expiry.
    Tracks team → keys mapping for scoped invalidation.
    """

    def __init__(
        self,
        maxsize: int = 1024,
        ttl_seconds: int = 300,  # 5 minutes default
    ) -> None:
        self._cache: TTLCache = TTLCache(maxsize=maxsize, ttl=ttl_seconds)
        self._default_ttl = ttl_seconds
        # Track which cache keys belong to which team for scoped invalidation
        self._team_keys: dict[str, set[str]] = defaultdict(set)

    def _make_key(self, key: str, team_id: str) -> str:
        """Deterministic cache key scoped by team."""
        raw = f"{team_id}:{key}"
        return hashlib.sha256(raw.encode()).hexdigest()

    async def get(self, key: str, team_id: str) -> CacheResult:
        cache_key = self._make_key(key, team_id)
        value = self._cache.get(cache_key)
        if value is not None:
            logger.debug("l1_cache_hit", team_id=team_id, key_hash=cache_key[:12])
            return CacheResult(hit=True, tier=CacheTier.L1_IN_PROCESS, value=value)
        return CacheResult(hit=False, tier=CacheTier.MISS)

    async def set(
        self,
        key: str,
        value: Any,
        team_id: str,
        ttl_seconds: int = 3600,
    ) -> None:
        cache_key = self._make_key(key, team_id)
        self._cache[cache_key] = value
        self._team_keys[team_id].add(cache_key)
        logger.debug("l1_cache_set", team_id=team_id, key_hash=cache_key[:12])

    async def invalidate(self, team_id: str, namespace: str | None = None) -> int:
        """Invalidate entries for a specific team (not the whole cache)."""
        keys_to_remove = self._team_keys.pop(team_id, set())
        count = 0
        for cache_key in keys_to_remove:
            if cache_key in self._cache:
                del self._cache[cache_key]
                count += 1
        logger.info("l1_cache_invalidated", team_id=team_id, count=count)
        return count
