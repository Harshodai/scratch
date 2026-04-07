"""
Unit tests for NoOp implementations — validates the pipeline can run end-to-end.

Tests:
  - NoOpEmbedder: deterministic vectors, dimension check, batch embed
  - NoOpVectorStore: upsert, search with filters, delete
  - NoOpLLM: generation, complexity classification, streaming
  - NoOpReranker: scoring, ordering, top_n limit
"""
from __future__ import annotations

import asyncio
import pytest

from centrag.implementations.noop_embedder import NoOpEmbedder
from centrag.implementations.noop_vectorstore import NoOpVectorStore
from centrag.implementations.noop_llm import NoOpLLM
from centrag.implementations.noop_reranker import NoOpReranker
from centrag.abstractions.vectorstore import VectorFilter
from centrag.abstractions.llm import QueryComplexity


# =============================================================================
# NoOpEmbedder
# =============================================================================

class TestNoOpEmbedder:
    @pytest.fixture
    def embedder(self):
        return NoOpEmbedder(dimension=128)

    @pytest.mark.asyncio
    async def test_embed_query_returns_correct_dimension(self, embedder):
        vec = await embedder.embed_query("test query")
        assert len(vec) == 128

    @pytest.mark.asyncio
    async def test_embed_query_is_deterministic(self, embedder):
        v1 = await embedder.embed_query("same text")
        v2 = await embedder.embed_query("same text")
        assert v1 == v2

    @pytest.mark.asyncio
    async def test_different_text_different_vectors(self, embedder):
        v1 = await embedder.embed_query("hello world")
        v2 = await embedder.embed_query("goodbye world")
        assert v1 != v2

    @pytest.mark.asyncio
    async def test_embed_documents_batch(self, embedder):
        texts = ["doc one", "doc two", "doc three"]
        result = await embedder.embed_documents(texts)
        assert len(result) == 3
        assert all(len(v) == 128 for v in result)

    @pytest.mark.asyncio
    async def test_embed_with_late_chunking(self, embedder):
        text = "Hello world. This is a test document for chunking."
        boundaries = [(0, 12), (13, 50)]
        result = await embedder.embed_with_late_chunking(text, boundaries)
        assert len(result) == 2
        assert all(len(v) == 128 for v in result)

    @pytest.mark.asyncio
    async def test_unit_norm(self, embedder):
        vec = await embedder.embed_query("normalize me")
        norm = sum(v * v for v in vec) ** 0.5
        assert abs(norm - 1.0) < 1e-6


# =============================================================================
# NoOpVectorStore
# =============================================================================

class TestNoOpVectorStore:
    @pytest.fixture
    def store(self):
        return NoOpVectorStore()

    @pytest.mark.asyncio
    async def test_upsert_and_search(self, store):
        await store.upsert("docs", "id1", [1.0, 0.0], {"team_id": "t1", "content": "hello"})
        results = await store.search(
            "docs", [1.0, 0.0], VectorFilter(must=[{"key": "team_id", "match": {"value": "t1"}}])
        )
        assert len(results) == 1
        assert results[0].id == "id1"
        assert results[0].score > 0.99

    @pytest.mark.asyncio
    async def test_filter_by_team(self, store):
        await store.upsert("docs", "id1", [1.0, 0.0], {"team_id": "team_a"})
        await store.upsert("docs", "id2", [1.0, 0.0], {"team_id": "team_b"})

        results_a = await store.search(
            "docs", [1.0, 0.0], VectorFilter(must=[{"key": "team_id", "match": {"value": "team_a"}}])
        )
        assert len(results_a) == 1
        assert results_a[0].id == "id1"

    @pytest.mark.asyncio
    async def test_must_not_filter(self, store):
        await store.upsert("docs", "id1", [1.0, 0.0], {"team_id": "t1", "status": "archived"})
        await store.upsert("docs", "id2", [1.0, 0.0], {"team_id": "t1", "status": "active"})

        results = await store.search(
            "docs", [1.0, 0.0],
            VectorFilter(
                must=[{"key": "team_id", "match": {"value": "t1"}}],
                must_not=[{"key": "status", "match": {"value": "archived"}}],
            ),
        )
        assert len(results) == 1
        assert results[0].id == "id2"

    @pytest.mark.asyncio
    async def test_delete_by_filter(self, store):
        await store.upsert("docs", "id1", [1.0], {"team_id": "t1"})
        await store.upsert("docs", "id2", [1.0], {"team_id": "t1"})
        await store.upsert("docs", "id3", [1.0], {"team_id": "t2"})

        deleted = await store.delete_by_filter(
            "docs", VectorFilter(must=[{"key": "team_id", "match": {"value": "t1"}}])
        )
        assert deleted == 2
        assert store.count("docs") == 1

    @pytest.mark.asyncio
    async def test_score_threshold(self, store):
        await store.upsert("docs", "id1", [1.0, 0.0], {"team_id": "t1"})
        await store.upsert("docs", "id2", [0.0, 1.0], {"team_id": "t1"})

        results = await store.search(
            "docs", [1.0, 0.0],
            VectorFilter(must=[{"key": "team_id", "match": {"value": "t1"}}]),
            score_threshold=0.5,
        )
        assert len(results) == 1  # Only id1 should match (cosine=1.0)


