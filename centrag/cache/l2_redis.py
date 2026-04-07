"""
L2 Redis Cache — Exact-match distributed cache.

Shared across all server instances via Redis. ~2ms latency.
Best for: cross-instance cache sharing, session stickiness not required.

Stub implementation — requires Redis connection at runtime.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

import structlog

from centrag.abstractions.cache import CacheProtocol, CacheResult, CacheTier

logger = structlog.get_logger("cache.l2")


class L2RedisCache:
    """
    Redis-backed exact-match cache.

    Implements CacheProtocol for the L2 tier.

    NOTE: This is a working stub. In production, inject the Redis
    client via the app's lifespan manager (centrag.app.py).
    """

    def __init__(self, redis_client: Any = None, key_prefix: str = "centrag:cache:") -> None:
        self._redis = redis_client
        self._prefix = key_prefix

    def _make_key(self, key: str, team_id: str) -> str:
        raw = f"{team_id}:{key}"
        return f"{self._prefix}{hashlib.sha256(raw.encode()).hexdigest()}"

    async def get(self, key: str, team_id: str) -> CacheResult:
        if self._redis is None:
            return CacheResult(hit=False, tier=CacheTier.MISS)

        cache_key = self._make_key(key, team_id)
        try:
            value = await self._redis.get(cache_key)
            if value is not None:
                logger.debug("l2_cache_hit", team_id=team_id)
                return CacheResult(
                    hit=True,
                    tier=CacheTier.L2_EXACT,
                    value=json.loads(value),
                )
        except Exception as e:
            logger.warning("l2_cache_error", error=str(e))

        return CacheResult(hit=False, tier=CacheTier.MISS)

    async def set(
        self,
        key: str,
        value: Any,
        team_id: str,
        ttl_seconds: int = 3600,
    ) -> None:
        if self._redis is None:
            return

        cache_key = self._make_key(key, team_id)
        try:
            await self._redis.set(
                cache_key,
                json.dumps(value, default=str),
                ex=ttl_seconds,
            )
            logger.debug("l2_cache_set", team_id=team_id, ttl=ttl_seconds)
        except Exception as e:
            logger.warning("l2_cache_set_error", error=str(e))

    async def invalidate(self, team_id: str, namespace: str | None = None) -> int:
        if self._redis is None:
            return 0

        pattern = f"{self._prefix}*"
        try:
            keys = []
            async for key in self._redis.scan_iter(match=pattern):
                keys.append(key)
            if keys:
                await self._redis.delete(*keys)
            logger.info("l2_cache_invalidated", team_id=team_id, count=len(keys))
            return len(keys)
        except Exception as e:
            logger.warning("l2_cache_invalidate_error", error=str(e))
            return 0
