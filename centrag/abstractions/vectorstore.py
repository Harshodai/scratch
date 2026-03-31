"""
VectorStore abstraction — handles vector CRUD + filtered search.

SOLID: Single Responsibility — only vector operations, no business logic.
SOLID: Liskov Substitution — QdrantStore, PineconeStore, PgVectorStore
       can replace each other without breaking the retrieval engine.

Design Pattern: REPOSITORY PATTERN
    - Encapsulates data access behind a clean interface
    - Business logic never knows if it's talking to Qdrant or Pinecone
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class VectorSearchResult:
    """Immutable search result. frozen=True prevents accidental mutation."""

    id: str
    score: float
    payload: dict[str, Any] = field(default_factory=dict)
    vector: list[float] | None = None


@dataclass(frozen=True)
class VectorFilter:
    """Type-safe filter builder instead of raw dicts."""

    must: list[dict[str, Any]] = field(default_factory=list)
    must_not: list[dict[str, Any]] = field(default_factory=list)

    @staticmethod
    def for_team(team_id: str) -> VectorFilter:
        """Factory: create a filter scoped to a single team."""
        return VectorFilter(
            must=[{"key": "team_id", "match": {"value": team_id}}]
        )

    def with_condition(self, key: str, value: Any) -> VectorFilter:
        """Builder: add a condition (returns new VectorFilter — immutable)."""
        return VectorFilter(
            must=[*self.must, {"key": key, "match": {"value": value}}],
            must_not=list(self.must_not),
        )


@runtime_checkable
class VectorStoreProtocol(Protocol):
    """Contract for all vector database implementations."""

    async def upsert(
        self,
        collection: str,
        id: str,
        vector: list[float],
        payload: dict[str, Any],
    ) -> None:
        """Insert or update a single vector with payload."""
        ...

    async def upsert_batch(
        self,
        collection: str,
        ids: list[str],
        vectors: list[list[float]],
        payloads: list[dict[str, Any]],
    ) -> None:
        """Batch upsert for ingestion throughput."""
        ...

    async def search(
        self,
        collection: str,
        vector: list[float],
        filter: VectorFilter,
        limit: int = 10,
        score_threshold: float | None = None,
    ) -> list[VectorSearchResult]:
        """Filtered vector search. ALWAYS requires a team_id filter."""
        ...

    async def delete_by_filter(
        self,
        collection: str,
        filter: VectorFilter,
    ) -> int:
        """Delete vectors matching filter. Returns count deleted."""
        ...

    async def set_payload(
        self,
        collection: str,
        ids: list[str],
        payload: dict[str, Any],
    ) -> None:
        """Update payload on existing vectors (e.g., mark is_current=False)."""
        ...
