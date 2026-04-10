"""
PageIndex Tree Builder — VECTORLESS retrieval path implementation.

Wraps the VectifyAI/PageIndex library to build hierarchical tree indices
from documents. This is the core of the vectorless retrieval strategy:
instead of chunking and embedding, documents are organized into an
LLM-navigable tree structure.

┌─────────────────────────────────────────────────────────────────────┐
│  RETRIEVAL PATH: VECTORLESS                                         │
│                                                                     │
│  This implementation is NEVER used in the vector retrieval path.    │
│  It implements TreeIndexProtocol (centrag/abstractions/tree_index)  │
│  and is wired into PageIndexRetriever for query-time tree search.  │
│                                                                     │
│  Ingestion flow:                                                    │
│    PDF/Markdown → PageIndex LLM → tree JSON + page cache → store   │
│                                                                     │
│  For non-PDF/Markdown: content is first converted to Markdown       │
│  by the existing parsers, then processed via md_to_tree().          │
└─────────────────────────────────────────────────────────────────────┘

Dependencies: pageindex (VectifyAI/PageIndex), litellm, pymupdf, PyPDF2.
Install: pip install litellm pymupdf PyPDF2

Design Pattern: ADAPTER — adapts PageIndex's API to CentRAG's TreeIndexProtocol.

SOLID: Single Responsibility — only builds trees. Does not retrieve, chunk, or embed.
SOLID: Liskov Substitution — any TreeIndexProtocol implementation can replace this.
"""
from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from centrag.utils.logger import get_logger

from centrag.abstractions.tree_index import (
    PageContent,
    TreeIndexProtocol,
    TreeIndexResult,
)

logger = get_logger("implementations.tree_index.pageindex")


def _remove_fields(data: Any, fields: list[str]) -> Any:
    """Recursively remove specified fields from a nested dict/list structure."""
    if isinstance(data, dict):
        return {
            k: _remove_fields(v, fields)
            for k, v in data.items()
            if k not in fields
        }
    if isinstance(data, list):
        return [_remove_fields(item, fields) for item in data]
    return data


def _count_nodes(tree: Any) -> int:
    """Count total nodes in a PageIndex tree structure."""
    if isinstance(tree, list):
        return sum(_count_nodes(n) for n in tree)
    if isinstance(tree, dict):
        count = 1
        for child in tree.get("nodes", []):
            count += _count_nodes(child)
        return count
    return 0


def _parse_pages(pages: str) -> list[int]:
    """Parse a page range string like '5-7', '3,8', '12' into sorted ints."""
    result: list[int] = []
    for part in pages.split(","):
        part = part.strip()
        if "-" in part:
            start_s, end_s = part.split("-", 1)
            start, end = int(start_s.strip()), int(end_s.strip())
            if start > end:
                raise ValueError(f"Invalid range: {part}")
            result.extend(range(start, end + 1))
        else:
            result.append(int(part))
    return sorted(set(result))


