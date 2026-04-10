"""
LLM Query Extractor — uses an LLM to parse natural language into structured search intents.

SOLID: Single Responsibility — transforms raw queries into optimized queries + vector filters.
"""
from __future__ import annotations

import json
import re
from typing import Any

from centrag.utils.logger import get_logger

from centrag.abstractions.llm import LLMProtocol
from centrag.abstractions.query_transformer import QueryIntent, QueryTransformerProtocol
from centrag.abstractions.vectorstore import VectorFilter

logger = get_logger("implementations.query_transformer")


class LLMQueryExtractor(QueryTransformerProtocol):
    """
    Implements a fast-pass LLM extraction pattern to structurally parse a user query.
    Extracts explicit metadata (like years, authors) into VectorFilters, and rewrites
    the query to optimize semantic search (stripping out the filter keywords).
    """

    def __init__(self, llm: LLMProtocol) -> None:
        self._llm = llm

    async def transform(self, raw_query: str, team_id: str) -> QueryIntent:
        system_prompt = (
            "You are a search intent parser. Analyze the user's query and extract JSON matching this perfectly:\n"
            "{\n"
            '  "optimized_query": "The core semantic question WITHOUT the metadata filters",\n'
            '  "expansions": ["synonym", "broader category"],\n'
            '  "filters": {"exact_key": "exact_value"}\n'
            "}\n"
            "If there are no explicit filters in the query, return an empty filters dictionary.\n"
            "Output ONLY valid JSON. No markdown formatting."
        )

        try:
            response = await self._llm.generate(
                prompt=raw_query,
                context=[],
                system_prompt=system_prompt,
                temperature=0.0,
                max_tokens=500,
            )
            
            # Clean up potential markdown formatting if the model ignored instructions
            content = response.content.strip()
            # Use regex to find the first comprehensive JSON object mapping bounds
            match = re.search(r'\{.*\}', content, re.DOTALL)
            if not match:
                raise ValueError("No JSON object detected in response.")
            json_str = match.group(0)
                
            parsed = json.loads(json_str)
            
            # Build VectorFilter
            v_filter = VectorFilter.for_team(team_id)
            filters_dict: dict[str, Any] = parsed.get("filters", {})
            for k, v in filters_dict.items():
                v_filter = v_filter.with_condition(k, v)

            intent = QueryIntent(
                optimized_query=parsed.get("optimized_query", raw_query),
                expansions=parsed.get("expansions", []),
                extracted_filter=v_filter,  # v_filter explicitly contains the team_id base requirement
            )
            
            logger.info(
                "query_transformed",
                original=raw_query,
                optimized=intent.optimized_query,
                filters=filters_dict
            )
            return intent
            
        except Exception as e:
            logger.error("query_extraction_failed", error=str(e))
            # Fallback gracefully
            return QueryIntent(
                optimized_query=raw_query,
                expansions=[],
                extracted_filter=None
            )
