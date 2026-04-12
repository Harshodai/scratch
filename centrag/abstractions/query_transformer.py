"""
Query Transformer Abstraction — converts natural language to structured search intents.

SOLID: Single Responsibility — only parses user intent into system filters and optimized text.
SOLID: Liskov Substitution — standard protocol for LLM-based extractors, regex parsers, etc.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from centrag.abstractions.vectorstore import VectorFilter


@dataclass(frozen=True)
class QueryIntent:
    """The structured result of a query transformation."""

    # The original query rewritten to remove filter noise and optimize semantic search
    optimized_query: str

    # Optional list of query expansions (synonyms, abstract concepts) useful for CRAG
    expansions: list[str] = field(default_factory=list)

    # Optional metadata filters extracted from the natural language
    # e.g., "for year 2024" -> VectorFilter applying {"year": 2024}
    extracted_filter: VectorFilter | None = None


@runtime_checkable
class QueryTransformerProtocol(Protocol):
    """Contract for extracting filters and semantics from a raw user query."""

    async def transform(
        self,
        raw_query: str,
        team_id: str,
    ) -> QueryIntent:
        """
        Analyze the raw query, extract metadata filters, and rewrite it for search.

        Args:
            raw_query: The natural language string from the user.
            team_id: Used to scope the root of the extracted filter.

        Returns:
            A QueryIntent dataclass containing structured search parameters.
        """
        ...
