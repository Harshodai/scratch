"""
Tests for DocumentStore — SHARED infrastructure serving both retrieval paths.

Verifies:
    - Document lifecycle (store → get → update → delete)
    - VECTORLESS path artifacts (PageIndex tree, page cache)
    - VECTOR path artifacts (chunks, Day 3)
    - Team isolation (directory scoping)
    - Page range parsing
"""
from __future__ import annotations

import json
import pytest
import shutil
import tempfile
from pathlib import Path

from centrag.storage.document_store import DocumentStore, DocumentMeta


@pytest.fixture
def tmp_store():
    """Create a DocumentStore with a temporary directory."""
    tmpdir = tempfile.mkdtemp(prefix="centrag_test_")
    store = DocumentStore(base_path=tmpdir)
    yield store
    shutil.rmtree(tmpdir, ignore_errors=True)


# ── Document Lifecycle ──────────────────────────────────────────────

class TestDocumentLifecycle:
    """Tests for core document CRUD operations (shared by both paths)."""

    async def test_store_and_retrieve_document(self, tmp_store: DocumentStore):
        """Store a document and retrieve its metadata."""
        meta = await tmp_store.store_document(
            team_id="team-1",
            filename="report.pdf",
            content_type="application/pdf",
            cleaned_text="This is the cleaned text content.",
            namespace="finance",
        )

        assert meta.doc_id
        assert meta.team_id == "team-1"
        assert meta.filename == "report.pdf"
        assert meta.status == "processing"
        assert meta.namespace == "finance"

    async def test_get_meta_returns_stored_data(self, tmp_store: DocumentStore):
        """Metadata persists correctly to filesystem."""
        meta = await tmp_store.store_document(
            team_id="team-1",
            filename="test.pdf",
            content_type="application/pdf",
            cleaned_text="Content here.",
        )

        retrieved = await tmp_store.get_meta("team-1", meta.doc_id)
        assert retrieved is not None
        assert retrieved.doc_id == meta.doc_id
        assert retrieved.filename == "test.pdf"

    async def test_get_meta_wrong_team_returns_none(self, tmp_store: DocumentStore):
        """Team isolation: accessing another team's document returns None."""
        meta = await tmp_store.store_document(
            team_id="team-1",
            filename="secret.pdf",
            content_type="application/pdf",
            cleaned_text="Secret content.",
        )

        # Different team cannot access
        result = await tmp_store.get_meta("team-2", meta.doc_id)
        assert result is None

    async def test_get_cleaned_text(self, tmp_store: DocumentStore):
        """Cleaned text is stored and retrievable (shared by both paths)."""
        original_text = "This is cleaned content with\nmultiple lines."
        meta = await tmp_store.store_document(
            team_id="team-1",
            filename="doc.txt",
            content_type="text/plain",
            cleaned_text=original_text,
        )

        text = await tmp_store.get_cleaned_text("team-1", meta.doc_id)
        assert text == original_text

    async def test_update_meta(self, tmp_store: DocumentStore):
        """Update metadata fields individually."""
        meta = await tmp_store.store_document(
            team_id="team-1",
            filename="doc.pdf",
            content_type="application/pdf",
            cleaned_text="Text.",
        )

        updated = await tmp_store.update_meta(
            "team-1",
            meta.doc_id,
            status="ready",
            tree_available=True,
            tree_node_count=15,
        )

        assert updated.status == "ready"
        assert updated.tree_available is True
        assert updated.tree_node_count == 15

    async def test_delete_document(self, tmp_store: DocumentStore):
        """Delete removes all artifacts for both paths."""
        meta = await tmp_store.store_document(
            team_id="team-1",
            filename="doc.pdf",
            content_type="application/pdf",
            cleaned_text="Text.",
        )

        deleted = await tmp_store.delete_document("team-1", meta.doc_id)
        assert deleted is True

        # Verify everything is gone
        assert await tmp_store.get_meta("team-1", meta.doc_id) is None
        assert await tmp_store.get_cleaned_text("team-1", meta.doc_id) is None

    async def test_delete_nonexistent_returns_false(self, tmp_store: DocumentStore):
        """Deleting a non-existent document returns False."""
        result = await tmp_store.delete_document("team-1", "nonexistent-id")
        assert result is False


# ── VECTORLESS Path Artifacts ───────────────────────────────────────

