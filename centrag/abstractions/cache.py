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


import sys
import time
import asyncio
from typing import TypeVar, Callable, Coroutine, Dict

from cachetools import LRUCache
import structlog

logger = structlog.get_logger(__name__)

T = TypeVar("T")

DEFAULT_MAX_LIMIT_BYTES = 25 * 1024 * 1024  # 25 MB max memory heap for RAG cache

@dataclass
class SWR_CacheEntry:
    """Wrapper for items stored in the internal LRU to track staleness."""
    value: Any
    timestamp: float
    refreshing: bool


def memoize_with_ttl_async(
    ttl_seconds: int = 300,
    max_size_bytes: int = DEFAULT_MAX_LIMIT_BYTES
):
    """
    Decorator implementing Stale-While-Revalidate (SWR) and In-Flight Request Collapsing.
    
    Backend Architecture Pattern:
        1. Byte-Bounded Caching (prevents container OOMs from huge LLM responses).
        2. Request Deduplication (prevents thundering herd of duplicate LLM API calls).
        3. Stale-While-Revalidate (returns stale item fast while silently background refreshing).
    """
    # Bound the dictionary physically by the byte-size of the serialized responses.
    cache = LRUCache(maxsize=max_size_bytes, getsizeof=lambda x: sys.getsizeof(x.value))
    in_flight: Dict[str, asyncio.Task] = {}

    def decorator(func: Callable[..., Coroutine[Any, Any, T]]) -> Callable[..., Coroutine[Any, Any, T]]:
        async def wrapper(*args, **kwargs):
            key = str(args) + str(kwargs)  # Serialize args to deterministic hash key
            now = time.time()
            cached = cache.get(key)

            # --- Cold Miss (or Deduplication Wait) ---
            if not cached:
                if key in in_flight:
                    # In-flight Request Collapsing: Join the already running generation task
                    return await in_flight[key]

                # Start the literal generative process
                task = asyncio.create_task(func(*args, **kwargs))
                in_flight[key] = task
                try:
                    result = await task
                    if in_flight.get(key) is task:
                        cache[key] = SWR_CacheEntry(
                            value=result,
                            timestamp=now,
                            refreshing=False
                        )
                    return result
                finally:
                    if in_flight.get(key) is task:
                        del in_flight[key]

            # --- Stale-While-Revalidate (SWR) ---
            if now - cached.timestamp > ttl_seconds and not cached.refreshing:
                cached.refreshing = True

                async def refresh():
                    try:
                        new_val = await func(*args, **kwargs)
                        # Ensure cache hasn't been explicitly cleared during generation
                        if cache.get(key) is cached:
                            cache[key] = SWR_CacheEntry(
                                value=new_val,
                                timestamp=time.time(),
                                refreshing=False
                            )
                    except asyncio.CancelledError:
                        pass
                    except Exception as e:
                        logger.error("swr_refresh_failed", error=str(e))
                        # Drop stale cache entirely if unable to auto-refresh
                        if cache.get(key) is cached:
                            del cache[key]

                # Fire and forget the background revalidation task
                asyncio.create_task(refresh())

            # Return (potentially stale) cache hit instantly
            return cached.value

        return wrapper
    return decorator
