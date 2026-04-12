"""
Qdrant Vector Store — Production VectorStoreProtocol implementation.

VECTOR PATH ONLY: This module handles all vector CRUD operations for the
similarity-based retrieval path.

Uses the qdrant-client SDK to communicate with a Qdrant instance (local
or cloud). Auto-creates collections with HNSW configuration optimized
for RAG workloads.

Design Pattern: REPOSITORY — encapsulates Qdrant SDK behind VectorStoreProtocol.

SOLID: Single Responsibility — only vector storage. No retrieval logic.
SOLID: Liskov Substitution — drop-in replacement for NoOpVectorStore.
SOLID: Dependency Inversion — engine depends on Protocol, not on Qdrant SDK.
"""

from __future__ import annotations

from typing import Any

from centrag.abstractions.vectorstore import (
    VectorFilter,
    VectorSearchResult,
)
from centrag.utils.logger import get_logger

logger = get_logger("implementations.qdrant")


class QdrantVectorStore:
    """Production VectorStore implementation backed by Qdrant.

    The WHY:
        Vectors alone are just coordinates. In an enterprise system,
        we need a store that supports Hybrid Search (Dense + Sparse)
        and strict Multi-Tenant filtering. Qdrant allows us to
        store the text alongside the vector (Payload-Based Retrieval),
        ensuring that every search is payload-filtered by `team_id`
        before the similarity calculation is even performed.

    Design Patterns:
        - REPOSITORY PATTERN: Encapsulates the complex Qdrant
          filtering DSL behind a clean Python interface.
        - HYBRID FUSION: Implicitly supports Reciprocal Rank Fusion (RRF)
          when both dense and sparse vectors are provided.

    Usage:
        store = QdrantVectorStore(url="...", dimension=1536)
        # Filters are MANDATORY for production multi-tenancy
        results = await store.search(..., filter=VectorFilter.for_team("t-123"))
    """

    def __init__(
        self,
        url: str | None = "http://localhost:6333",
        api_key: str | None = None,
        collection_name: str = "centrag",
        dimension: int = 1024,
        on_disk: bool = False,
        path: str | None = None,
    ) -> None:
        self._url = url
        self._api_key = api_key
        self._collection = collection_name
        self._dimension = dimension
        self._on_disk = on_disk
        self._path = path
        self._client = None  # Lazy-loaded

    def _get_client(self):
        """Lazy-load the Qdrant client."""
        if self._client is None:
            try:
                from qdrant_client import QdrantClient
                from qdrant_client.models import Distance, Modifier, SparseVectorParams, VectorParams

                self._client = QdrantClient(
                    url=self._url if not self._path else None,
                    path=self._path,
                    api_key=self._api_key,
                    timeout=30,
                )

                # Auto-create collection if it doesn't exist
                collections = self._client.get_collections().collections
                exists = any(c.name == self._collection for c in collections)
                if not exists:
                    self._client.create_collection(
                        collection_name=self._collection,
                        vectors_config=VectorParams(
                            size=self._dimension,
                            distance=Distance.COSINE,
                            on_disk=self._on_disk,
                        ),
                        sparse_vectors_config={"sparse": SparseVectorParams(modifier=Modifier.NONE)},
                    )
                    logger.info(
                        "qdrant_collection_created",
                        name=self._collection,
                        dimension=self._dimension,
                    )

                logger.info(
                    "qdrant_connected",
                    url=self._url,
                    collection=self._collection,
                )

            except ImportError:
                raise ImportError(
                    "qdrant-client is required for QdrantVectorStore. Install with: pip install qdrant-client"
                )

        return self._client

    def _build_filter(self, filter: VectorFilter) -> dict[str, Any] | None:
        """Convert VectorFilter to Qdrant filter format."""
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        conditions = []
        for cond in filter.must:
            conditions.append(
                FieldCondition(
                    key=cond["key"],
                    match=MatchValue(value=cond["match"]["value"]),
                )
            )

        must_not = []
        for cond in filter.must_not:
            must_not.append(
                FieldCondition(
                    key=cond["key"],
                    match=MatchValue(value=cond["match"]["value"]),
                )
            )

        if not conditions and not must_not:
            return None

        return Filter(
            must=conditions if conditions else None,
            must_not=must_not if must_not else None,
        )

    async def upsert(
        self,
        collection: str,
        id: str,
        vector: list[float],
        payload: dict[str, Any],
        sparse_vector: dict[int, float] | None = None,
    ) -> None:
        """Insert or update a single vector with payload."""
        from qdrant_client.models import PointStruct, SparseVector

        # If a sparse vector is provided, Qdrant allows passing a dict of vectors
        vector_data: Any = vector
        if sparse_vector:
            vector_data = {
                "": vector,  # "" is the default unnamed dense vector
                "sparse": SparseVector(indices=list(sparse_vector.keys()), values=list(sparse_vector.values())),
            }

        client = self._get_client()
        client.upsert(
            collection_name=collection,
            points=[PointStruct(id=id, vector=vector_data, payload=payload)],
        )

    async def upsert_batch(
        self,
        collection: str,
        ids: list[str],
        vectors: list[list[float]],
        payloads: list[dict[str, Any]],
        sparse_vectors: list[dict[int, float] | None] | None = None,
    ) -> None:
        """Batch upsert for ingestion throughput."""
        from qdrant_client.models import PointStruct, SparseVector

        client = self._get_client()
        points = []
        for i, (id_val, vec, pay) in enumerate(zip(ids, vectors, payloads, strict=False)):
            vector_data: Any = vec
            if sparse_vectors and i < len(sparse_vectors) and sparse_vectors[i]:
                sv = sparse_vectors[i]
                assert sv is not None
                vector_data = {"": vec, "sparse": SparseVector(indices=list(sv.keys()), values=list(sv.values()))}
            points.append(PointStruct(id=id_val, vector=vector_data, payload=pay))

        # Qdrant batch size limit is ~100 points per request
        batch_size = 100
        for i in range(0, len(points), batch_size):
            batch = points[i : i + batch_size]
            client.upsert(collection_name=collection, points=batch)

        logger.info(
            "vectors_upserted",
            collection=collection,
            count=len(points),
        )

    async def search(
        self,
        collection: str,
        vector: list[float],
        filter: VectorFilter,
        limit: int = 10,
        score_threshold: float | None = None,
        sparse_vector: dict[int, float] | None = None,
    ) -> list[VectorSearchResult]:
        """Filtered vector search. ALWAYS requires a team_id filter."""
        from qdrant_client.models import Prefetch, SparseVector

        client = self._get_client()

        # Mandatory Multi-Tenant Security Check
        has_team_filter = any(c.get("key") == "team_id" for c in filter.must)
        if not has_team_filter:
            logger.error("security_violation_missing_team_id", collection=collection)
            raise ValueError(
                f"FATAL: Vector search in collection '{collection}' attempted without a 'team_id' filter. "
                "This violates multi-tenant isolation policies."
            )

        qdrant_filter = self._build_filter(filter)

        if sparse_vector:
            # Qdrant Hybrid Search (RRF Native) using Prefetch
            # We prefetch both dense and sparse, then Qdrant merges them.
            prefetch = [
                Prefetch(
                    query=vector,
                    using="",
                    limit=limit * 2,
                    filter=qdrant_filter,
                ),
                Prefetch(
                    query=SparseVector(indices=list(sparse_vector.keys()), values=list(sparse_vector.values())),
                    using="sparse",
                    limit=limit * 2,
                    filter=qdrant_filter,
                ),
            ]

            results = client.query_points(
                collection_name=collection,
                prefetch=prefetch,
                query=None,  # None triggers Qdrant's automatic Fusion RRF
                limit=limit,
                score_threshold=score_threshold,
            ).points
        else:
            # Legacy Dense-only search
            results = client.search(
                collection_name=collection,
                query_vector=vector,
                query_filter=qdrant_filter,
                limit=limit,
                score_threshold=score_threshold,
            )

        return [
            VectorSearchResult(
                id=str(r.id),
                score=r.score,
                payload=r.payload or {},
            )
            for r in results
        ]

    async def delete_by_filter(
        self,
        collection: str,
        filter: VectorFilter,
    ) -> int:
        """Delete vectors matching filter. Returns count deleted."""
        from qdrant_client.models import FilterSelector

        client = self._get_client()
        qdrant_filter = self._build_filter(filter)

        if qdrant_filter is None:
            return 0

        # Count before delete
        count_before = client.count(
            collection_name=collection,
            count_filter=qdrant_filter,
        ).count

        client.delete(
            collection_name=collection,
            points_selector=FilterSelector(filter=qdrant_filter),
        )

        return count_before

    async def set_payload(
        self,
        collection: str,
        ids: list[str],
        payload: dict[str, Any],
    ) -> None:
        """Update payload on existing vectors."""
        client = self._get_client()
        client.set_payload(
            collection_name=collection,
            payload=payload,
            points=ids,
        )
