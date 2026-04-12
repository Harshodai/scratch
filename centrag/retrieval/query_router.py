"""
Query Router — Decides which retrieval path to use per query.

SHARED INFRASTRUCTURE: Routes queries to the optimal retrieval path.

Routing logic:
    - target_doc_id + tree available → PAGEINDEX (vectorless reasoning)
    - No target_doc_id (cross-doc search) → VECTOR (similarity search)
    - mode="hybrid" → HYBRID (both paths + RRF fusion)
    - mode="auto" → Router decides based on query + doc availability

Design Pattern: STRATEGY PATTERN — the router selects the retrieval strategy.

SOLID: Single Responsibility — only routing decisions. No retrieval logic.
SOLID: Open/Closed — add new routing heuristics without modifying retrieval code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from centrag.storage.document_store import DocumentStore
from centrag.utils.logger import get_logger

logger = get_logger("retrieval.router")


class RetrievalPath(str, Enum):
    """The retrieval path selected by the router."""

    VECTOR = "vector"  # Similarity-based (embeddings + Qdrant)
    PAGEINDEX = "pageindex"  # Reasoning-based (tree navigation via LLM)
    HYBRID = "hybrid"  # Both paths + Reciprocal Rank Fusion


@dataclass(frozen=True)
class RoutingDecision:
    """
    Immutable routing decision from the QueryRouter.

    Explains WHY a path was chosen (for observability and debugging).
    """

    path: RetrievalPath
    reason: str
    confidence: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)


class QueryRouter:
    """
    Decides which retrieval path to use for a given query.

    SHARED INFRASTRUCTURE — sits between the API and retrieval paths.

    Routing rules (in priority order):
        1. Explicit mode override (user chose "pageindex" or "vector")
        2. target_doc_id + tree available → PAGEINDEX
        3. No target_doc_id → VECTOR (cross-doc search)
        4. Complex query + tree available → HYBRID

    Usage:
        router = QueryRouter(document_store=store)
        decision = await router.route(
            query="What are the key risks?",
            mode="auto",
            target_doc_id="uuid",
            team_id="team-1",
        )
        # decision.path → RetrievalPath.PAGEINDEX
    """

    # Keywords that suggest structured document navigation
    _STRUCTURED_KEYWORDS = frozenset(
        {
            "section",
            "chapter",
            "table",
            "figure",
            "appendix",
            "page",
            "heading",
            "paragraph",
            "summary",
            "conclusion",
            "introduction",
            "abstract",
            "findings",
            "recommendation",
        }
    )

    # Keywords that suggest cross-document or factual search
    _FACTUAL_KEYWORDS = frozenset(
        {
            "compare",
            "across",
            "all documents",
            "every",
            "between",
            "list all",
            "how many",
            "what is",
            "define",
            "who",
        }
    )

    def __init__(self, document_store: DocumentStore) -> None:
        self._store = document_store

    async def route(
        self,
        query: str,
        mode: str = "auto",
        target_doc_id: str = "",
        team_id: str = "",
        namespace: str = "default",
    ) -> RoutingDecision:
        """
        Decide which retrieval path to use.

        Args:
            query: User's search query.
            mode: Explicit mode ("auto", "pageindex", "vector", "hybrid", "rag").
            target_doc_id: Scope to a specific document.
            team_id: For checking document availability.
            namespace: For document filtering.

        Returns:
            RoutingDecision with path, reason, and confidence.
        """
        # Rule 1: Explicit mode override
        if mode == "pageindex":
            return RoutingDecision(
                path=RetrievalPath.PAGEINDEX,
                reason="Explicit mode: pageindex",
            )
        if mode in ("vector", "rag"):
            return RoutingDecision(
                path=RetrievalPath.VECTOR,
                reason=f"Explicit mode: {mode}",
            )
        if mode == "hybrid":
            return RoutingDecision(
                path=RetrievalPath.HYBRID,
                reason="Explicit mode: hybrid",
            )

        # Rule 2: Auto-routing
        has_tree = False
        has_vectors = False

        if target_doc_id and team_id:
            meta = await self._store.get_meta(team_id, target_doc_id)
            if meta:
                has_tree = meta.tree_available
                has_vectors = meta.vectors_available

        # Rule 2a: target_doc_id + tree → PAGEINDEX
        if target_doc_id and has_tree and not has_vectors:
            return RoutingDecision(
                path=RetrievalPath.PAGEINDEX,
                reason="Document has tree index only",
                confidence=0.9,
            )

        # Rule 2b: Both available → analyze query
        if target_doc_id and has_tree and has_vectors:
            query_type = self._classify_query(query)
            if query_type == "structured":
                return RoutingDecision(
                    path=RetrievalPath.PAGEINDEX,
                    reason="Structured query on document with tree",
                    confidence=0.8,
                    metadata={"query_type": "structured"},
                )
            if query_type == "factual":
                return RoutingDecision(
                    path=RetrievalPath.VECTOR,
                    reason="Factual query, vector search faster",
                    confidence=0.7,
                    metadata={"query_type": "factual"},
                )
            # Complex/ambiguous → HYBRID
            return RoutingDecision(
                path=RetrievalPath.HYBRID,
                reason="Complex query, using both paths",
                confidence=0.6,
                metadata={"query_type": query_type},
            )

        # Rule 2c: No target_doc_id → VECTOR (cross-doc search)
        if not target_doc_id:
            return RoutingDecision(
                path=RetrievalPath.VECTOR,
                reason="Cross-document search, vector path required",
                confidence=0.9,
            )

        # Rule 2d: target_doc_id but no tree → VECTOR
        return RoutingDecision(
            path=RetrievalPath.VECTOR,
            reason="Document has no tree index, fallback to vector",
            confidence=0.7,
        )

    def _classify_query(self, query: str) -> str:
        """
        Simple heuristic query classification.

        Returns: "structured", "factual", or "complex"

        Day 5: Replace with LLM-based classification from evaluation data.
        """
        query_lower = query.lower()
        words = set(query_lower.split())

        structured_score = len(words & self._STRUCTURED_KEYWORDS)
        factual_score = sum(1 for kw in self._FACTUAL_KEYWORDS if kw in query_lower)

        if structured_score > factual_score:
            return "structured"
        if factual_score > structured_score:
            return "factual"
        return "complex"
