# centrag/cache/__init__.py
"""
Cache Subsystem — Tiered caching with L1→L2→L3 orchestration.

Separates cache PROTOCOL (in centrag.abstractions.cache) from
IMPLEMENTATIONS (in this package).

Architecture:
  TieredCacheOrchestrator → L1 InMemory → L2 Redis → L3 Semantic → MISS
"""

from centrag.cache.orchestrator import TieredCacheOrchestrator
from centrag.cache.swr import memoize_with_ttl_async

__all__ = ["TieredCacheOrchestrator", "memoize_with_ttl_async"]

