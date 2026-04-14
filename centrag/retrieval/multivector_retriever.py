"""
Multivector Retriever — Facet-based retrieval for diverse query types.

Performs fusion search across multiple vector facets (content, summary, keywords).
This powers the 'Facet Path' in Phase 4 of CentRAG.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from centrag.abstractions.retrieval import RetrievalRequest, RetrievalResponse, RetrievalResult
from centrag.utils.logger import get_logger

if TYPE_CHECKING:
    from centrag.abstractions.vectorstore import VectorStoreProtocol, VectorFilter
    from centrag.abstractions.embedder import EmbedderProtocol

logger = get_logger("retrieval.multivector")


class MultivectorRetriever:
    """
    Implements the Facet Path by querying multiple vectors per chunk.
    
    The WHY:
        Different queries require different matching strategies.
        - "What is the policy?" -> Better matched against 'Summary'.
        - "Error code 0x800" -> Better matched against 'Keywords'.
        - "Implementation details" -> Better matched against 'Default' content.
        
        This retriever queries all three and fuses the results.
    """

    def __init__(self, vectorstore: VectorStoreProtocol, embedder: EmbedderProtocol):
        self._vectorstore = vectorstore
        self._embedder = embedder

    async def retrieve(self, request: RetrievalRequest) -> RetrievalResponse:
        """
        1. Generate a single query embedding.
        2. Query Qdrant multiple times using DIFFERENT named vectors.
        3. Fuse the results.
        """
        logger.info("multivector_retrieval_started", query=request.query, team_id=request.team_id)
        
        # 1. Embed query once
        embeddings = await self._embedder.embed_queries([request.query])
        query_vec = embeddings[0]
        
        from centrag.abstractions.vectorstore import VectorFilter
        v_filter = VectorFilter.for_team(request.team_id).with_condition("namespace", request.namespace)
        
        facets = ["", "summary", "keywords"] 
        facet_weights = {"": 1.0, "summary": 1.5, "keywords": 1.2} # Summary gets a boost for conceptual queries
        
        all_results: dict[str, RetrievalResult] = {}
        
        for facet in facets:
            try:
                # Query specific facet
                facet_results = await self._vectorstore.search(
                    collection="centrag", # Should be injected but hardcoded for PoC
                    vector=query_vec,
                    filter=v_filter,
                    limit=request.limit,
                    vector_name=facet
                )
                
                weight = facet_weights.get(facet, 1.0)
                for res in facet_results:
                    chunk_id = res.payload.get("chunk_id", res.id)
                    
                    if chunk_id in all_results:
                        # Simple fusion: update score
                        existing = all_results[chunk_id]
                        new_score = existing.score + (res.score * weight)
                        all_results[chunk_id] = RetrievalResult(
                            content=existing.content,
                            score=new_score,
                            doc_id=existing.doc_id,
                            filename=existing.filename,
                            metadata=existing.metadata
                        )
                    else:
                        all_results[chunk_id] = RetrievalResult(
                            content=res.payload.get("content", ""),
                            score=res.score * weight,
                            doc_id=res.payload.get("doc_id", ""),
                            filename=res.payload.get("filename", ""),
                            metadata=res.payload
                        )
            except Exception as e:
                logger.warning("facet_search_failed", facet=facet, error=str(e))
                
        # Sort by fused score
        final_results = sorted(all_results.values(), key=lambda x: x.score, reverse=True)
        
        return RetrievalResponse(
            query=request.query,
            results=final_results[:request.limit],
            strategy="multivector"
        )
