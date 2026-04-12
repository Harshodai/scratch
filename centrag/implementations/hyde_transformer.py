"""
HyDE Transformer — Hypothetical Document Embeddings.
Generates a hypothetical answer to the query to improve semantic search alignment.

ADR Alignment: Advanced RAG Techniques (HyDE) — improves retrieval for questions
where the query and the answer live in different semantic spaces.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

from centrag.abstractions.query_transformer import QueryIntent, QueryTransformerProtocol
from centrag.abstractions.vectorstore import VectorFilter
from centrag.utils.logger import get_logger

if TYPE_CHECKING:
    from centrag.abstractions.llm import LLMProtocol

logger = get_logger("implementations.hyde_transformer")


class HyDETransformer(QueryTransformerProtocol):
    """HyDE (Hypothetical Document Embeddings) Query Transformer.

    The WHY:
        Semantic search (vector retrieval) often fails because user
        queries (short, interrogative) look very different from answer
        chunks (long, declarative). This "Semantic Gap" causes
        retrieval misses. HyDE solves this by using an LLM to generate
        a "Fake Answer" (a hypothetical document) first. We then
        embed this fake answer and use its vector to find real,
        declarative chunks that look just like it.

    Design Pattern:
        TRANSFORMER — Implements the `QueryTransformerProtocol`
        to morph the user's intent into a retrieval-optimized form.

    Usage:
        transformer = HyDETransformer(llm)
        intent = await transformer.transform("How do I reset my API key?", "team_1")
        # intent.optimized_query contains the hypothetical answer paragraph
    """

    def __init__(self, llm: LLMProtocol) -> None:
        self._llm = llm

    async def transform(self, raw_query: str, team_id: str) -> QueryIntent:
        system_prompt = (
            "You are a hypothetical document generator for a RAG system. "
            "Given a user query, write a single paragraph that would be an ideal, "
            "highly relevant answer found in a knowledge base. "
            "Do not include conversational filler or explain what you are doing. "
            "Focus only on stating facts that would likely answer the query."
        )

        try:
            # Stage 1: Generate Hypothetical Answer
            response = await self._llm.generate(
                prompt=f"Query: {raw_query}",
                context=[],
                system_prompt=system_prompt,
                temperature=0.7,  # Higher temperature for diverse hypothetical docs
                max_tokens=300,
            )

            hypothetical_doc = response.content.strip()

            # Stage 2: Extract Filters (using a secondary fast prompt or combined)
            # For efficiency in this implementation, we combine HyDE with basic filter extraction
            filter_prompt = (
                "Analyze the original query and extract any metadata filters as JSON.\n"
                "Query: {raw_query}\n"
                'Return ONLY JSON: {"filters": {"key": "value"}, "expansions": []}'
            ).replace("{raw_query}", raw_query)

            filter_response = await self._llm.generate(
                prompt=filter_prompt,
                context=[],
                system_prompt="You are a JSON metadata extractor. Output ONLY valid JSON.",
                temperature=0.0,
                max_tokens=200,
            )

            # Parse filters
            match = re.search(r"\{.*\}", filter_response.content, re.DOTALL)
            parsed = json.loads(match.group(0)) if match else {}

            v_filter = VectorFilter.for_team(team_id)
            filters_dict = parsed.get("filters", {})
            for k, v in filters_dict.items():
                v_filter = v_filter.with_condition(k, v)

            # Semantic search query is now the hypothetical document
            # Expansions include the original query to ensure broad recall
            intent = QueryIntent(
                optimized_query=hypothetical_doc,
                expansions=[raw_query] + parsed.get("expansions", []),
                extracted_filter=v_filter,
            )

            logger.info(
                "hyde_transformation_complete", raw_query=raw_query, hyde_len=len(hypothetical_doc), team_id=team_id
            )
            return intent

        except Exception as e:
            logger.error("hyde_transformation_failed", error=str(e))
            # Fallback to raw query
            return QueryIntent(
                optimized_query=raw_query, expansions=[], extracted_filter=VectorFilter.for_team(team_id)
            )
