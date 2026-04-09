"""
PageIndex Retriever — VECTORLESS retrieval strategy.

Performs reasoning-based document retrieval by having an LLM navigate
a hierarchical tree index to find relevant sections. This is the
core difference from vector retrieval:

    VECTOR PATH:    query → embed → cosine similarity → top-k chunks
    VECTORLESS PATH: query → LLM reads tree → reasons about relevance →
                     extracts specific pages/sections

┌─────────────────────────────────────────────────────────────────────┐
│  RETRIEVAL PATH: VECTORLESS                                         │
│                                                                     │
│  This retriever is NEVER used in the vector retrieval path.         │
│  It is wired by the QueryRouter when:                               │
│    - Query targets a specific document with a tree index            │
│    - Mode is explicitly set to "pageindex"                          │
│    - QueryRouter determines structured doc navigation is optimal    │
│                                                                     │
│  SDLC Boundary:                                                     │
│    - Depends on: TreeIndexProtocol, LLMProtocol, DocumentStore     │
│    - Does NOT depend on: EmbedderProtocol, VectorStoreProtocol     │
│    - The vector path has its own retriever (VectorRetriever, Day 3) │
└─────────────────────────────────────────────────────────────────────┘

Design Pattern: STRATEGY — pluggable retriever, selected by QueryRouter.
SOLID: Single Responsibility — only does tree-based retrieval.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

import structlog

from centrag.abstractions.tree_index import TreeIndexProtocol, PageContent
from centrag.storage.document_store import DocumentStore

logger = structlog.get_logger("retrieval.pageindex")


# ── Prompt Templates ────────────────────────────────────────────────

TREE_NAVIGATION_PROMPT = """You are a document analyst. You have the structure of a document below.
Your task is to identify which sections/pages contain information relevant to the user's question.

DOCUMENT STRUCTURE:
{tree_structure}

USER QUESTION: {query}

INSTRUCTIONS:
1. Analyze the document structure (titles, summaries, page ranges).
2. Identify the most relevant sections based on the question.
3. Return the page numbers that should be retrieved.

RESPONSE FORMAT (strict):
REASONING: <one paragraph explaining which sections are relevant and why>
PAGES: <comma-separated page ranges, e.g. "5-7, 22-28, 45">
CONFIDENCE: <float 0.0-1.0 indicating how confident you are the answer is in these pages>
"""

ANSWER_GENERATION_PROMPT = """You are a document QA assistant. Answer the user's question based ONLY on the provided document content.

DOCUMENT CONTENT (from pages {page_refs}):
{page_content}

USER QUESTION: {query}