# =============================================================================
# NoOpLLM
# =============================================================================

class TestNoOpLLM:
    @pytest.fixture
    def llm(self):
        return NoOpLLM()

    @pytest.mark.asyncio
    async def test_generate_with_context(self, llm):
        response = await llm.generate(
            prompt="What is X?",
            context=["X is a test value.", "X was introduced in 2024."],
        )
        assert "Based on the provided sources" in response.content
        assert response.input_tokens > 0
        assert response.output_tokens > 0
        assert response.model == "noop-llm-v1"

    @pytest.mark.asyncio
    async def test_generate_without_context(self, llm):
        response = await llm.generate(prompt="test", context=[])
        assert "No relevant context" in response.content

    @pytest.mark.asyncio
    async def test_classify_simple(self, llm):
        result = await llm.classify_complexity("What is X?")
        assert result == QueryComplexity.SIMPLE

    @pytest.mark.asyncio
    async def test_classify_complex(self, llm):
        result = await llm.classify_complexity(
            "Compare the revenue trends between Q1 and Q4 across all regional divisions"
        )
        assert result == QueryComplexity.COMPLEX

    @pytest.mark.asyncio
    async def test_generate_stream(self, llm):
        chunks = []
        async for chunk in llm.generate_stream(prompt="test", context=["ctx"]):
            chunks.append(chunk)
        assert len(chunks) > 0
        full_text = "".join(chunks).strip()
        assert len(full_text) > 0


# =============================================================================
# NoOpReranker
# =============================================================================

class TestNoOpReranker:
    @pytest.fixture
    def reranker(self):
        return NoOpReranker()

    @pytest.mark.asyncio
    async def test_rerank_returns_top_n(self, reranker):
        docs = ["doc about cats", "doc about dogs", "doc about birds"]
        results = await reranker.rerank("cats", docs, top_n=2)
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_rerank_prefers_matching_docs(self, reranker):
        docs = [
            "The weather is sunny today",
            "Cats are wonderful pets with fluffy fur",
            "Database optimization techniques",
        ]
        results = await reranker.rerank("cats fluffy", docs, top_n=3)
        # The cat document should score highest due to word overlap
        assert results[0].text == docs[1]

    @pytest.mark.asyncio
    async def test_rerank_empty_docs(self, reranker):
        results = await reranker.rerank("query", [], top_n=5)
        assert results == []

    @pytest.mark.asyncio
    async def test_rerank_scores_bounded(self, reranker):
        docs = ["hello world", "test doc"]
        results = await reranker.rerank("hello world", docs, top_n=2)
        for r in results:
            assert 0.0 <= r.relevance_score <= 1.0
