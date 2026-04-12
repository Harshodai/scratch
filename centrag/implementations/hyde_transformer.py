"""
HyDE Transformer — Hypothetical Document Embeddings.
Generates a hypothetical answer to the query to improve semantic search alignment.

ADR Alignment: Advanced RAG Techniques (HyDE) — improves retrieval for questions
where the query and the answer live in different semantic spaces.
"""

from __future__ import annotations

import json
import re

from centrag.abstractions.llm import LLMProtocol
from centrag.abstractions.query_transformer import QueryIntent, QueryTransformerProtocol
from centrag.abstractions.vectorstore import VectorFilter
from centrag.utils.logger import get_logger

logger = get_logger("implementations.hyde_transformer")


class HyDETransformer(QueryTransformerProtocol):
    """
    Implements HyDE (Hypothetical Document Embeddings).
    It generates a 'hypothetical document' (a potential answer) from the query,
    then uses that answer as the embedding source for vector retrieval.
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
