"""
DocumentStore — Filesystem-backed unified document storage.

SHARED INFRASTRUCTURE: Used by BOTH vectorless and vector retrieval paths.

Each document is stored in its own directory under:
    data/documents/{team_id}/{doc_id}/

This class is path-neutral — it stores and retrieves artifacts for both
the vectorless path (PageIndex tree, page cache) and the vector path
(chunks, embeddings metadata). The ingestion service decides what to store;
the retrievers decide what to read.

Design Pattern: REPOSITORY — encapsulates all persistence logic.
                DocumentStore is the ONLY way to access document artifacts.
                No retriever or service reads the filesystem directly.

SOLID: Single Responsibility — only handles document storage/retrieval.
       No parsing, no chunking, no embedding, no tree building.

SOLID: Open/Closed — to add S3 support, create a new DocumentStore
       implementation, don't modify this one.
"""
from __future__ import annotations

import json
import os
import shutil
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger("storage.document_store")


@dataclass(frozen=True)
class DocumentMeta:
    """
    Immutable metadata for a stored document.

    Shared by both retrieval paths — neither path-specific field
    (tree_available, vectors_available) is populated by DocumentStore
    itself; the ingestion service sets them after each path completes.
    """
    doc_id: str
    team_id: str
    filename: str
    content_type: str
    status: str = "pending"               # "pending" | "processing" | "ready" | "failed"
    namespace: str = "default"
    page_count: int = 0
    tree_node_count: int = 0              # VECTORLESS path: number of tree nodes
    chunk_count: int = 0                  # VECTOR path: number of chunks
    tree_available: bool = False          # VECTORLESS path: tree index built?
    vectors_available: bool = False       # VECTOR path: vectors in Qdrant?
    created_at: str = ""
    updated_at: str = ""
    user_metadata: dict[str, Any] = field(default_factory=dict)
    error_message: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize for JSON storage."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DocumentMeta":
        """Deserialize from JSON."""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class DocumentStore:
    """
    Filesystem-backed document store.

    Directory layout per document:
        {base_path}/{team_id}/{doc_id}/
            meta.json              — DocumentMeta (shared)
            cleaned_text.txt       — PII-scrubbed content (shared)
            pageindex_tree.json    — Tree structure (VECTORLESS path)
            page_cache.json        — Per-page text (VECTORLESS path)
            chunks.json            — Chunk list (VECTOR path, Day 3)

    Team isolation is enforced by directory structure: a team can only
    access documents under its own {team_id}/ directory.
    """

    def __init__(self, base_path: str = "data/documents") -> None:
        self._base = Path(base_path)
        self._base.mkdir(parents=True, exist_ok=True)

    def _doc_dir(self, team_id: str, doc_id: str) -> Path:
        """Get the directory for a specific document."""
        return self._base / team_id / doc_id

    # ── Document Lifecycle ──────────────────────────────────────────

    async def store_document(
        self,
        team_id: str,
        filename: str,
        content_type: str,
        cleaned_text: str,
        namespace: str = "default",
        user_metadata: dict[str, Any] | None = None,
        doc_id: str | None = None,
    ) -> DocumentMeta:
        """
        Store a new document. Creates the directory structure and writes
        the cleaned text and metadata.

        This is the FIRST step in ingestion — called before any
        path-specific indexing (tree building or vector embedding).
        """
        doc_id = doc_id or str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        doc_dir = self._doc_dir(team_id, doc_id)
        doc_dir.mkdir(parents=True, exist_ok=True)

        # Write cleaned text (shared by both paths)
        text_path = doc_dir / "cleaned_text.txt"
        text_path.write_text(cleaned_text, encoding="utf-8")

        # Create metadata
        meta = DocumentMeta(
            doc_id=doc_id,
            team_id=team_id,
            filename=filename,
            content_type=content_type,
            status="processing",
            namespace=namespace,
            created_at=now,
            updated_at=now,
            user_metadata=user_metadata or {},
        )

        # Write metadata
        meta_path = doc_dir / "meta.json"
        meta_path.write_text(
            json.dumps(meta.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        logger.info(
            "document_stored",
            doc_id=doc_id,
            team_id=team_id,
            filename=filename,
            content_type=content_type,
        )
        return meta

    async def update_meta(
        self,
        team_id: str,
        doc_id: str,
        **updates: Any,
    ) -> DocumentMeta:
        """
        Update specific metadata fields for a document.

        Used by the ingestion service to mark path-specific completion:
            update_meta(team_id, doc_id, tree_available=True, status="ready")
        """
        meta = await self.get_meta(team_id, doc_id)
        if meta is None:
            raise FileNotFoundError(f"Document {doc_id} not found for team {team_id}")

        meta_dict = meta.to_dict()
        meta_dict.update(updates)
        meta_dict["updated_at"] = datetime.now(timezone.utc).isoformat()

        updated = DocumentMeta.from_dict(meta_dict)

        meta_path = self._doc_dir(team_id, doc_id) / "meta.json"
        meta_path.write_text(
            json.dumps(updated.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return updated

    async def get_meta(self, team_id: str, doc_id: str) -> DocumentMeta | None:
        """Get document metadata. Returns None if not found."""
        meta_path = self._doc_dir(team_id, doc_id) / "meta.json"
        if not meta_path.exists():
            return None
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        return DocumentMeta.from_dict(data)

    async def get_cleaned_text(self, team_id: str, doc_id: str) -> str | None:
        """Get the cleaned text for a document (shared by both paths)."""
        text_path = self._doc_dir(team_id, doc_id) / "cleaned_text.txt"
        if not text_path.exists():
            return None
        return text_path.read_text(encoding="utf-8")

    # ── VECTORLESS Path Artifacts ───────────────────────────────────

    async def store_pageindex(
        self,
        team_id: str,
        doc_id: str,
        tree_json: dict[str, Any],
        page_cache: list[dict[str, Any]],
    ) -> None:
        """
        Store PageIndex tree and page cache.

        VECTORLESS PATH ONLY.

        Args:
            tree_json: The hierarchical tree structure from PageIndex.
            page_cache: List of {page: int, content: str} for each page.
        """
        doc_dir = self._doc_dir(team_id, doc_id)

        tree_path = doc_dir / "pageindex_tree.json"
        tree_path.write_text(
            json.dumps(tree_json, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        cache_path = doc_dir / "page_cache.json"
        cache_path.write_text(
            json.dumps(page_cache, ensure_ascii=False),
            encoding="utf-8",
        )

        logger.info(
            "pageindex_stored",
            doc_id=doc_id,
            team_id=team_id,
            tree_nodes=self._count_nodes(tree_json),
            pages=len(page_cache),
        )

    async def get_pageindex_tree(
        self, team_id: str, doc_id: str
    ) -> dict[str, Any] | None:
        """
        Get the PageIndex tree structure.

        VECTORLESS PATH ONLY.
        """
        tree_path = self._doc_dir(team_id, doc_id) / "pageindex_tree.json"
        if not tree_path.exists():
            return None
        return json.loads(tree_path.read_text(encoding="utf-8"))

    async def get_page_cache(
        self, team_id: str, doc_id: str
    ) -> list[dict[str, Any]] | None:
        """
        Get the page content cache.

        VECTORLESS PATH ONLY.
        """
        cache_path = self._doc_dir(team_id, doc_id) / "page_cache.json"
        if not cache_path.exists():
            return None
        return json.loads(cache_path.read_text(encoding="utf-8"))

    async def get_page_content(
        self,
        team_id: str,
        doc_id: str,
        pages: str,
    ) -> list[dict[str, Any]]:
        """
        Extract specific page content from the cache.

        VECTORLESS PATH ONLY.

        Args:
            pages: Page range string, e.g. "5-7", "3,8", "12".

        Returns:
            List of {page: int, content: str} for requested pages.
        """
        cache = await self.get_page_cache(team_id, doc_id)
        if not cache:
            return []

        page_nums = self._parse_pages(pages)
        page_map = {p["page"]: p["content"] for p in cache}
        return [
            {"page": p, "content": page_map[p]}
            for p in page_nums
            if p in page_map
        ]

    # ── VECTOR Path Artifacts ───────────────────────────────────────

    async def store_chunks(
        self,
        team_id: str,
        doc_id: str,
        chunks: list[dict[str, Any]],
    ) -> None:
        """
        Store chunk metadata (not vectors — those go to Qdrant).

        VECTOR PATH ONLY. Added in Day 3.
        """
        doc_dir = self._doc_dir(team_id, doc_id)
        chunks_path = doc_dir / "chunks.json"
        chunks_path.write_text(
            json.dumps(chunks, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info("chunks_stored", doc_id=doc_id, count=len(chunks))

    async def get_chunks(
        self, team_id: str, doc_id: str
    ) -> list[dict[str, Any]] | None:
        """
        Get chunk metadata for a document.

        VECTOR PATH ONLY.
        """
        chunks_path = self._doc_dir(team_id, doc_id) / "chunks.json"
        if not chunks_path.exists():
            return None
        return json.loads(chunks_path.read_text(encoding="utf-8"))

    # ── Shared Operations ───────────────────────────────────────────

    async def delete_document(self, team_id: str, doc_id: str) -> bool:
        """
        Atomically delete ALL artifacts for a document.

        Removes the entire document directory, covering both paths:
        tree, page cache, chunks, cleaned text, and metadata.
        """
        doc_dir = self._doc_dir(team_id, doc_id)
        if not doc_dir.exists():
            return False
        shutil.rmtree(doc_dir)
        logger.info("document_deleted", doc_id=doc_id, team_id=team_id)
        return True

    async def list_documents(
        self,
        team_id: str,
        namespace: str | None = None,
    ) -> list[DocumentMeta]:
        """List all documents for a team, optionally filtered by namespace."""
        team_dir = self._base / team_id
        if not team_dir.exists():
            return []

        results: list[DocumentMeta] = []
        for doc_dir in team_dir.iterdir():
            if not doc_dir.is_dir():
                continue
            meta_path = doc_dir / "meta.json"
            if not meta_path.exists():
                continue
            try:
                data = json.loads(meta_path.read_text(encoding="utf-8"))
                meta = DocumentMeta.from_dict(data)
                if namespace and meta.namespace != namespace:
                    continue
                results.append(meta)
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning("corrupt_meta", doc_dir=str(doc_dir), error=str(e))

        return results

    # ── Helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _parse_pages(pages: str) -> list[int]:
        """Parse a pages string like '5-7', '3,8', or '12' into sorted ints."""
        result: list[int] = []
        for part in pages.split(","):
            part = part.strip()
            if "-" in part:
                start_s, end_s = part.split("-", 1)
                start, end = int(start_s.strip()), int(end_s.strip())
                result.extend(range(start, end + 1))
            else:
                result.append(int(part))
        return sorted(set(result))

    @staticmethod
    def _count_nodes(tree: dict[str, Any] | list[Any]) -> int:
        """Count total nodes in a tree structure."""
        if isinstance(tree, list):
            return sum(DocumentStore._count_nodes(n) for n in tree)
        count = 1
        for child in tree.get("nodes", []):
            count += DocumentStore._count_nodes(child)
        return count
