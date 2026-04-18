"""
Tests for Automatic Self-Evaluation — verifies background evaluation and failure logging.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from centrag.abstractions.llm import QueryComplexity
from centrag.abstractions.retrieval import RetrievalRequest
from centrag.evaluation.failure_store import FailureStore
from centrag.evaluation.judges import FaithfulnessJudge
from centrag.middleware import RequestContext
from centrag.retrieval.engine import RetrievalEngine


@pytest.mark.asyncio
async def test_self_evaluation_captures_failure():
    """Verify that a low-score response triggers a FailureStore entry."""

    # 1. Setup mocked components
    mock_llm = AsyncMock()
    mock_llm.classify_complexity = AsyncMock(return_value=QueryComplexity.COMPLEX)
    mock_llm.generate = AsyncMock()
    # Mock llm.generate to return a bad answer (no overlap with sources)
    mock_llm_response = MagicMock()
    mock_llm_response.content = "Apples are red."
    mock_llm_response.input_tokens = 10
    mock_llm_response.output_tokens = 5
    mock_llm.generate.return_value = mock_llm_response

    mock_vectorstore = AsyncMock()
    mock_vectorstore.search = AsyncMock(
        return_value=[
            MagicMock(content="Oranges are orange.", document_id="doc1", score=0.9, metadata={"chunk_index": 0})
        ]
    )

    cache = AsyncMock()
    cache.get = AsyncMock(return_value=MagicMock(hit=False))
    memory = AsyncMock()
    memory.recall = AsyncMock(return_value=[])

    failure_store = MagicMock(spec=FailureStore)
    tracing = MagicMock()
    tracing.span = MagicMock()
    tracing.span.return_value.__aenter__ = AsyncMock()
    tracing.span.return_value.__aexit__ = AsyncMock()

    # 2. Patch settings to enable self-eval
    with patch("centrag.retrieval.engine.get_settings") as mock_settings_fn:
        mock_settings = MagicMock()
        mock_settings.enable_self_evaluation = True
        mock_settings.self_eval_threshold = 0.8
        mock_settings.enable_graph_retrieval = False
        mock_settings.enable_multivector_retrieval = False
        mock_settings.qdrant_collection = "test"
        mock_settings_fn.return_value = mock_settings

        # 3. Initialize Engine
        engine = RetrievalEngine(
            embedder_factory=lambda: AsyncMock(),
            vectorstore_factory=lambda: mock_vectorstore,
            reranker_factory=lambda: AsyncMock(),
            llm_factory=lambda: mock_llm,
            cache=cache,
            memory=memory,
            tracing=tracing,
            failure_store=failure_store,
            self_eval_judges=[FaithfulnessJudge()],
        )

        # 4. Execute query
        request = RetrievalRequest(query="What color are oranges?")
        ctx = RequestContext(team_id="test-team", team_name="Test", api_key_id="key-1", request_id="req-123")

        await engine.retrieve(request, ctx)

        # 5. Wait for background task
        # Since asyncio.create_task is used, we give it time to finish
        for _ in range(10):
            await asyncio.sleep(0.05)
            if failure_store.add_from_result.called:
                break

        # 6. Verify FailureStore was called
        # Faithfulness judge should score ~0 since "Apples are red" has no context in "Oranges are orange"
        assert failure_store.add_from_result.called

        args, _ = failure_store.add_from_result.call_args
        result = args[0]
        assert result.case.query == "What color are oranges?"
        assert result.generated_answer == "Apples are red."
        assert result.case.id.startswith("live-req-123")


@pytest.mark.asyncio
async def test_self_evaluation_skipped_for_simple_query():
    """Verify that SIMPLE complexity queries skip background self-evaluation.

    The WHY:
        Simple factual queries like "What is 2+2?" should not waste LLM
        tokens on self-evaluation judges. This is a performance optimization
        introduced to reduce cost on high-traffic basic queries.
    """
    mock_llm = AsyncMock()
    mock_llm.classify_complexity = AsyncMock(return_value=QueryComplexity.SIMPLE)
    mock_llm.generate = AsyncMock()
    mock_llm_response = MagicMock()
    mock_llm_response.content = "2 + 2 = 4"
    mock_llm_response.input_tokens = 5
    mock_llm_response.output_tokens = 3
    mock_llm.generate.return_value = mock_llm_response

    mock_vectorstore = AsyncMock()
    mock_vectorstore.search = AsyncMock(
        return_value=[MagicMock(content="Basic math.", document_id="doc1", score=0.95, metadata={"chunk_index": 0})]
    )

    cache = AsyncMock()
    cache.get = AsyncMock(return_value=MagicMock(hit=False))
    memory = AsyncMock()
    memory.recall = AsyncMock(return_value=[])

    failure_store = MagicMock(spec=FailureStore)
    tracing = MagicMock()
    tracing.span = MagicMock()
    tracing.span.return_value.__aenter__ = AsyncMock()
    tracing.span.return_value.__aexit__ = AsyncMock()

    with patch("centrag.retrieval.engine.get_settings") as mock_settings_fn:
        mock_settings = MagicMock()
        mock_settings.enable_self_evaluation = True
        mock_settings.self_eval_threshold = 0.8
        mock_settings.enable_graph_retrieval = False
        mock_settings.enable_multivector_retrieval = False
        mock_settings.qdrant_collection = "test"
        mock_settings_fn.return_value = mock_settings

        engine = RetrievalEngine(
            embedder_factory=lambda: AsyncMock(),
            vectorstore_factory=lambda: mock_vectorstore,
            reranker_factory=lambda: AsyncMock(),
            llm_factory=lambda: mock_llm,
            cache=cache,
            memory=memory,
            tracing=tracing,
            failure_store=failure_store,
            self_eval_judges=[FaithfulnessJudge()],
        )

        request = RetrievalRequest(query="What is 2+2?")
        ctx = RequestContext(team_id="test-team", team_name="Test", api_key_id="key-1", request_id="req-simple")

        await engine.retrieve(request, ctx)

        # Allow background tasks to settle
        await asyncio.sleep(0.2)

        # FailureStore should NOT have been called for SIMPLE queries
        assert not failure_store.add_from_result.called, "Self-evaluation should be skipped for SIMPLE queries"
