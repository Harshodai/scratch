"""
Tree Index abstraction — contract for VECTORLESS retrieval path.

┌─────────────────────────────────────────────────────────────────────┐
│  RETRIEVAL PATH: VECTORLESS (PageIndex / Tree-based)                │
│                                                                     │
│  This protocol defines the contract for reasoning-based retrieval.  │
│  Instead of embeddings + cosine similarity, the vectorless path:    │
│    1. Builds a hierarchical tree index from a document (LLM call)   │
│    2. Navigates the tree via LLM reasoning to find relevant sections│
│    3. Extracts specific pages/sections as context                   │
│                                                                     │
│  Key difference from VectorStoreProtocol:                           │
│    - VectorStoreProtocol: chunk → embed → cosine search (SIMILAR)   │
│    - TreeIndexProtocol:   parse → tree → LLM reason → extract       │
│                           (RELEVANT — reasoning, not similarity)    │
│                                                                     │
│  SDLC Boundary:                                                     │
│    - This protocol is ONLY used in the vectorless retrieval path    │
│    - The vector path uses EmbedderProtocol + VectorStoreProtocol   │
│    - The QueryRouter decides which path handles each query          │
└─────────────────────────────────────────────────────────────────────┘

SOLID: Interface Segregation — TreeIndexProtocol only does tree operations.
       It does NOT embed, chunk, or search vectors.

SOLID: Dependency Inversion — PageIndexRetriever depends on this protocol,
       not on the concrete PageIndex library. You can swap PageIndex for
       any tree-based indexer without changing retrieval logic.

Design Pattern: STRATEGY — different tree indexers (PageIndex, custom)
       can be plugged in as long as they satisfy this protocol.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class TreeNode:
    """
    A single node in the document tree index.

    Represents a section/subsection with page references and an
    LLM-generated summary. Children form the hierarchy.
    """
    node_id: str
    title: str
    summary: str = ""
    start_page: int = 0
    end_page: int = 0
    children: tuple["TreeNode", ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize for JSON storage / LLM context injection."""
        result: dict[str, Any] = {
            "node_id": self.node_id,
            "title": self.title,
            "start_page": self.start_page,
            "end_page": self.end_page,
        }
        if self.summary:
            result["summary"] = self.summary
        if self.children:
            result["nodes"] = [c.to_dict() for c in self.children]
        if self.metadata:
            result["metadata"] = self.metadata
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TreeNode":
        """Deserialize from JSON."""
        children = tuple(
            cls.from_dict(n) for n in data.get("nodes", [])
        )
        return cls(
            node_id=data.get("node_id", ""),
            title=data.get("title", ""),
            summary=data.get("summary", ""),
            start_page=data.get("start_page", data.get("start_index", 0)),
            end_page=data.get("end_page", data.get("end_index", 0)),
            children=children,
            metadata=data.get("metadata", {}),
        )


@dataclass(frozen=True)
class TreeIndexResult:
    """
    Result of building a tree index for a document.

    Contains the tree structure, optional page cache, and
    metadata about the indexing process.
    """
    tree: dict[str, Any]              # Raw tree JSON (PageIndex format)
    page_cache: list[dict[str, Any]]  # [{page: 1, content: "..."}, ...]
    doc_name: str = ""
    doc_description: str = ""
    page_count: int = 0
    node_count: int = 0
    model_used: str = ""


@dataclass(frozen=True)
class PageContent:
    """A single page/section extracted from a document."""
    page: int
    content: str
    section_title: str = ""


@runtime_checkable
class TreeIndexProtocol(Protocol):
    """
    Contract for tree-based document indexers.

    VECTORLESS PATH ONLY — this protocol is never used in the vector path.

    Implementations:
        - PageIndexTreeBuilder: wraps VectifyAI/PageIndex library
        - Future: custom tree builders for specific document types
    """

    async def build_tree(
        self,
        file_path: str,
        content_type: str,
        doc_id: str | None = None,
    ) -> TreeIndexResult:
        """
        Build a hierarchical tree index from a document.

        This is an expensive operation (LLM API calls). Should be called
        once during ingestion, results cached in DocumentStore.

        Args:
            file_path: Path to the document file.
            content_type: MIME type (application/pdf, text/markdown, etc.).
            doc_id: Optional document ID for tracking.

        Returns:
            TreeIndexResult with tree structure and page cache.
        """
        ...

    def get_structure_for_context(
        self,
        tree: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Return tree structure WITHOUT text fields.

        Used to inject the tree into an LLM's context window for
        reasoning-based navigation. Text is stripped to save tokens;
        the LLM only needs titles, summaries, and page references
        to decide which sections are relevant.

        Args:
            tree: Full tree JSON from build_tree().

        Returns:
            Tree JSON with text fields removed.
        """
        ...

    def extract_page_content(
        self,
        page_cache: list[dict[str, Any]],
        pages: str,
    ) -> list[PageContent]:
        """
        Extract specific page content from the cached pages.

        Called after the LLM identifies relevant page ranges.

        Args:
            page_cache: List of {page, content} dicts.
            pages: Page range string, e.g. "5-7", "3,8", "12".

        Returns:
            List of PageContent for the requested pages.
        """
        ...
