"""
Tests for FlashRankReranker — no external dependencies required.

Tests the FlashRankReranker class using mocked flashrank.Ranker
to verify protocol compliance, edge cases, and graceful fallback
without requiring flashrank to be installed.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from centrag.abstractions.reranker import RerankResult


class TestFlashRankReranker:
    """Unit tests for FlashRankReranker."""

    def _make_reranker(self):
        """Create a FlashRankReranker with mocked Ranker."""
        from centrag.implementations.flashrank_reranker import FlashRankReranker

        reranker = FlashRankReranker(model_name="ms-marco-TinyBERT-L-2-v2")
        return reranker

    def test_empty_documents_returns_empty(self):
        reranker = self._make_reranker()
        result = asyncio.get_event_loop().run_until_complete(
            reranker.rerank("What is X?", [], top_n=5)
        )
        assert result == []

    def test_empty_query_returns_zero_scores(self):
        reranker = self._make_reranker()
        result = asyncio.get_event_loop().run_until_complete(
            reranker.rerank("", ["doc1", "doc2"], top_n=2)
        )
        assert len(result) == 2
        assert all(r.relevance_score == 0.0 for r in result)

    def test_whitespace_query_returns_zero_scores(self):
        reranker = self._make_reranker()
        result = asyncio.get_event_loop().run_until_complete(
            reranker.rerank("   ", ["doc1", "doc2"], top_n=2)
        )
        assert all(r.relevance_score == 0.0 for r in result)

    def test_rerank_with_mocked_ranker(self):
        """Test reranking with a mocked flashrank.Ranker."""
        reranker = self._make_reranker()

        # Mock the ranker to return predictable results
        mock_ranker = MagicMock()
        mock_ranker.rerank.return_value = [
            {"id": "1", "text": "Relevant document", "score": 0.95},
            {"id": "0", "text": "Less relevant", "score": 0.42},
        ]
        reranker._ranker = mock_ranker

        documents = ["Less relevant", "Relevant document"]
        result = asyncio.get_event_loop().run_until_complete(
            reranker.rerank("What is relevant?", documents, top_n=2)
        )

        assert len(result) == 2
        assert isinstance(result[0], RerankResult)
        assert result[0].index == 1
        assert result[0].relevance_score == 0.95
        assert result[0].text == "Relevant document"
        assert result[1].index == 0
        assert result[1].relevance_score == 0.42

    def test_top_n_limits_results(self):
        """Verify top_n is respected."""
        reranker = self._make_reranker()

        mock_ranker = MagicMock()
        mock_ranker.rerank.return_value = [
            {"id": "0", "text": "doc0", "score": 0.9},
            {"id": "1", "text": "doc1", "score": 0.8},
            {"id": "2", "text": "doc2", "score": 0.7},
        ]
        reranker._ranker = mock_ranker

        result = asyncio.get_event_loop().run_until_complete(
            reranker.rerank("query", ["doc0", "doc1", "doc2"], top_n=2)
        )
        assert len(result) == 2

    def test_fallback_on_exception(self):
        """Verify graceful degradation when ranker fails."""
        reranker = self._make_reranker()

        mock_ranker = MagicMock()
        mock_ranker.rerank.side_effect = RuntimeError("Model load failed")
        reranker._ranker = mock_ranker

        result = asyncio.get_event_loop().run_until_complete(
            reranker.rerank("query", ["doc1", "doc2", "doc3"], top_n=2)
        )

        # Fallback returns input order with 0.5 scores
        assert len(result) == 2
        assert all(r.relevance_score == 0.5 for r in result)
        assert result[0].index == 0
        assert result[1].index == 1

    def test_ranker_called_with_correct_format(self):
        """Verify FlashRank is called with the expected passage format."""
        reranker = self._make_reranker()

        mock_ranker = MagicMock()
        mock_ranker.rerank.return_value = [
            {"id": "0", "text": "doc A", "score": 0.5},
        ]
        reranker._ranker = mock_ranker

        asyncio.get_event_loop().run_until_complete(
            reranker.rerank("test query", ["doc A"], top_n=1)
        )

        # Verify the passage format passed to ranker.rerank()
        call_kwargs = mock_ranker.rerank.call_args
        passages = call_kwargs.kwargs.get("passages") or call_kwargs[1].get("passages")
        assert passages == [{"id": "0", "text": "doc A"}]

    def test_is_confident_property(self):
        """Verify CRAG confidence gating works on FlashRank results."""
        reranker = self._make_reranker()

        mock_ranker = MagicMock()
        mock_ranker.rerank.return_value = [
            {"id": "0", "text": "high confidence", "score": 0.85},
            {"id": "1", "text": "low confidence", "score": 0.3},
        ]
        reranker._ranker = mock_ranker

        result = asyncio.get_event_loop().run_until_complete(
            reranker.rerank("query", ["high confidence", "low confidence"], top_n=2)
        )

        assert result[0].is_confident is True  # 0.85 >= 0.5
        assert result[1].is_confident is False  # 0.3 < 0.5