class TestPageIndexArtifacts:
    """Tests for VECTORLESS path (PageIndex tree and page cache)."""

    async def test_store_and_retrieve_tree(self, tmp_store: DocumentStore):
        """Store and retrieve a PageIndex tree JSON."""
        meta = await tmp_store.store_document(
            team_id="team-1",
            filename="report.pdf",
            content_type="application/pdf",
            cleaned_text="Content.",
        )

        tree = {
            "doc_name": "report",
            "structure": [
                {
                    "node_id": "1",
                    "title": "Introduction",
                    "start_index": 1,
                    "end_index": 5,
                    "summary": "Overview of the report.",
                    "nodes": [],
                }
            ],
        }
        page_cache = [
            {"page": 1, "content": "Page 1 text."},
            {"page": 2, "content": "Page 2 text."},
        ]

        await tmp_store.store_pageindex(
            team_id="team-1",
            doc_id=meta.doc_id,
            tree_json=tree,
            page_cache=page_cache,
        )

        # Retrieve tree
        retrieved_tree = await tmp_store.get_pageindex_tree("team-1", meta.doc_id)
        assert retrieved_tree is not None
        assert retrieved_tree["doc_name"] == "report"
        assert len(retrieved_tree["structure"]) == 1

        # Retrieve page cache
        retrieved_cache = await tmp_store.get_page_cache("team-1", meta.doc_id)
        assert retrieved_cache is not None
        assert len(retrieved_cache) == 2

    async def test_get_page_content_single_page(self, tmp_store: DocumentStore):
        """Extract a single page from the cache."""
        meta = await tmp_store.store_document(
            team_id="team-1",
            filename="doc.pdf",
            content_type="application/pdf",
            cleaned_text="Content.",
        )
        await tmp_store.store_pageindex(
            team_id="team-1",
            doc_id=meta.doc_id,
            tree_json={},
            page_cache=[
                {"page": 1, "content": "Page 1"},
                {"page": 2, "content": "Page 2"},
                {"page": 3, "content": "Page 3"},
            ],
        )

        pages = await tmp_store.get_page_content("team-1", meta.doc_id, "2")
        assert len(pages) == 1
        assert pages[0]["page"] == 2
        assert pages[0]["content"] == "Page 2"

    async def test_get_page_content_range(self, tmp_store: DocumentStore):
        """Extract a page range from the cache."""
        meta = await tmp_store.store_document(
            team_id="team-1",
            filename="doc.pdf",
            content_type="application/pdf",
            cleaned_text="Content.",
        )
        await tmp_store.store_pageindex(
            team_id="team-1",
            doc_id=meta.doc_id,
            tree_json={},
            page_cache=[
                {"page": i, "content": f"Page {i}"}
                for i in range(1, 11)
            ],
        )

        pages = await tmp_store.get_page_content("team-1", meta.doc_id, "3-5, 8")
        assert len(pages) == 4  # pages 3, 4, 5, 8
        page_nums = [p["page"] for p in pages]
        assert page_nums == [3, 4, 5, 8]

    async def test_tree_not_found(self, tmp_store: DocumentStore):
        """Missing tree returns None, not an error."""
        result = await tmp_store.get_pageindex_tree("team-1", "nonexistent")
        assert result is None


# ── VECTOR Path Artifacts ───────────────────────────────────────────

class TestVectorArtifacts:
    """Tests for VECTOR path (chunks). Placeholder for Day 3."""

    async def test_store_and_retrieve_chunks(self, tmp_store: DocumentStore):
        """Store and retrieve chunk metadata."""
        meta = await tmp_store.store_document(
            team_id="team-1",
            filename="doc.pdf",
            content_type="application/pdf",
            cleaned_text="Content.",
        )

        chunks = [
            {"chunk_id": "c1", "content": "Chunk 1", "token_count": 50},
            {"chunk_id": "c2", "content": "Chunk 2", "token_count": 60},
        ]

        await tmp_store.store_chunks("team-1", meta.doc_id, chunks)

        retrieved = await tmp_store.get_chunks("team-1", meta.doc_id)
        assert retrieved is not None
        assert len(retrieved) == 2
        assert retrieved[0]["chunk_id"] == "c1"


# ── List & Multi-tenant ────────────────────────────────────────────

class TestListAndMultiTenant:
    """Tests for listing and team isolation."""

    async def test_list_documents_by_team(self, tmp_store: DocumentStore):
        """Each team sees only their own documents."""
        await tmp_store.store_document(
            team_id="team-1", filename="t1-doc.pdf",
            content_type="application/pdf", cleaned_text="T1.",
        )
        await tmp_store.store_document(
            team_id="team-2", filename="t2-doc.pdf",
            content_type="application/pdf", cleaned_text="T2.",
        )

        t1_docs = await tmp_store.list_documents("team-1")
        t2_docs = await tmp_store.list_documents("team-2")

        assert len(t1_docs) == 1
        assert t1_docs[0].filename == "t1-doc.pdf"
        assert len(t2_docs) == 1
        assert t2_docs[0].filename == "t2-doc.pdf"

    async def test_list_documents_by_namespace(self, tmp_store: DocumentStore):
        """Filter documents by namespace."""
        await tmp_store.store_document(
            team_id="team-1", filename="finance.pdf",
            content_type="application/pdf", cleaned_text="F.",
            namespace="finance",
        )
        await tmp_store.store_document(
            team_id="team-1", filename="legal.pdf",
            content_type="application/pdf", cleaned_text="L.",
            namespace="legal",
        )

        finance_docs = await tmp_store.list_documents("team-1", namespace="finance")
        assert len(finance_docs) == 1
        assert finance_docs[0].filename == "finance.pdf"


# ── Page Parsing ────────────────────────────────────────────────────

class TestPageParsing:
    """Tests for the _parse_pages utility."""

    def test_single_page(self):
        assert DocumentStore._parse_pages("5") == [5]

    def test_range(self):
        assert DocumentStore._parse_pages("3-7") == [3, 4, 5, 6, 7]

    def test_comma_separated(self):
        assert DocumentStore._parse_pages("1, 5, 10") == [1, 5, 10]

    def test_mixed(self):
        assert DocumentStore._parse_pages("1-3, 7, 10-12") == [1, 2, 3, 7, 10, 11, 12]

    def test_deduplication(self):
        assert DocumentStore._parse_pages("1-3, 2-4") == [1, 2, 3, 4]


# ── TreeNode Serialization ──────────────────────────────────────────

class TestTreeNodeSerialization:
    """Tests for TreeNode dataclass (VECTORLESS path)."""

    def test_to_dict_and_from_dict(self):
        from centrag.abstractions.tree_index import TreeNode

        node = TreeNode(
            node_id="1",
            title="Introduction",
            summary="Overview",
            start_page=1,
            end_page=5,
            children=(
                TreeNode(
                    node_id="1.1",
                    title="Background",
                    start_page=1,
                    end_page=3,
                ),
            ),
        )

        data = node.to_dict()
        assert data["node_id"] == "1"
        assert len(data["nodes"]) == 1

        restored = TreeNode.from_dict(data)
        assert restored.node_id == "1"
        assert len(restored.children) == 1
        assert restored.children[0].title == "Background"
