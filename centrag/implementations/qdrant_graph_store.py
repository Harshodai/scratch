"""
Qdrant Graph Store — Pure Vector implementation of GraphStoreProtocol.

The WHY:
    Conventional Graph DBs (Neo4j) add infrastructure complexity. By storing 
    knowledge triplets as vectors in Qdrant, we achieve semantic graph traversal 
    with zero additional databases. We use payload filtering to simulate 
    relational 'edges' while benefiting from vector similarity for 'soft matching' 
    of entity names.

SOLID:
    - SRP: Only handles graph persistence and traversal logic in Qdrant.
    - Liskov: Fully replaces SQLiteGraphStore without affecting retrieval callers.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import TYPE_CHECKING, Any

from centrag.abstractions.graph_store import Entity, Relation
from centrag.utils.logger import get_logger

if TYPE_CHECKING:
    from centrag.abstractions.llm import LLMProtocol
    from centrag.implementations.qdrant_vectorstore import QdrantVectorStore

logger = get_logger("implementations.graph.qdrant")


class QdrantGraphStore:
    """
    Graph Storage using pure vector search logic in Qdrant.
    """

    def __init__(
        self,
        vector_store: QdrantVectorStore,
        embedder: Any,  # EmbedderProtocol
        collection_name: str = "centrag_graph",
        sibling_limit: int = 10
    ):
        self._store = vector_store
        self._embedder = embedder
        self._collection = collection_name
        self._sibling_limit = sibling_limit
        self._initialized = False

    async def _ensure_collection(self):
        """Lazy-initialize the graph collection with proper indices."""
        if self._initialized:
            return

        client = self._store._get_client()
        from qdrant_client.models import Distance, VectorParams
        
        collections = client.get_collections().collections
        exists = any(c.name == self._collection for c in collections)
        
        if not exists:
            # Triplet collection: vectors represent the whole relation
            client.create_collection(
                collection_name=self._collection,
                vectors_config=VectorParams(
                    size=self._store._dimension, 
                    distance=Distance.COSINE
                )
            )
            # Indicies for fast structural traversal (exact matching)
            client.create_payload_index(self._collection, "team_id", field_schema="keyword")
            client.create_payload_index(self._collection, "namespace", field_schema="keyword")
            client.create_payload_index(self._collection, "subject", field_schema="keyword")
            client.create_payload_index(self._collection, "object", field_schema="keyword")
            
            logger.info("graph_collection_created", name=self._collection)
        
        self._initialized = True

    async def add_triplets(self, team_id: str, namespace: str, triplets: list[Relation]) -> None:
        """Embed and store triplets in Qdrant."""
        await self._ensure_collection()
        
        points = []
        for t in triplets:
            # Create a semantic string for embedding the relationship
            triplet_str = f"{t.subject} {t.predicate} {t.object}"
            vector = await self._embedder.embed_query(triplet_str)
            
            point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{team_id}:{namespace}:{triplet_str}"))
            
            points.append({
                "id": point_id,
                "vector": vector,
                "payload": {
                    "team_id": team_id,
                    "namespace": namespace,
                    "subject": t.subject.lower(), # Normalize for structural lookup
                    "predicate": t.predicate,
                    "object": t.object.lower(),
                    "metadata": t.metadata,
                    "original_subject": t.subject,
                    "original_object": t.object
                }
            })

        # Batch upsert via the underlying client
        client = self._store._get_client()
        from qdrant_client.models import PointStruct
        
        client.upsert(
            collection_name=self._collection,
            points=[
                PointStruct(id=p["id"], vector=p["vector"], payload=p["payload"])
                for p in points
            ]
        )
        logger.info("triplets_upserted", count=len(triplets), team_id=team_id)

    async def get_neighbors(self, team_id: str, namespace: str, entity_name: str, depth: int = 1) -> list[Relation]:
        """
        Recursive multi-hop traversal in Qdrant using payload filters.
        """
        await self._ensure_collection()
        client = self._store._get_client()
        from qdrant_client.models import Filter, FieldCondition, MatchValue
        
        visited_nodes = {entity_name.lower()}
        all_relations: dict[str, Relation] = {}
        current_layer_nodes = [entity_name.lower()]

        for d in range(depth):
            if not current_layer_nodes:
                break
                
            next_layer_nodes = []
            tasks = []
            
            # Fan-out: search for all triplets where subject or object is in current layer
            for node in current_layer_nodes:
                # We use scroll for exact structural links
                filter_cond = Filter(
                    must=[
                        FieldCondition(key="team_id", match=MatchValue(value=team_id)),
                        FieldCondition(key="namespace", match=MatchValue(value=namespace)),
                    ],
                    should=[
                        FieldCondition(key="subject", match=MatchValue(value=node)),
                        FieldCondition(key="object", match=MatchValue(value=node)),
                    ]
                )
                tasks.append(client.scroll(
                    collection_name=self._collection,
                    scroll_filter=filter_cond,
                    limit=self._sibling_limit,
                    with_payload=True
                ))
            
            responses = await asyncio.gather(*[asyncio.to_thread(lambda t=t: t) for t in tasks])
            
            for points, _ in responses:
                for p in points:
                    payload = p.payload
                    rel_key = f"{payload['subject']}->{payload['predicate']}->{payload['object']}"
                    
                    if rel_key not in all_relations:
                        all_relations[rel_key] = Relation(
                            subject=payload["original_subject"],
                            predicate=payload["predicate"],
                            object=payload["original_object"],
                            metadata=payload.get("metadata", {})
                        )
                        
                        # Identify next nodes to traverse
                        subj = payload["subject"]
                        obj = payload["object"]
                        
                        if subj not in visited_nodes:
                            visited_nodes.add(subj)
                            next_layer_nodes.append(subj)
                        if obj not in visited_nodes:
                            visited_nodes.add(obj)
                            next_layer_nodes.append(obj)
            
            current_layer_nodes = next_layer_nodes[:self._sibling_limit * 2] # Safety cap
            
        return list(all_relations.values())

    async def search_entities(self, team_id: str, namespace: str, query: str, limit: int = 5) -> list[Entity]:
        """
        Find entities matching a query. 
        In this pure-vector approach, we search for relates triplets and extract entities.
        """
        await self._ensure_collection()
        
        # Start with a semantic search for similar triplets
        query_vector = await self._embedder.embed_query(query)
        
        from qdrant_client.models import Filter, FieldCondition, MatchValue
        
        results = await self._store.search(
            collection=self._collection,
            vector=query_vector,
            filter=VectorFilter.for_team(team_id).with_condition("namespace", namespace),
            limit=limit
        )
        
        # Extract unique entities from found triplets
        entities = {}
        for r in results:
            # We treat the relevant triplet's subject/object as candidate entities
            subj = r.payload.get("original_subject", "")
            if subj and subj not in entities:
                entities[subj] = Entity(name=subj)
            
            obj = r.payload.get("original_object", "")
            if obj and obj not in entities:
                entities[obj] = Entity(name=obj)
                
        return list(entities.values())[:limit]

    async def delete_namespace(self, team_id: str, namespace: str) -> None:
        """Clear graph data for a namespace."""
        await self._ensure_collection()
        client = self._store._get_client()
        from qdrant_client.models import Filter, FieldCondition, MatchValue
        
        client.delete(
            collection_name=self._collection,
            points_filter=Filter(
                must=[
                    FieldCondition(key="team_id", match=MatchValue(value=team_id)),
                    FieldCondition(key="namespace", match=MatchValue(value=namespace)),
                ]
            )
        )
