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
    """Immutable result from a vector database search.

    The WHY:
        Provides a standardized container for raw database responses.
        `score` is essential for RAG confidence-gating, and `payload`
        carries the document metadata (UUID, team_id, chunk_index)
        needed for final result synthesis.
    """

    id: str
    score: float
    payload: dict[str, Any] = field(default_factory=dict)
    vector: list[float] | None = None


@dataclass(frozen=True)
class VectorFilter:
    """Helper for constructing database-agnostic search filters.

    The WHY:
        Simplifies the creation of complex "Where" clauses. While this
        class organizes filter criteria, runtime enforcement must still
        be handled by the specific VectorStore implementation to ensure
        mandatory team isolation.
    """

    must: list[dict[str, Any]] = field(default_factory=list)
    must_not: list[dict[str, Any]] = field(default_factory=list)

    @staticmethod
    def for_team(team_id: str) -> VectorFilter:
        """Factory: create a filter scoped to a single team.

        The WHY:
            Mandatory security gate. All retrieval queries must be
            scoped to a team to maintain SOC2-compliant data isolation.
        """
        return VectorFilter(must=[{"key": "team_id", "match": {"value": team_id}}])

    def with_condition(self, key: str, value: Any) -> VectorFilter:
        """Builder: add a condition (returns new VectorFilter — immutable).

        Usage:
            >>> combined_filter = VectorFilter.for_team(tid).with_condition("status", "live")
        """
        return VectorFilter(
            must=[*self.must, {"key": key, "match": {"value": value}}],
            must_not=list(self.must_not),
        )


@runtime_checkable
class VectorStoreProtocol(Protocol):
    """Contract for all vector database implementations.

    The WHY:
        Implements the REPOSITORY PATTERN. Whether we use Qdrant
        (local/prod) or Pinecone (SaaS), the `RetrievalEngine`
        logic remains identical, making the platform future-proof.
    """

    async def upsert(
        self,
        collection: str,
        id: str,
        vector: list[float] | dict[str, list[float]],
        payload: dict[str, Any],
        sparse_vector: dict[int, float] | None = None,
    ) -> None:
        """Insert or update a single vector with associated data.

        The WHY:
            Support for `vector` as a dict enables Named Vectors (Multivector).
            Support for `sparse_vector` enables Hybrid Search
            capabilities inside the same upsert transaction.
        """
        ...

    async def upsert_batch(
        self,
        collection: str,
        ids: list[str],
        vectors: list[list[float]] | list[dict[str, list[float]]],
        payloads: list[dict[str, Any]],
        sparse_vectors: list[dict[int, float] | None] | None = None,
    ) -> None:
        """Batch upsert to maximize ingestion throughput.

        Optimization:
            Reduces network overhead by grouping multiple vectors
            into a single database call. Handles both single and 
            named vectors for Multivector/Facet search.
        """
        ...

    async def search(
        self,
        collection: str,
        vector: list[float],
        filter: VectorFilter,
        limit: int = 10,
        score_threshold: float | None = None,
        sparse_vector: dict[int, float] | None = None,
        vector_name: str | None = None,
    ) -> list[VectorSearchResult]:
        """Perform a context-aware vector search.

        The WHY:
            Accepts both dense and sparse vectors to perform
            "Reciprocal Rank Fusion" (Hybrid Search) if the store
            supports it. `vector_name` enables Facet/Multivector search.

        Args:
            vector: The dense embedding (float list).
            filter: Mandatory VectorFilter for team isolation.
            sparse_vector: Optional keyword-importance map.
            vector_name: Optional name of the vector to query (e.g. "summary").

        Returns:
            list[VectorSearchResult]: Top-K results sorted by score.
        """
        ...

    async def delete_by_filter(
        self,
        collection: str,
        filter: VectorFilter,
    ) -> int:
        """Atomic deletion of vectors matching specific criteria.

        Returns:
            int: Number of records successfully purged.
        """
        ...

    async def set_payload(
        self,
        collection: str,
        ids: list[str],
        payload: dict[str, Any],
    ) -> None:
        """Partial update of vector metadata without re-indexing the vector.

        The WHY:
            Used for updating 'is_current' flags or ingestion
            status without the compute cost of embedding generation.
        """
        ...
