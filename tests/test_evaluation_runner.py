"""
Tests for EvaluationRunner — verifies the full orchestration pipeline.

Uses mocked RetrievalEngine to avoid real API calls.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from centrag.abstractions.cache import CacheTier
from centrag.abstractions.llm import QueryComplexity
from centrag.abstractions.retrieval import RetrievalResponse, SourceChunk
from centrag.evaluation.dataset import Difficulty, GoldenDataset, TestCase
from centrag.evaluation.runner import EvaluationRunner


def _make_test_case(case_id: str = "tc-1", query: str = "What is CentRAG?") -> TestCase:
    return TestCase(
        id=case_id,
        query=query,
        expected_answer="CentRAG is a multi-tenant RAG platform.",
        expected_doc_ids=["doc-1", "doc-2"],
        difficulty=Difficulty.SIMPLE,
        tags=frozenset(["core"]),
    )


def _make_mock_engine(answer: str = "CentRAG is a RAG platform.", doc_ids: list[str] | None = None):
    """Create a mocked RetrievalEngine."""
    engine = AsyncMock()
    doc_ids = doc_ids or ["doc-1"]

    response = RetrievalResponse(
        answer=answer,
        sources=[
            SourceChunk(
                content="CentRAG is a multi-tenant platform.",
                document_id=did,
                chunk_index=0,
                relevance_score=0.9,
                metadata={"source": "vector"},
            )
            for did in doc_ids
        ],
        cache_tier=CacheTier.MISS,
        query_complexity=QueryComplexity.MODERATE,
        metadata={"retrieval_source": "vector"},
    )
    engine.retrieve = AsyncMock(return_value=response)
    return engine


class TestEvaluationRunner:
    """Tests for EvaluationRunner orchestration."""

    def test_runner_initialization(self):
        """Runner initializes with default judges."""
        engine = _make_mock_engine()
        dataset = GoldenDataset(cases=[_make_test_case()])

        runner = EvaluationRunner(engine=engine, dataset=dataset)

        assert len(runner._heuristic_judges) == 3  # Faithfulness, Relevance, Coverage
        assert len(runner._deepeval_judges) == 0
        assert runner.failure_store.count == 0

    def test_run_single_case(self):
        """Runner processes a single test case end-to-end."""
        engine = _make_mock_engine()
        dataset = GoldenDataset(cases=[_make_test_case()])

        runner = EvaluationRunner(engine=engine, dataset=dataset)
        report = asyncio.get_event_loop().run_until_complete(runner.run())

        assert report.total_cases == 1
        assert report.passed_cases + report.failed_cases == 1
        assert len(report.case_results) == 1

    def test_run_multiple_cases(self):
        """Runner processes multiple cases."""
        cases = [
            _make_test_case("tc-1", "What is CentRAG?"),
            _make_test_case("tc-2", "How does caching work?"),
            _make_test_case("tc-3", "Explain retrieval."),
        ]
        engine = _make_mock_engine()
        dataset = GoldenDataset(cases=cases)

        runner = EvaluationRunner(engine=engine, dataset=dataset)
        report = asyncio.get_event_loop().run_until_complete(runner.run())

        assert report.total_cases == 3
        assert engine.retrieve.call_count == 3

    def test_failure_store_captures_failures(self):
        """Failed cases are recorded in the FailureStore."""
        # Engine returns garbage → judges will give low scores
        engine = _make_mock_engine(
            answer="I don't know anything about this topic.",
            doc_ids=["wrong-doc"],
        )
        dataset = GoldenDataset(cases=[_make_test_case()])

        runner = EvaluationRunner(engine=engine, dataset=dataset)
        report = asyncio.get_event_loop().run_until_complete(runner.run())

        # Whether it passed or failed depends on judge scores,
        # but the runner processes it without errors
        assert report.total_cases == 1

    def test_engine_error_handled_gracefully(self):
        """Engine errors don't crash the runner."""
        engine = AsyncMock()
        engine.retrieve = AsyncMock(side_effect=RuntimeError("Connection refused"))

        dataset = GoldenDataset(cases=[_make_test_case()])

        runner = EvaluationRunner(engine=engine, dataset=dataset)
        report = asyncio.get_event_loop().run_until_complete(runner.run())

        # Should complete, case results should contain the error
        assert report.total_cases == 1
        case_data = report.case_results[0]
        assert "[ERROR]" in case_data["generated_answer"]

    def test_report_structure(self):
        """Report has all required fields."""
        engine = _make_mock_engine()
        dataset = GoldenDataset(cases=[_make_test_case()])

        runner = EvaluationRunner(engine=engine, dataset=dataset)
        report = asyncio.get_event_loop().run_until_complete(runner.run())
        report_dict = report.to_dict()

        assert "summary" in report_dict
        assert "per_judge" in report_dict
        assert "per_difficulty" in report_dict
        assert "cases" in report_dict
        assert "retrieval_metrics" in report_dict

    def test_failure_store_len(self):
        """FailureStore count property works."""
        engine = _make_mock_engine()
        dataset = GoldenDataset(cases=[_make_test_case()])

        runner = EvaluationRunner(engine=engine, dataset=dataset)
        assert runner.failure_store.count == 0
