"""
Multivector Enricher — Facet-based metadata generation for chunks.

Generates 'summaries' and 'keywords' for chunks to provide alternate retrieval paths.
This is the heart of the 'Facet Path' in Phase 4 of CentRAG.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from centrag.utils.logger import get_logger

if TYPE_CHECKING:
    from centrag.abstractions.chunker import ChunkResult
    from centrag.abstractions.llm import LLMProtocol

logger = get_logger("extraction.multivector")


class MultivectorEnricher:
    """
    LLM-powered enrichment for Multivector retrieval.
    
    The WHY:
        Standard embeddings match based on semantic similarity of the full text.
        However, users often search for technical names (keywords) or high-level
        concepts (summaries). By creating separate vectors for these facets,
        we significantly improve recall for diverse query types.
    """

    def __init__(self, llm: LLMProtocol):
        self._llm = llm

    async def enrich(self, chunks: list[ChunkResult]) -> list[ChunkResult]:
        """
        Processes a list of chunks and adds 'summary' and 'keywords' to their metadata.
        """
        enriched_chunks = []
        
        for chunk in chunks:
            try:
                # We do a single LLM call to get both for token efficiency
                system_prompt = (
                    "You are a Metadata Enrichment Agent. For the given text chunk, generate:\n"
                    "1. A 1-sentence concise summary of the main point.\n"
                    "2. A comma-separated list of the 5 most important technical keywords/entities.\n"
                    "Output ONLY a JSON object with keys 'summary' and 'keywords'."
                )
                
                response = await self._llm.generate(
                    prompt=f"Text: {chunk.content[:1000]}",
                    context=[],
                    system_prompt=system_prompt,
                    temperature=0.0
                )
                
                import re
                content = response.content.strip()
                # Robust regex-based JSON extraction to handle LLM conversational slop
                match = re.search(r"\{.*\}", content, re.DOTALL)
                if not match:
                    logger.warning("no_json_found_in_response", content=content[:100])
                    # Fallback to empty values
                    metadata = {}
                else:
                    clean_content = match.group(0)
                    metadata = json.loads(clean_content)
                
                # Update chunk metadata
                chunk.metadata["facet_summary"] = metadata.get("summary", "")
                chunk.metadata["facet_keywords"] = metadata.get("keywords", "")
                
                enriched_chunks.append(chunk)
            except Exception as e:
                logger.warning("multivector_enrichment_failed", chunk_index=chunk.chunk_index, error=str(e))
                enriched_chunks.append(chunk)
                
        return enriched_chunks
