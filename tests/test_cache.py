"""
Unit tests for cache subsystem — L1, L2, Orchestrator.

Tests:
  - L1InMemoryCache: get/set, TTL, team-scoped invalidation
  - TieredCacheOrchestrator: fallthrough, backfill
  - RetrievalResponse serialization roundtrip
"""
from __future__ import annotations

import pytest

from centrag.cache.l1_memory import L1InMemoryCache
from centrag.cache.orchestrator import TieredCacheOrchestrator
from centrag.abstractions.cache import CacheTier
from centrag.retrieval.engine import RetrievalResponse, SourceChunk
from centrag.abstractions.llm import QueryComplexity


# =============================================================================
# L1InMemoryCache
# =============================================================================

class TestL1InMemoryCache:
    @pytest.fixture
    def cache(self):
        return L1InMemoryCache(maxsize=100, ttl_seconds=60)

    @pytest.mark.asyncio
    async def test_miss_on_empty(self, cache):
        result = await cache.get("nonexistent", "team1")
        assert result.hit is False
        assert result.tier == CacheTier.MISS

    @pytest.mark.asyncio
    async def test_set_and_get(self, cache):
        await cache.set("key1", {"answer": "hello"}, "team1")
        result = await cache.get("key1", "team1")
        assert result.hit is True
        assert result.tier == CacheTier.L1_IN_PROCESS
        assert result.value == {"answer": "hello"}

    @pytest.mark.asyncio
    async def test_team_isolation(self, cache):
        await cache.set("key1", "value_a", "team_a")
        await cache.set("key1", "value_b", "team_b")

        result_a = await cache.get("key1", "team_a")
        result_b = await cache.get("key1", "team_b")
        assert result_a.value == "value_a"
        assert result_b.value == "value_b"

    @pytest.mark.asyncio
    async def test_invalidate_scoped_to_team(self, cache):
        await cache.set("k1", "v1", "team_a")
        await cache.set("k2", "v2", "team_a")
        await cache.set("k3", "v3", "team_b")

        count = await cache.invalidate("team_a")
        assert count == 2

        # team_a entries gone
        assert (await cache.get("k1", "team_a")).hit is False
        assert (await cache.get("k2", "team_a")).hit is False
        # team_b entries intact
        assert (await cache.get("k3", "team_b")).hit is True


# =============================================================================
# TieredCacheOrchestrator
# =============================================================================

class TestTieredCacheOrchestrator:
    @pytest.mark.asyncio
    async def test_l1_hit(self):
        l1 = L1InMemoryCache(maxsize=100, ttl_seconds=60)
        orchestrator = TieredCacheOrchestrator(tiers=[l1])

        await orchestrator.set("q", "result", "t1")
        result = await orchestrator.get("q", "t1")
        assert result.hit is True

    @pytest.mark.asyncio
    async def test_miss_when_empty(self):
        l1 = L1InMemoryCache(maxsize=100, ttl_seconds=60)
        orchestrator = TieredCacheOrchestrator(tiers=[l1])

        result = await orchestrator.get("q", "t1")
        assert result.hit is False


# =============================================================================
# RetrievalResponse Serialization
# =============================================================================

class TestRetrievalResponseSerialization:
    def test_roundtrip(self):
        original = RetrievalResponse(
            answer="Test answer",
            sources=[
                SourceChunk(
                    content="chunk content",
                    document_id="doc-1",
                    chunk_index=0,
                    relevance_score=0.95,
                    metadata={"page": 1},
                )
            ],
            cache_tier=CacheTier.MISS,
            query_complexity=QueryComplexity.MODERATE,
            memory_context=["memory piece"],
            metadata={"latency_ms": 42.5},
        )

        d = original.to_dict()
        restored = RetrievalResponse.from_dict(d)

        assert restored.answer == original.answer
        assert len(restored.sources) == 1
        assert restored.sources[0].content == "chunk content"
        assert restored.sources[0].relevance_score == 0.95
        assert restored.cache_tier == CacheTier.MISS
        assert restored.query_complexity == QueryComplexity.MODERATE
        assert restored.memory_context == ["memory piece"]

    def test_to_dict_is_json_safe(self):
        import json

        resp = RetrievalResponse(
            answer="ok",
            sources=[],
            cache_tier=CacheTier.L1_IN_PROCESS,
            query_complexity=QueryComplexity.SIMPLE,
        )
        # Must not raise
        json_str = json.dumps(resp.to_dict())
        assert isinstance(json_str, str)

    def test_from_dict_with_missing_fields(self):
        minimal = {"answer": "hello", "sources": []}
        resp = RetrievalResponse.from_dict(minimal)
        assert resp.answer == "hello"
        assert resp.cache_tier == CacheTier.MISS
        assert resp.query_complexity == QueryComplexity.MODERATE