class PageIndexTreeBuilder:
    """
    Builds hierarchical tree indices using VectifyAI/PageIndex.

    VECTORLESS PATH ONLY.

    Supports:
        - PDF: native PageIndex processing (page_index function)
        - Markdown: md_to_tree() function
        - Other formats: converted to Markdown first, then md_to_tree()

    Usage:
        builder = PageIndexTreeBuilder(model="gpt-4o")
        result = await builder.build_tree("/path/to/report.pdf", "application/pdf")
        # result.tree → hierarchical tree JSON
        # result.page_cache → [{page: 1, content: "..."}, ...]

    Implements TreeIndexProtocol.
    """

    # Content types that PageIndex handles natively
    _PDF_TYPES = {"application/pdf"}
    _MD_TYPES = {"text/markdown", "text/x-markdown"}

    def __init__(
        self,
        model: str = "gpt-4o",
        add_summaries: bool = True,
        add_node_text: bool = True,
        add_node_ids: bool = True,
        add_doc_description: bool = True,
    ) -> None:
        self._model = model
        self._add_summaries = "yes" if add_summaries else "no"
        self._add_node_text = "yes" if add_node_text else "no"
        self._add_node_ids = "yes" if add_node_ids else "no"
        self._add_doc_description = "yes" if add_doc_description else "no"

    async def build_tree(
        self,
        file_path: str,
        content_type: str,
        doc_id: str | None = None,
    ) -> TreeIndexResult:
        """
        Build a tree index from a document.

        For PDFs: uses PageIndex's native PDF processing.
        For Markdown: uses md_to_tree().
        For other formats: converts to Markdown temp file, then md_to_tree().
        """
        file_path = os.path.abspath(os.path.expanduser(file_path))
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        logger.info(
            "building_tree",
            file_path=file_path,
            content_type=content_type,
            model=self._model,
            doc_id=doc_id,
        )

        if content_type in self._PDF_TYPES:
            return await self._build_from_pdf(file_path)
        elif content_type in self._MD_TYPES:
            return await self._build_from_markdown(file_path)
        else:
            # Convert to Markdown first, then build tree
            return await self._build_from_text(file_path, content_type)

    async def _build_from_pdf(self, file_path: str) -> TreeIndexResult:
        """Build tree from PDF using PageIndex's native PDF processing."""
        try:
            from pageindex import page_index
            import PyPDF2
        except ImportError as e:
            raise ImportError(
                "PageIndex dependencies not installed. "
                "Run: pip install litellm pymupdf PyPDF2"
            ) from e

        # Run PageIndex (CPU + LLM-bound, run in executor)
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: page_index(
                doc=file_path,
                model=self._model,
                if_add_node_summary=self._add_summaries,
                if_add_node_text=self._add_node_text,
                if_add_node_id=self._add_node_ids,
                if_add_doc_description=self._add_doc_description,
            ),
        )

        # Extract per-page text cache
        pages: list[dict[str, Any]] = []
        with open(file_path, "rb") as f:
            pdf_reader = PyPDF2.PdfReader(f)
            for i, page in enumerate(pdf_reader.pages, 1):
                pages.append({"page": i, "content": page.extract_text() or ""})

        tree_structure = result.get("structure", result)
        node_count = _count_nodes(tree_structure)

        logger.info(
            "pdf_tree_built",
            file_path=file_path,
            page_count=len(pages),
            node_count=node_count,
        )

        return TreeIndexResult(
            tree=result,
            page_cache=pages,
            doc_name=result.get("doc_name", Path(file_path).stem),
            doc_description=result.get("doc_description", ""),
            page_count=len(pages),
            node_count=node_count,
            model_used=self._model,
        )

    async def _build_from_markdown(self, file_path: str) -> TreeIndexResult:
        """Build tree from Markdown using PageIndex's md_to_tree."""
        try:
            from pageindex.page_index_md import md_to_tree
        except ImportError as e:
            raise ImportError(
                "PageIndex dependencies not installed. "
                "Run: pip install litellm pymupdf PyPDF2"
            ) from e

        result = await md_to_tree(
            md_path=file_path,
            if_thinning=False,
            if_add_node_summary=self._add_summaries,
            summary_token_threshold=200,
            model=self._model,
            if_add_doc_description=self._add_doc_description,
            if_add_node_text=self._add_node_text,
            if_add_node_id=self._add_node_ids,
        )

        tree_structure = result.get("structure", result)
        node_count = _count_nodes(tree_structure)

        # For Markdown, page cache is line-based (from tree nodes with text)
        page_cache = self._extract_md_page_cache(tree_structure)

        logger.info(
            "md_tree_built",
            file_path=file_path,
            node_count=node_count,
        )

        return TreeIndexResult(
            tree=result,
            page_cache=page_cache,
            doc_name=result.get("doc_name", Path(file_path).stem),
            doc_description=result.get("doc_description", ""),
            page_count=result.get("line_count", len(page_cache)),
            node_count=node_count,
            model_used=self._model,
        )

    async def _build_from_text(
        self, file_path: str, content_type: str
    ) -> TreeIndexResult:
        """
        Build tree from non-PDF/non-Markdown content.

        Strategy: read the file, write to a temp .md file, run md_to_tree().
        This handles HTML, DOCX, CSV content that has already been parsed
        to text by CentRAG's extraction pipeline.
        """
        content = Path(file_path).read_text(encoding="utf-8")

        # Write to temp markdown file
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        ) as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        try:
            result = await self._build_from_markdown(tmp_path)
            return result
        finally:
            os.unlink(tmp_path)

    def get_structure_for_context(
        self,
        tree: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Return tree structure WITHOUT text fields.

        Strips the full text content from each node, keeping only
        titles, summaries, page references, and hierarchy. This
        minimized version fits in an LLM's context window for
        reasoning-based navigation.
        """
        return _remove_fields(tree, fields=["text"])

    def extract_page_content(
        self,
        page_cache: list[dict[str, Any]],
        pages: str,
    ) -> list[PageContent]:
        """
        Extract specific page content from the cached pages.

        Args:
            page_cache: List of {page, content} dicts from build_tree().
            pages: Page range string, e.g. "5-7".

        Returns:
            List of PageContent for the requested pages.
        """
        page_nums = _parse_pages(pages)
        page_map = {p["page"]: p["content"] for p in page_cache}

        return [
            PageContent(page=p, content=page_map[p])
            for p in page_nums
            if p in page_map
        ]

    @staticmethod
    def _extract_md_page_cache(tree: Any) -> list[dict[str, Any]]:
        """Extract text content from Markdown tree nodes."""
        cache: list[dict[str, Any]] = []

        def _traverse(nodes: list[dict[str, Any]]) -> None:
            for node in nodes if isinstance(nodes, list) else [nodes]:
                if not isinstance(node, dict):
                    continue
                line_num = node.get("line_num")
                text = node.get("text", "")
                if line_num and text:
                    cache.append({"page": line_num, "content": text})
                if node.get("nodes"):
                    _traverse(node["nodes"])

        if isinstance(tree, list):
            _traverse(tree)
        elif isinstance(tree, dict):
            _traverse(tree.get("structure", tree.get("nodes", [tree])))

        return sorted(cache, key=lambda x: x["page"])
