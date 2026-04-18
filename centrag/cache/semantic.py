"""
Semantic Cache — Similarity-based caching (L3 tier).

Following GPTCache standards:
- SSDataManager Pattern: Separates Vector indexing from Scalar data storage.
- Similarity Verification: Uses distance-based gating.
- Multi-Tenant Isolation: Strict team_id filtering on both Vector and Scalar layers.

Design Pattern: STRATEGY PATTERN (implements CacheProtocol).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np

from centrag.abstractions.cache import CacheProtocol, CacheResult, CacheTier
from centrag.abstractions.vectorstore import VectorFilter, VectorStoreProtocol
from centrag.utils.logger import get_logger

if TYPE_CHECKING:
    from centrag.abstractions.embedder import EmbedderProtocol

logger = get_logger("cache.semantic")


class SemanticCache:
    """
    GPTCache-inspired Semantic Caching implementation for CentRAG.

    The WHY:
        Exact-match caches (L2 Redis) fail when queries are slightly rephrased.
        Semantic caching converts queries into vectors and uses a Vector DB
        to find "conceptually identical" queries, significantly increasing
        hit rates for common enterprise assistant topics.

    Architecture (SSDataManager):
        - Vector Store: Holds embeddings of previous queries (Search Index).
        - Scalar Store: Holds the actual LLM responses (Data Storage).
        - similarity_threshold: Minimum cosine similarity to accept a hit.
    """

    def __init__(
        self,
        vector_store: VectorStoreProtocol,
        scalar_store: CacheProtocol,
        embedder: EmbedderProtocol,
        collection_name: str = "centrag_semantic_cache",
        similarity_threshold: float = 0.95,
    ) -> None:
        # GPTCache pattern: validate threshold range (see gptcache/config.py line 51)
        if not 0.0 <= similarity_threshold <= 1.0:
            raise ValueError(f"Invalid similarity_threshold {similarity_threshold}, reasonable range: 0.0-1.0")
        self._vector_store = vector_store
        self._scalar_store = scalar_store
        self._embedder = embedder
        self._collection = collection_name
        self._threshold = similarity_threshold

    def _normalize(self, vector: list[float]) -> list[float]:
        """L2 Normalization (GPTCache Requirement)."""
        vec = np.array(vector)
        norm = np.linalg.norm(vec)
        if norm == 0:
            return vector
        return (vec / norm).tolist()

    async def get(self, key: str, team_id: str, namespace: str | None = None) -> CacheResult:
        """
        Semantic lookup:
        1. Embed the incoming prompt (key).
        2. Search Vector Store for top match with team_id filter.
        3. If score > threshold, extract payload_id.
        4. Fetch payload from Scalar Store.
        """
        try:
            # 1. Embed query
            query_vector = await self._embedder.embed_query(key)
            query_vector = self._normalize(query_vector)

            # 2. Vector Search (Multi-tenant)
            #    Use .with_condition() instead of .must.append() to preserve
            #    VectorFilter immutability (frozen dataclass).
            search_filter = VectorFilter.for_team(team_id)
            if namespace:
                search_filter = search_filter.with_condition("namespace", namespace)

            results = await self._vector_store.search(
                collection=self._collection,
                vector=query_vector,
                filter=search_filter,
                limit=1,
            )

            if not results:
                return CacheResult(hit=False, tier=CacheTier.MISS)

            match = results[0]

            # 3. Similarity Threshold Check (Distance-based for Qdrant Cosine)
            # Qdrant score is 0..1 for Cosine (Higher is better)
            if match.score < self._threshold:
                logger.debug(
                    "semantic_cache_miss_low_score", score=match.score, threshold=self._threshold, team_id=team_id
                )
                return CacheResult(hit=False, tier=CacheTier.MISS)

            # 4. Fetch Scalar Payload
            scalar_key = match.payload.get("scalar_key")
            if not scalar_key:
                return CacheResult(hit=False, tier=CacheTier.MISS)

            scalar_result = await self._scalar_store.get(key=scalar_key, team_id=team_id, namespace=namespace)

            if scalar_result.hit:
                logger.info("semantic_cache_hit", score=match.score, team_id=team_id, tier=CacheTier.L3_SEMANTIC.value)
                return CacheResult(hit=True, tier=CacheTier.L3_SEMANTIC, value=scalar_result.value)

        except Exception as e:
            logger.error("semantic_cache_get_error", error=str(e), team_id=team_id)

        return CacheResult(hit=False, tier=CacheTier.MISS)

    async def set(
        self,
        key: str,
        value: Any,
        team_id: str,
        ttl_seconds: int = 3600,
        namespace: str | None = None,
    ) -> None:
        """
        Semantic storage:
        1. Write value to Scalar Store first.
        2. Embed prompt (key).
        3. Store Vector + ScalarKey in Vector Store.
        """
        try:
            # 1. Store in Scalar (Redis)
            # Use the key as the anchor (cached responses are often large)
            await self._scalar_store.set(
                key=key, value=value, team_id=team_id, ttl_seconds=ttl_seconds, namespace=namespace
            )

            # 2. Embed query
            query_vector = await self._embedder.embed_query(key)
            query_vector = self._normalize(query_vector)

            # 3. Store in Vector DB
            # Note: Qdrant ID must be UUID-like or int. We use the SHA256 of the prompt.
            import hashlib

            id_str = f"{team_id}:{namespace or ''}:{key}"
            point_id = hashlib.sha256(id_str.encode()).hexdigest()

            payload = {
                "team_id": team_id,
                "namespace": namespace,
                "scalar_key": key,  # We use the raw prompt as the scalar key for Redis
                "original_text": key[:100],  # For debugging/dashboards
            }

            await self._vector_store.upsert(
                collection=self._collection, id=point_id, vector=query_vector, payload=payload
            )

            logger.debug("semantic_cache_set_complete", team_id=team_id)

        except Exception as e:
            logger.error("semantic_cache_set_error", error=str(e), team_id=team_id)

    async def invalidate(self, team_id: str, namespace: str | None = None) -> int:
        """
        Invalidation is tricky for semantic cache.
        We delete from Vector Store (the index).
        Scalar entries will eventually TTL out of Redis.
        """
        try:
            search_filter = VectorFilter.for_team(team_id)
            if namespace:
                search_filter = search_filter.with_condition("namespace", namespace)

            count = await self._vector_store.delete_by_filter(
                collection=self._collection,
                filter=search_filter,
            )
            return count
        except Exception as e:
            logger.error("semantic_cache_invalidate_error", error=str(e), team_id=team_id)
            return 0
