"""
Tests for QueryRouter — auto path selection.

Verifies:
    - Explicit mode overrides
    - Auto-routing based on document availability
    - Query classification (structured vs factual vs complex)
    - Cross-document routing (always vector)
"""

from __future__ import annotations

import shutil
import tempfile

import pytest

from centrag.retrieval.query_router import QueryRouter, RetrievalPath
from centrag.storage.document_store import DocumentStore


@pytest.fixture
def tmp_store():
    """Create a DocumentStore with temp dir."""
    tmpdir = tempfile.mkdtemp(prefix="centrag_router_test_")
    store = DocumentStore(base_path=tmpdir)
    yield store
    shutil.rmtree(tmpdir, ignore_errors=True)


# ── Explicit Mode Overrides ────────────────────────────────────────


class TestExplicitMode:
    """User explicitly selects a mode — no auto-routing."""

    @pytest.mark.asyncio
    async def test_explicit_pageindex(self, tmp_store):
        router = QueryRouter(tmp_store)
        decision = await router.route("query", mode="pageindex")
        assert decision.path == RetrievalPath.PAGEINDEX
        assert "Explicit" in decision.reason

    @pytest.mark.asyncio
    async def test_explicit_vector(self, tmp_store):
        router = QueryRouter(tmp_store)
        decision = await router.route("query", mode="vector")
        assert decision.path == RetrievalPath.VECTOR

    @pytest.mark.asyncio
    async def test_explicit_rag(self, tmp_store):
        router = QueryRouter(tmp_store)
        decision = await router.route("query", mode="rag")
        assert decision.path == RetrievalPath.VECTOR  # rag = vector

    @pytest.mark.asyncio
    async def test_explicit_hybrid(self, tmp_store):
        router = QueryRouter(tmp_store)
        decision = await router.route("query", mode="hybrid")
        assert decision.path == RetrievalPath.HYBRID


# ── Auto-Routing Based on Document State ────────────────────────────


class TestAutoRouting:
    """Auto mode selects path based on what's available."""

    @pytest.mark.asyncio
    async def test_tree_only_routes_pageindex(self, tmp_store):
        """Doc with tree but no vectors → PAGEINDEX."""
        await tmp_store.store_document(
            team_id="t1",
            filename="doc.pdf",
            content_type="application/pdf",
            cleaned_text="text",
            doc_id="doc-1",
        )
        await tmp_store.update_meta(
            team_id="t1",
            doc_id="doc-1",
            tree_available=True,
            vectors_available=False,
            status="ready",
        )

        router = QueryRouter(tmp_store)
        decision = await router.route(
            query="What are the risks?",
            mode="auto",
            target_doc_id="doc-1",
            team_id="t1",
        )
        assert decision.path == RetrievalPath.PAGEINDEX

    @pytest.mark.asyncio
    async def test_no_target_doc_routes_vector(self, tmp_store):
        """No target_doc_id → VECTOR (cross-doc search)."""
        router = QueryRouter(tmp_store)
        decision = await router.route(
            query="What is revenue?",
            mode="auto",
            target_doc_id="",
            team_id="t1",
        )
        assert decision.path == RetrievalPath.VECTOR
        assert "Cross-document" in decision.reason

    @pytest.mark.asyncio
    async def test_both_available_structured_query(self, tmp_store):
        """Doc with both paths + structured query → PAGEINDEX."""
        await tmp_store.store_document(
            team_id="t1",
            filename="doc.pdf",
            content_type="application/pdf",
            cleaned_text="text",
            doc_id="doc-2",
        )
        await tmp_store.update_meta(
            team_id="t1",
            doc_id="doc-2",
            tree_available=True,
            vectors_available=True,
        )

        router = QueryRouter(tmp_store)
        decision = await router.route(
            query="What does the summary section say about findings?",
            mode="auto",
            target_doc_id="doc-2",
            team_id="t1",
        )
        assert decision.path == RetrievalPath.PAGEINDEX
        assert decision.metadata.get("query_type") == "structured"

    @pytest.mark.asyncio
    async def test_both_available_factual_query(self, tmp_store):
        """Doc with both paths + factual query → VECTOR."""
        await tmp_store.store_document(
            team_id="t1",
            filename="doc.pdf",
            content_type="application/pdf",
            cleaned_text="text",
            doc_id="doc-3",
        )
        await tmp_store.update_meta(
            team_id="t1",
            doc_id="doc-3",
            tree_available=True,
            vectors_available=True,
        )

        router = QueryRouter(tmp_store)
        decision = await router.route(
            query="What is the definition of revenue?",
            mode="auto",
            target_doc_id="doc-3",
            team_id="t1",
        )
        assert decision.path == RetrievalPath.VECTOR

    @pytest.mark.asyncio
    async def test_no_tree_fallback_to_vector(self, tmp_store):
        """Doc with no tree → fallback to VECTOR."""
        await tmp_store.store_document(
            team_id="t1",
            filename="doc.pdf",
            content_type="application/pdf",
            cleaned_text="text",
            doc_id="doc-4",
        )
        await tmp_store.update_meta(
            team_id="t1",
            doc_id="doc-4",
            tree_available=False,
            vectors_available=True,
        )

        router = QueryRouter(tmp_store)
        decision = await router.route(
            query="Explain the risks",
            mode="auto",
            target_doc_id="doc-4",
            team_id="t1",
        )
        assert decision.path == RetrievalPath.VECTOR
        assert "no tree" in decision.reason.lower()


# ── Query Classification ───────────────────────────────────────────


class TestQueryClassification:
    """Heuristic query classifier tests."""

    def test_structured_keywords(self, tmp_store):
        router = QueryRouter(tmp_store)
        assert router._classify_query("What does the summary section say?") == "structured"

    def test_factual_keywords(self, tmp_store):
        router = QueryRouter(tmp_store)
        assert router._classify_query("What is the definition of GDP?") == "factual"

    def test_complex_query(self, tmp_store):
        router = QueryRouter(tmp_store)
        assert router._classify_query("Analyze implications and nuances of this policy") == "complex"
