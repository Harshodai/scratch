"""
NoOp VectorStore — In-memory vector store for development/testing.

Stores vectors in a dict and performs brute-force cosine similarity search.
Supports all VectorStoreProtocol operations including filtered search.

Production replacement: QdrantVectorStore, PineconeStore, PgVectorStore.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from centrag.abstractions.vectorstore import (
    VectorFilter,
    VectorSearchResult,
)
from centrag.utils.logger import get_logger

logger = get_logger("implementations.vectorstore.noop")


@dataclass
class _StoredVector:
    """Internal representation of a stored vector."""

    id: str
    vector: list[float]
    payload: dict[str, Any]
    collection: str


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two vectors."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _matches_filter(payload: dict[str, Any], vf: VectorFilter) -> bool:
    """Check if a payload matches a VectorFilter."""
    # Check all 'must' conditions
    for condition in vf.must:
        key = condition.get("key", "")
        match_val = condition.get("match", {}).get("value")
        if payload.get(key) != match_val:
            return False
    # Check all 'must_not' conditions
    for condition in vf.must_not:
        key = condition.get("key", "")
        match_val = condition.get("match", {}).get("value")
        if payload.get(key) == match_val:
            return False
    return True


class NoOpVectorStore:
    """Zero-Infrastructure "Sandbox" Vector Store.

    The WHY:
        Setting up a production vector database (like Qdrant or
        Pinecone) can be a hurdle for new developers or CI/CD
        environments. The NoOpVectorStore provides a "Sandbox"
        that implements the full `VectorStoreProtocol` in-memory.
        It supports filtering, searching (via brute-force cosine
        similarity), and batching, allowing the system to run
        completely detached from any external infrastructure.

    Design Pattern:
        IN-MEMORY REPOSITORY — All data is stored in a Python
        dictionary and is volatile (lost on restart).

    Usage:
        store = NoOpVectorStore()
        # Full protocol support without the 6333 port requirement
        await store.upsert("docs", "id1", [0.1, 0.2], {"team_id": "t1"})
    """

    def __init__(self) -> None:
        self._store: dict[str, _StoredVector] = {}  # id → StoredVector

    async def upsert(
        self,
        collection: str,
        id: str,
        vector: list[float],
        payload: dict[str, Any],
    ) -> None:
        """Insert or update a single vector."""
        composite_key = f"{collection}:{id}"
        self._store[composite_key] = _StoredVector(id=id, vector=vector, payload=payload, collection=collection)
        logger.debug("noop_upsert", collection=collection, id=id)

    async def upsert_batch(
        self,
        collection: str,
        ids: list[str],
        vectors: list[list[float]],
        payloads: list[dict[str, Any]],
    ) -> None:
        """Batch upsert."""
        for vid, vec, pay in zip(ids, vectors, payloads, strict=True):
            await self.upsert(collection, vid, vec, pay)
        logger.debug("noop_upsert_batch", collection=collection, count=len(ids))

    async def search(
        self,
        collection: str,
        vector: list[float],
        filter: VectorFilter,
        limit: int = 10,
        score_threshold: float | None = None,
    ) -> list[VectorSearchResult]:
        """Brute-force cosine similarity search with filtering."""
        candidates: list[tuple[float, _StoredVector]] = []

        for stored in self._store.values():
            if stored.collection != collection:
                continue
            if not _matches_filter(stored.payload, filter):
                continue
            score = _cosine_similarity(vector, stored.vector)
            if score_threshold is not None and score < score_threshold:
                continue
            candidates.append((score, stored))

        # Sort by score descending
        candidates.sort(key=lambda x: x[0], reverse=True)

        results = [
            VectorSearchResult(
                id=stored.id,
                score=score,
                payload=stored.payload,
            )
            for score, stored in candidates[:limit]
        ]

        logger.debug(
            "noop_search",
            collection=collection,
            candidates=len(candidates),
            returned=len(results),
        )
        return results

    async def delete_by_filter(
        self,
        collection: str,
        filter: VectorFilter,
    ) -> int:
        """Delete vectors matching filter."""
        to_delete = [
            key
            for key, stored in self._store.items()
            if stored.collection == collection and _matches_filter(stored.payload, filter)
        ]
        for key in to_delete:
            del self._store[key]
        logger.debug("noop_delete", collection=collection, count=len(to_delete))
        return len(to_delete)

    async def set_payload(
        self,
        collection: str,
        ids: list[str],
        payload: dict[str, Any],
    ) -> None:
        """Update payload on existing vectors."""
        for vid in ids:
            composite_key = f"{collection}:{vid}"
            if composite_key in self._store:
                self._store[composite_key].payload.update(payload)
        logger.debug("noop_set_payload", collection=collection, count=len(ids))

    # -- Convenience methods for testing --

    def count(self, collection: str | None = None) -> int:
        """Count stored vectors, optionally by collection."""
        if collection is None:
            return len(self._store)
        return sum(1 for s in self._store.values() if s.collection == collection)

    def clear(self, collection: str | None = None) -> None:
        """Clear all or collection-specific vectors."""
        if collection is None:
            self._store.clear()
        else:
            keys = [k for k, v in self._store.items() if v.collection == collection]
            for k in keys:
                del self._store[k]
