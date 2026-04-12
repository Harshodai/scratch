"""
SWR Cache Decorator — Stale-While-Revalidate with request deduplication.

Moved from abstractions/cache.py to maintain clean protocol/implementation
separation in the abstractions package.

Architecture Pattern:
    1. Byte-Bounded Caching (prevents container OOMs from huge LLM responses).
    2. Request Deduplication (prevents thundering herd of duplicate LLM API calls).
    3. Stale-While-Revalidate (returns stale item fast while silently refreshing).
"""

from __future__ import annotations

import asyncio
import sys
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any, TypeVar

from cachetools import LRUCache

from centrag.utils.logger import get_logger

logger = get_logger(__name__)

T = TypeVar("T")

DEFAULT_MAX_LIMIT_BYTES = 25 * 1024 * 1024  # 25 MB max memory heap for RAG cache


@dataclass
class SWR_CacheEntry:
    """Wrapper for items stored in the internal LRU to track staleness."""

    value: Any
    timestamp: float
    refreshing: bool


def memoize_with_ttl_async(ttl_seconds: int = 300, max_size_bytes: int = DEFAULT_MAX_LIMIT_BYTES):
    """
    Decorator implementing Stale-While-Revalidate (SWR) and In-Flight Request Collapsing.

    Backend Architecture Pattern:
        1. Byte-Bounded Caching (prevents container OOMs from huge LLM responses).
        2. Request Deduplication (prevents thundering herd of duplicate LLM API calls).
        3. Stale-While-Revalidate (returns stale item fast while silently background refreshing).
    """
    cache = LRUCache(maxsize=max_size_bytes, getsizeof=lambda x: sys.getsizeof(x.value))
    in_flight: dict[str, asyncio.Task] = {}

    def decorator(func: Callable[..., Coroutine[Any, Any, T]]) -> Callable[..., Coroutine[Any, Any, T]]:
        async def wrapper(*args, **kwargs):
            key = str(args) + str(kwargs)
            now = time.time()
            cached = cache.get(key)

            # --- Cold Miss (or Deduplication Wait) ---
            if not cached:
                if key in in_flight:
                    return await in_flight[key]

                task = asyncio.create_task(func(*args, **kwargs))
                in_flight[key] = task
                try:
                    result = await task
                    if in_flight.get(key) is task:
                        cache[key] = SWR_CacheEntry(value=result, timestamp=now, refreshing=False)
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
                        if cache.get(key) is cached:
                            cache[key] = SWR_CacheEntry(value=new_val, timestamp=time.time(), refreshing=False)
                    except asyncio.CancelledError:
                        pass
                    except Exception as e:
                        logger.error("swr_refresh_failed", error=str(e))
                        if cache.get(key) is cached:
                            del cache[key]

                asyncio.create_task(refresh())

            return cached.value

        return wrapper

    return decorator
