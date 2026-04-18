"""
Graph Retriever — Knowledge Graph based retrieval path.

Traversal-based retrieval to find connected facts across chunks.
This powers the 'Relational Path' in Phase 4 of CentRAG.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from centrag.abstractions.retrieval import RetrievalRequest, RetrievalResponse, RetrievalResult
from centrag.utils.logger import get_logger

if TYPE_CHECKING:
    from centrag.abstractions.graph_store import GraphStoreProtocol
    from centrag.storage.document_store import DocumentStore

logger = get_logger("retrieval.graph")


class GraphRetriever:
    """
    Implements the Relational Path using knowledge graph traversal.

    The WHY:
        Conventional RAG relies on text similarity. Graph RAG relies on
        ontological connections. If a user asks "Who founded X?",
        and the founder's name is in Chunk A but the founding of X is
        in Chunk B, Graph RAG can bridge this gap via the (Founder, Founded, X) triplet.
    """

    def __init__(self, graph_store: GraphStoreProtocol, document_store: DocumentStore):
        self._graph_store = graph_store
        self._doc_store = document_store

    async def retrieve(self, request: RetrievalRequest) -> RetrievalResponse:
        # 1. Identify Seed Entities
        # We use any extracted query intent expansions or the optimized query itself
        seed_terms = []
        if request.query_intent:
            seed_terms.extend(request.query_intent.expansions)
            seed_terms.append(request.query_intent.optimized_query)
        else:
            seed_terms.append(request.query)

        # 2. Extract specific entities via GraphStore search
        # This finds semantic matches to concepts in the graph
        entities = []
        for term in seed_terms:
            found = await self._graph_store.search_entities(request.team_id, request.namespace, term, limit=3)
            entities.extend([e.name for e in found])

        # Deduplicate entities
        entities = list(set(entities))

        # 3. Dynamic Expansion (Multi-Hop)
        depth = request.query_intent.reasoning_hops if request.query_intent else 1
        logger.info("executing_graph_traversal", seed_entities=entities, depth=depth)

        all_relations = []
        for ent in entities:
            relations = await self._graph_store.get_neighbors(request.team_id, request.namespace, ent, depth=depth)
            all_relations.extend(relations)

        if not all_relations:
            return RetrievalResponse(query=request.query, results=[], strategy="graph")

        # Deduplicate and format results
        results = []
        seen_triplets = set()

        for rel in all_relations:
            triplet_key = f"{rel.subject}-{rel.predicate}-{rel.object}"
            if triplet_key in seen_triplets:
                continue
            seen_triplets.add(triplet_key)

            # Form a 'Synthetic Result' from the triplet
            content = f"Relation: {rel.subject} -> {rel.predicate} -> {rel.object}"
            source_doc = rel.metadata.get("source_doc", "Knowledge Graph")

            results.append(
                RetrievalResult(
                    content=content,
                    score=0.9,  # Triplet matches are highly certain
                    doc_id="",
                    filename=source_doc,
                    metadata=rel.metadata,
                )
            )

        return RetrievalResponse(query=request.query, results=results[: request.limit], strategy="graph")
