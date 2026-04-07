"""
Unit tests for in-memory store (temporal memory with versioning).

Tests:
  - add/recall facts
  - team isolation
  - limit enforcement
  - temporal versioning (forget)
"""
from __future__ import annotations

import pytest

from centrag.memory.in_memory_store import InMemoryStore
from centrag.abstractions.memory import MemoryType


@pytest.fixture
def store():
    return InMemoryStore()


class TestInMemoryStore:
    @pytest.mark.asyncio
    async def test_add_and_recall(self, store):
        await store.add(
            content="The sky is blue",
            memory_type=MemoryType.FACT,
            team_id="team1",
        )
        results = await store.recall("sky", team_id="team1", limit=5)
        assert len(results) >= 1
        assert any("sky" in r.content.lower() for r in results)

    @pytest.mark.asyncio
    async def test_team_isolation(self, store):
        await store.add(
            content="Secret A data",
            memory_type=MemoryType.FACT,
            team_id="team_a",
        )
        await store.add(
            content="Secret B data",
            memory_type=MemoryType.FACT,
            team_id="team_b",
        )

        results_a = await store.recall("secret", team_id="team_a", limit=10)
        results_b = await store.recall("secret", team_id="team_b", limit=10)

        # Each team should only see their own memories
        contents_a = [r.content for r in results_a]
        contents_b = [r.content for r in results_b]
        assert "Secret A data" in contents_a
        assert "Secret B data" not in contents_a
        assert "Secret B data" in contents_b
        assert "Secret A data" not in contents_b

    @pytest.mark.asyncio
    async def test_limit_respected(self, store):
        for i in range(10):
            await store.add(
                content=f"Memory number {i}",
                memory_type=MemoryType.FACT,
                team_id="t1",
            )
        results = await store.recall("memory", team_id="t1", limit=3)
        assert len(results) <= 3

    @pytest.mark.asyncio
    async def test_empty_recall(self, store):
        results = await store.recall("anything", team_id="nonexistent", limit=5)
        assert results == []

    @pytest.mark.asyncio
    async def test_forget_makes_memory_non_current(self, store):
        entry = await store.add(
            content="Temporary fact",
            memory_type=MemoryType.FACT,
            team_id="team1",
        )
        await store.forget(entry.id, "team1")

        # Recalled memories should exclude forgotten ones
        results = await store.recall("temporary", team_id="team1", limit=10)
        assert all(r.id != entry.id for r in results)

    @pytest.mark.asyncio
    async def test_memory_types(self, store):
        await store.add("User likes tables", MemoryType.PREFERENCE, "t1")
        await store.add("DB is Postgres", MemoryType.FACT, "t1")

        all_memories = await store.get_all("t1")
        types = {m.memory_type for m in all_memories}
        assert MemoryType.PREFERENCE in types
        assert MemoryType.FACT in types
