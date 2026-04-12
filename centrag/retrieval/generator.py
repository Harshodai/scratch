"""
Two-Pass Generator — Implements grounding-first hierarchical reasoning.

As specified in the technical documentation:
- Pass 1: Extract atomic facts from each chunk with mandatory quotes.
- Pass 2: Synthesize a final answer citing chunk IDs and page numbers.

This strategy is used for COMPLEX queries (summarization, comparison).
"""

from __future__ import annotations

import asyncio
import hashlib
from typing import TYPE_CHECKING, Protocol

from centrag.utils.logger import get_logger

if TYPE_CHECKING:
    from centrag.abstractions.cache import CacheProtocol
    from centrag.abstractions.llm import LLMProtocol, LLMResponse
    from centrag.abstractions.retrieval import SourceChunk

logger = get_logger("retrieval.generator")


class GeneratorProtocol(Protocol):
    """Protocol for LLM generation strategies.

    The WHY:
        Defines the interface for how CentRAG synthesizes final
        answers. By decoupling the implementation, we can switch
        between a "Standard" single-pass generator and a "Two-Pass"
        reasoning generator based on query complexity.
    """

    async def generate_response(
        self,
        query: str,
        sources: list[SourceChunk],
        system_prompt: str | None = None,
    ) -> LLMResponse: ...


class TwoPassGenerator:
    """Grounding-first hierarchical reasoning pipeline.

    The WHY:
        Complex RAG queries (comparisons, summaries) often fail because
        the LLM tries to reason and retrieve simultaneously, leading
        to hallucinations. This generator enforces a Two-Pass pattern:
        1. Pass 1 (Grounding): Extract atomic facts + quotes from each chunk.
        2. Pass 2 (Synthesis): Merge those facts into a final answer.
        This "Thought-before-Action" pattern significantly increases precision.

    Design Patterns:
        - TWO-PASS REASONING: Atomic extraction → Final synthesis.
        - PARALLEL EXECUTION: Fact extraction happens concurrently across chunks.
    """

    def __init__(self, llm: LLMProtocol, cache: CacheProtocol | None = None) -> None:
        self._llm = llm
        self._cache = cache

    async def generate_response(
        self,
        query: str,
        sources: list[SourceChunk],
        team_id: str = "default",
        system_prompt: str | None = None,
    ) -> LLMResponse:
        """
        Main entry point for two-pass generation.
        """
        # STEP 1: Pass 1 — Atomic Fact Extraction (Parallel)
        fact_tasks = [self._extract_facts_from_chunk(query, chunk, team_id=team_id) for chunk in sources]

        # Limit concurrency but allow parallel extraction
        extracted_facts = await asyncio.gather(*fact_tasks)

        # Filter out empty or low-value facts
        valid_facts = [f for f in extracted_facts if f.strip()]

        # STEP 2: Pass 2 — Synthesis
        # Combine all atomic facts into a unified, grounded answer.
        full_context = "\n\n".join(valid_facts)

        synthesis_prompt = f"""
You are a technical assistant. Using ONLY the ATOMIC FACTS provided below, answer the user query.

USER QUERY: {query}

ATOMIC FACTS:
{full_context}

REQUIREMENTS:
1. Synthesize a concise, accurate answer.
2. Use citations in the format [Chunk#X, pY] where X is the chunk index and Y is the page.
3. If facts conflict, highlight the discrepancy.
4. If the facts do not answer the query, state "I do not have enough information."
        """

        logger.info("pass_2_synthesis_started", fact_count=len(valid_facts))

        response = await self._llm.generate(
            prompt=synthesis_prompt,
            system_prompt=system_prompt or "You are a grounding-first technical expert.",
        )

        return response

    async def _extract_facts_from_chunk(
        self,
        query: str,
        chunk: SourceChunk,
        team_id: str = "default",
    ) -> str:
        """
        Pass 1: Extract atomic facts from a single chunk.
        Uses namespaced caching (Tier 2-style) to prevent re-processing.
        """
        chunk_id = chunk.chunk_index
        page_num = chunk.metadata.get("page_number", "unknown")

        # 1. Check cache first
        if self._cache:
            # Hash query for key
            query_hash = hashlib.sha256(query.lower().strip().encode()).hexdigest()[:16]
            cache_key = f"{chunk.document_id}:{chunk.chunk_index}:{query_hash}"

            cached = await self._cache.get(cache_key, team_id=team_id, namespace="chunk_summaries")
            if cached.hit:
                return cached.value

        prompt = f"""
Analyze the technical document chunk below and extract exactly 2-3 atomic facts relevant to the query.

QUERY: {query}
CHUNK [ID: {chunk_id}, Page: {page_num}]:
\"\"\"
{chunk.content}
\"\"\"

OUTPUT FORMAT:
- [Fact description] (Citation: [Chunk#{chunk_id}, p{page_num}]) "Direct Quote"
        """

        # Use a lower temperature for extraction to avoid hallucination
        response = await self._llm.generate(
            prompt=prompt,
            system_prompt="You are a meticulous fact-extractor.",
        )

        fact_text = response.content

        # 2. Store in cache
        if self._cache:
            await self._cache.set(
                cache_key,
                fact_text,
                team_id=team_id,
                namespace="chunk_summaries",
                ttl_seconds=86400 * 7,  # Cache for 7 days
            )

        return fact_text
