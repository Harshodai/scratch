"""
Tests for BGEV2Reranker — validates score normalization, fallback, and protocol conformance.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from centrag.implementations.bge_reranker import BGEV2Reranker


@pytest.mark.asyncio
async def test_bge_reranker_empty_documents():
    """Empty document list should return empty results."""
    reranker = BGEV2Reranker()
    results = await reranker.rerank("test query", documents=[])
    assert results == []


@pytest.mark.asyncio
async def test_bge_reranker_empty_query():
    """Empty query string should return low-confidence fallback results."""
    reranker = BGEV2Reranker()
    results = await reranker.rerank("   ", documents=["doc1", "doc2"])
    assert len(results) == 2
    assert all(r.relevance_score == 0.0 for r in results)


@pytest.mark.asyncio
async def test_bge_reranker_normalized_scores():
    """Verify that scores are normalized to [0, 1] via normalize=True.

    The WHY:
        BGE raw logit scores can be negative or >1. The reranker MUST pass
        normalize=True to FlagReranker.compute_score() so sigmoid is applied.
        RerankResult.relevance_score is documented as '0.0 to 1.0'.
    """
    mock_model = MagicMock()
    # Simulate normalized sigmoid outputs (always 0-1)
    mock_model.compute_score.return_value = [0.95, 0.2, 0.75]

    with patch(
        "centrag.implementations.bge_reranker.BGEV2Reranker._load_model",
        return_value=mock_model,
    ):
        reranker = BGEV2Reranker()
        results = await reranker.rerank(
            "What is the revenue?",
            documents=["Revenue was $1M", "Weather is sunny", "Revenue grew 20%"],
            top_n=2,
        )

    # Verify that compute_score was called with normalize=True
    mock_model.compute_score.assert_called_once()
    call_args = mock_model.compute_score.call_args
    assert call_args[1].get("normalize") is True, (
        "compute_score MUST be called with normalize=True to map logits to [0,1]"
    )

    # Verify sorted and truncated
    assert len(results) == 2
    assert results[0].relevance_score >= results[1].relevance_score
    assert all(0.0 <= r.relevance_score <= 1.0 for r in results)


@pytest.mark.asyncio
async def test_bge_reranker_single_document():
    """Single document should handle scalar score (not list)."""
    mock_model = MagicMock()
    # FlagReranker returns a float (not list) for single pairs
    mock_model.compute_score.return_value = 0.88

    with patch(
        "centrag.implementations.bge_reranker.BGEV2Reranker._load_model",
        return_value=mock_model,
    ):
        reranker = BGEV2Reranker()
        results = await reranker.rerank("test", documents=["single doc"], top_n=5)

    assert len(results) == 1
    assert results[0].relevance_score == 0.88
    assert results[0].text == "single doc"
    assert results[0].index == 0


@pytest.mark.asyncio
async def test_bge_reranker_fallback_on_error():
    """On unexpected error, should return documents in original order."""
    mock_model = MagicMock()
    mock_model.compute_score.side_effect = RuntimeError("CUDA OOM")

    with patch(
        "centrag.implementations.bge_reranker.BGEV2Reranker._load_model",
        return_value=mock_model,
    ):
        reranker = BGEV2Reranker()
        results = await reranker.rerank(
            "query", documents=["doc1", "doc2", "doc3"], top_n=2
        )

    # Fallback returns original order with 0.5 score
    assert len(results) == 2
    assert all(r.relevance_score == 0.5 for r in results)
    assert results[0].text == "doc1"
    assert results[1].text == "doc2"


@pytest.mark.asyncio
async def test_bge_reranker_fallback_on_import_error():
    """When FlagEmbedding is not installed, should degrade gracefully."""
    reranker = BGEV2Reranker()

    with patch(
        "centrag.implementations.bge_reranker.BGEV2Reranker._load_model",
        side_effect=ImportError("No module named 'FlagEmbedding'"),
    ):
        results = await reranker.rerank("query", documents=["doc1"], top_n=1)

    assert len(results) == 1
    assert results[0].relevance_score == 0.5


@pytest.mark.asyncio
async def test_bge_reranker_preserves_original_index():
    """RerankResult.index should track original position for traceability."""
    mock_model = MagicMock()
    # Third doc is most relevant
    mock_model.compute_score.return_value = [0.1, 0.3, 0.9]

    with patch(
        "centrag.implementations.bge_reranker.BGEV2Reranker._load_model",
        return_value=mock_model,
    ):
        reranker = BGEV2Reranker()
        results = await reranker.rerank(
            "query", documents=["doc_a", "doc_b", "doc_c"], top_n=3
        )

    # doc_c (index=2) should be first after reranking
    assert results[0].index == 2
    assert results[0].text == "doc_c"
    assert results[0].relevance_score == 0.9