INSTRUCTIONS:
- Answer based ONLY on the provided content. Do not make up information.
- Cite specific page numbers when referencing information.
- If the content does not contain the answer, say so explicitly.
- Be concise but thorough.
"""


@dataclass(frozen=True)
class PageIndexRetrievalResult:
    """
    Result from vectorless (PageIndex) retrieval.

    Includes the reasoning trace from tree navigation, making the
    retrieval explainable — you can see WHY these pages were selected.
    """
    content: str                           # Extracted page content
    source: str = "pageindex"              # Always "pageindex" for this retriever
    doc_id: str = ""
    section_title: str = ""
    page_refs: str = ""                    # e.g. "5-7, 22-28"
    relevance_score: float = 0.0           # From LLM confidence
    reasoning: str = ""                    # LLM's navigation reasoning
    metadata: dict[str, Any] = field(default_factory=dict)


class PageIndexRetriever:
    """
    Reasoning-based document retriever using PageIndex tree navigation.

    VECTORLESS PATH ONLY.

    Flow:
        1. Load tree structure (without text) from DocumentStore
        2. Inject tree + query into LLM → LLM reasons about relevant sections
        3. Parse LLM response → extract page ranges
        4. Fetch page content from DocumentStore
        5. Return as PageIndexRetrievalResult

    Usage:
        retriever = PageIndexRetriever(
            document_store=doc_store,
            tree_builder=tree_builder,
            llm=llm_instance,
        )
        results = await retriever.retrieve(
            query="What were the key risks?",
            doc_id="uuid",
            team_id="team-1",
        )
    """

    def __init__(
        self,
        document_store: DocumentStore,
        tree_builder: TreeIndexProtocol,
        llm: Any = None,  # LLMProtocol — typed as Any to avoid circular import
        max_pages_per_query: int = 20,
    ) -> None:
        self._store = document_store
        self._tree_builder = tree_builder
        self._llm = llm
        self._max_pages = max_pages_per_query

    async def retrieve(
        self,
        query: str,
        doc_id: str,
        team_id: str,
        limit: int = 5,
    ) -> list[PageIndexRetrievalResult]:
        """
        Retrieve relevant content from a document using tree navigation.

        Steps:
            1. Load PageIndex tree from DocumentStore
            2. LLM navigates tree to identify relevant pages
            3. Extract page content
            4. Return structured results

        Args:
            query: User's natural language question.
            doc_id: Target document ID (PageIndex is per-document).
            team_id: Team ID for access control.
            limit: Max number of result sections to return.

        Returns:
            List of PageIndexRetrievalResult with content and reasoning.
        """
        # 1. Load tree structure
        tree = await self._store.get_pageindex_tree(team_id, doc_id)
        if not tree:
            logger.warning("no_tree_found", doc_id=doc_id, team_id=team_id)
            return []

        # 2. Get structure without text (save tokens)
        structure_for_llm = self._tree_builder.get_structure_for_context(tree)

        # 3. LLM navigates the tree
        nav_result = await self._navigate_tree(
            query=query,
            tree_structure=structure_for_llm,
        )

        if not nav_result["pages"]:
            logger.info("no_relevant_pages", doc_id=doc_id, query=query[:100])
            return []

        # 4. Extract page content
        page_contents = await self._store.get_page_content(
            team_id=team_id,
            doc_id=doc_id,
            pages=nav_result["pages"],
        )

        if not page_contents:
            logger.warning(
                "page_content_empty",
                doc_id=doc_id,
                pages=nav_result["pages"],
            )
            return []

        # 5. Build results
        combined_content = "\n\n".join(
            f"--- Page {pc['page']} ---\n{pc['content']}"
            for pc in page_contents
        )

        result = PageIndexRetrievalResult(
            content=combined_content,
            doc_id=doc_id,
            page_refs=nav_result["pages"],
            relevance_score=nav_result.get("confidence", 0.7),
            reasoning=nav_result.get("reasoning", ""),
            metadata={
                "tree_nodes_visited": self._count_tree_depth(structure_for_llm),
                "pages_extracted": len(page_contents),
                "model": getattr(self._llm, "model", "unknown"),
            },
        )

        logger.info(
            "pageindex_retrieval_complete",
            doc_id=doc_id,
            pages=nav_result["pages"],
            confidence=nav_result.get("confidence"),
            pages_extracted=len(page_contents),
        )

        return [result]

    async def _navigate_tree(
        self,
        query: str,
        tree_structure: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Use LLM to navigate the tree and identify relevant pages.

        Returns:
            {pages: "5-7, 22-28", reasoning: "...", confidence: 0.85}
        """
        prompt = TREE_NAVIGATION_PROMPT.format(
            tree_structure=json.dumps(tree_structure, indent=2, ensure_ascii=False),
            query=query,
        )

        if self._llm is None:
            # Fallback: no LLM available, return all pages from tree
            logger.warning("no_llm_available", fallback="all_pages")
            all_pages = self._extract_all_page_ranges(tree_structure)
            return {
                "pages": all_pages,
                "reasoning": "LLM not available, returning all pages.",
                "confidence": 0.3,
            }

        try:
            response = await self._llm.generate(
                prompt=prompt,
                system_prompt="You are a precise document analyst. Follow the response format exactly.",
                temperature=0.1,  # Low temp for structured output
            )

            llm_text = response.text if hasattr(response, "text") else str(response)
            return self._parse_navigation_response(llm_text)

        except Exception as e:
            logger.error("tree_navigation_failed", error=str(e))
            # Fallback: return first few pages
            return {
                "pages": "1-5",
                "reasoning": f"Navigation failed ({e}), returning first pages.",
                "confidence": 0.2,
            }

    def _parse_navigation_response(self, response: str) -> dict[str, Any]:
        """Parse the LLM's navigation response into structured data."""
        result: dict[str, Any] = {
            "pages": "",
            "reasoning": "",
            "confidence": 0.5,
        }

        # Extract REASONING
        reasoning_match = re.search(
            r"REASONING:\s*(.+?)(?=\nPAGES:|$)",
            response,
            re.DOTALL | re.IGNORECASE,
        )
        if reasoning_match:
            result["reasoning"] = reasoning_match.group(1).strip()

        # Extract PAGES
        pages_match = re.search(
            r"PAGES:\s*(.+?)(?=\nCONFIDENCE:|$)",
            response,
            re.DOTALL | re.IGNORECASE,
        )
        if pages_match:
            pages_str = pages_match.group(1).strip()
            # Validate and normalize page ranges
            result["pages"] = self._normalize_pages(pages_str)

        # Extract CONFIDENCE
        conf_match = re.search(
            r"CONFIDENCE:\s*([\d.]+)",
            response,
            re.IGNORECASE,
        )
        if conf_match:
            try:
                result["confidence"] = min(1.0, max(0.0, float(conf_match.group(1))))
            except ValueError:
                pass

        return result

    @staticmethod
    def _normalize_pages(pages_str: str) -> str:
        """Clean and validate page range string."""
        # Remove any non-numeric, non-dash, non-comma characters
        cleaned = re.sub(r"[^\d,\-\s]", "", pages_str)
        # Remove extra whitespace
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        # Validate each part
        parts: list[str] = []
        for part in cleaned.split(","):
            part = part.strip()
            if not part:
                continue
            if "-" in part:
                try:
                    start, end = part.split("-", 1)
                    int(start.strip())
                    int(end.strip())
                    parts.append(part.strip())
                except (ValueError, IndexError):
                    continue
            else:
                try:
                    int(part)
                    parts.append(part)
                except ValueError:
                    continue
        return ", ".join(parts)

    @staticmethod
    def _extract_all_page_ranges(tree: Any) -> str:
        """Extract all page ranges from a tree structure (fallback)."""
        pages: set[int] = set()

        def _traverse(node: Any) -> None:
            if isinstance(node, list):
                for item in node:
                    _traverse(item)
                return
            if not isinstance(node, dict):
                return
            start = node.get("start_index", node.get("start_page", 0))
            end = node.get("end_index", node.get("end_page", 0))
            if start and end:
                pages.update(range(start, end + 1))
            for child in node.get("nodes", []):
                _traverse(child)

        _traverse(tree)
        if not pages:
            return "1-5"

        sorted_pages = sorted(pages)
        # Limit to max 20 pages
        limited = sorted_pages[:20]
        if len(limited) == 1:
            return str(limited[0])
        return f"{limited[0]}-{limited[-1]}"

    @staticmethod
    def _count_tree_depth(tree: Any) -> int:
        """Count the depth of a tree structure."""
        if isinstance(tree, list):
            return max(
                (PageIndexRetriever._count_tree_depth(n) for n in tree),
                default=0,
            )
        if isinstance(tree, dict):
            children = tree.get("nodes", [])
            if not children:
                return 1
            return 1 + max(
                PageIndexRetriever._count_tree_depth(c) for c in children
            )
        return 0
