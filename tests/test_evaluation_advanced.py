"""
Tests for IR Metrics, Failure Store, and DeepEval Judges.

Supplements the existing test_evaluation.py with:
    - Precision@K, Recall@K, MRR, NDCG@K, F1@K pure function tests
    - CaseResult.retrieval_metrics() integration test
    - FailureStore lifecycle (add, classify, save, load)
    - DeepEval judge availability check

All tests are deterministic (NoOp, no external LLM calls).
"""

from __future__ import annotations

import tempfile

import pytest

from centrag.evaluation.dataset import TestCase
from centrag.evaluation.failure_store import (
    FailureCase,
    FailureCategory,
    FailureStore,
    classify_failure,
)
from centrag.evaluation.judges import JudgeResult
from centrag.evaluation.metrics import (
    CaseResult,
    EvaluationMetrics,
    f1_at_k,
    mean_reciprocal_rank,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
)

# ── IR Metrics — Pure Functions ─────────────────────────────────────


class TestPrecisionAtK:
    """Precision@K: fraction of top-K retrieved that are relevant."""

    def test_all_relevant(self):
        assert precision_at_k(["a", "b", "c"], {"a", "b", "c"}, k=3) == 1.0

    def test_none_relevant(self):
        assert precision_at_k(["x", "y", "z"], {"a", "b"}, k=3) == 0.0

    def test_partial(self):
        # 2 out of 4 are relevant
        assert precision_at_k(["a", "x", "b", "y"], {"a", "b"}, k=4) == 0.5

    def test_k_less_than_retrieved(self):
        # Only look at top 2: ["a", "x"] → 1 relevant out of 2
        assert precision_at_k(["a", "x", "b", "y"], {"a", "b"}, k=2) == 0.5

    def test_empty_retrieved(self):
        assert precision_at_k([], {"a"}, k=5) == 0.0

    def test_zero_k(self):
        assert precision_at_k(["a"], {"a"}, k=0) == 0.0


class TestRecallAtK:
    """Recall@K: fraction of relevant docs found in top-K."""

    def test_all_found(self):
        assert recall_at_k(["a", "b", "c"], {"a", "b"}, k=3) == 1.0

    def test_none_found(self):
        assert recall_at_k(["x", "y", "z"], {"a", "b"}, k=3) == 0.0

    def test_partial(self):
        # Only "a" found in top 2 → 1/2 = 0.5
        assert recall_at_k(["a", "x", "b"], {"a", "b"}, k=2) == 0.5

    def test_empty_relevant(self):
        assert recall_at_k(["a", "b"], set(), k=5) == 0.0


class TestMRR:
    """Mean Reciprocal Rank: 1/rank of first relevant result."""

    def test_first_is_relevant(self):
        assert mean_reciprocal_rank(["a", "b", "c"], {"a"}) == 1.0

    def test_second_is_relevant(self):
        assert mean_reciprocal_rank(["x", "a", "c"], {"a"}) == 0.5

    def test_third_is_relevant(self):
        assert mean_reciprocal_rank(["x", "y", "a"], {"a"}) == pytest.approx(1.0 / 3)

    def test_none_relevant(self):
        assert mean_reciprocal_rank(["x", "y", "z"], {"a"}) == 0.0

    def test_empty_retrieved(self):
        assert mean_reciprocal_rank([], {"a"}) == 0.0


class TestNDCG:
    """NDCG@K: ranking quality with position-based discounting."""

    def test_perfect_ranking(self):
        # Both relevant docs at positions 1 and 2 → perfect NDCG
        assert ndcg_at_k(["a", "b", "c"], {"a", "b"}, k=3) == 1.0

    def test_reversed_ranking(self):
        # Relevant docs at positions 2 and 3 → penalized
        result = ndcg_at_k(["x", "a", "b"], {"a", "b"}, k=3)
        assert 0.0 < result < 1.0

    def test_no_relevant(self):
        assert ndcg_at_k(["x", "y", "z"], {"a"}, k=3) == 0.0

    def test_zero_k(self):
        assert ndcg_at_k(["a"], {"a"}, k=0) == 0.0


class TestF1AtK:
    """F1@K: harmonic mean of Precision@K and Recall@K."""

    def test_perfect(self):
        assert f1_at_k(["a", "b"], {"a", "b"}, k=2) == 1.0

    def test_zero(self):
        assert f1_at_k(["x", "y"], {"a", "b"}, k=2) == 0.0

    def test_balanced(self):
        # Precision=0.5 (1/2), Recall=1.0 (1/1) → F1 = 2*0.5*1.0/1.5 ≈ 0.667
        result = f1_at_k(["a", "x"], {"a"}, k=2)
        assert result == pytest.approx(2 / 3, abs=0.01)


# ── CaseResult IR Integration ──────────────────────────────────────


class TestCaseResultIR:
    """CaseResult.retrieval_metrics() integration."""

    def test_metrics_with_docs(self):
        case = TestCase(id="1", query="Q", expected_answer="A", expected_doc_ids=["a", "b"])
        result = CaseResult(
            case=case,
            judge_results=[JudgeResult("test", 0.8, "OK")],
            retrieved_doc_ids=["a", "x", "b"],
        )
        ir = result.retrieval_metrics(k=3)
        assert ir["precision_at_k"] == pytest.approx(2 / 3, abs=0.01)
        assert ir["recall_at_k"] == 1.0
        assert ir["mrr"] == 1.0  # "a" is at position 1

    def test_metrics_no_docs(self):
        case = TestCase(id="1", query="Q", expected_answer="A")
        result = CaseResult(case=case, judge_results=[])
        ir = result.retrieval_metrics()
        assert ir["precision_at_k"] == 0.0

    def test_metrics_in_report(self):
        metrics = EvaluationMetrics()
        case = TestCase(id="1", query="Q", expected_answer="A", expected_doc_ids=["a"])
        metrics.add(
            case,
            [JudgeResult("test", 0.8, "OK")],
            retrieved_doc_ids=["a", "b", "c"],
        )
        report = metrics.generate_report()
        assert "retrieval_metrics" in report.to_dict()
        assert report.retrieval_metrics["mrr"] == 1.0


# ── Failure Store ───────────────────────────────────────────────────


class TestFailureClassification:
    """Automatic failure classification from judge scores."""

    def test_hallucination_detection(self):
        case = TestCase(id="1", query="Q", expected_answer="A")
        result = CaseResult(
            case=case,
            judge_results=[JudgeResult("faithfulness", 0.1, "Bad")],
        )
        assert classify_failure(result) == FailureCategory.HALLUCINATION

    def test_off_topic_detection(self):
        case = TestCase(id="1", query="Q", expected_answer="A")
        result = CaseResult(
            case=case,
            judge_results=[
                JudgeResult("faithfulness", 0.8, "OK"),
                JudgeResult("relevance", 0.1, "Off topic"),
            ],
        )
        assert classify_failure(result) == FailureCategory.OFF_TOPIC

    def test_latency_exceeded(self):
        case = TestCase(id="1", query="Q", expected_answer="A")
        result = CaseResult(
            case=case,
            judge_results=[
                JudgeResult("faithfulness", 0.8, "OK"),
                JudgeResult("relevance", 0.8, "OK"),
                JudgeResult("coverage", 0.8, "OK"),
            ],
            latency_ms=15000,
        )
        assert classify_failure(result) == FailureCategory.LATENCY_EXCEEDED


class TestFailureStore:
    """FailureStore lifecycle tests."""

    def test_add_and_count(self):
        store = FailureStore()
        failure = FailureCase(
            case_id="1",
            query="Q",
            expected_answer="A",
            generated_answer="B",
            category=FailureCategory.HALLUCINATION,
            composite_score=0.2,
            retrieval_path="vector",
            latency_ms=500,
        )
        store.add(failure)
        assert store.count == 1

    def test_filter_by_category(self):
        store = FailureStore()
        store.add(
            FailureCase(
                case_id="1",
                query="Q1",
                expected_answer="A1",
                generated_answer="B1",
                category=FailureCategory.HALLUCINATION,
                composite_score=0.1,
                retrieval_path="vector",
                latency_ms=100,
            )
        )
        store.add(
            FailureCase(
                case_id="2",
                query="Q2",
                expected_answer="A2",
                generated_answer="B2",
                category=FailureCategory.OFF_TOPIC,
                composite_score=0.2,
                retrieval_path="vector",
                latency_ms=200,
            )
        )
        store.add(
            FailureCase(
                case_id="3",
                query="Q3",
                expected_answer="A3",
                generated_answer="B3",
                category=FailureCategory.HALLUCINATION,
                composite_score=0.15,
                retrieval_path="pageindex",
                latency_ms=300,
            )
        )

        hallucinations = store.filter_by_category(FailureCategory.HALLUCINATION)
        assert len(hallucinations) == 2

    def test_summary(self):
        store = FailureStore()
        store.add(
            FailureCase(
                case_id="1",
                query="Q",
                expected_answer="A",
                generated_answer="B",
                category=FailureCategory.RETRIEVAL_MISS,
                composite_score=0.3,
                retrieval_path="vector",
                latency_ms=100,
            )
        )
        summary = store.summary()
        assert summary["total_failures"] == 1
        assert "retrieval_miss" in summary["by_category"]

    def test_save_and_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = FailureStore(output_dir=tmpdir)
            store.add(
                FailureCase(
                    case_id="tc-1",
                    query="Q",
                    expected_answer="A",
                    generated_answer="B",
                    category=FailureCategory.HALLUCINATION,
                    composite_score=0.2,
                    retrieval_path="hybrid",
                    latency_ms=500,
                    judge_scores={"faithfulness": 0.1},
                )
            )
            path = store.save()
            assert path is not None

            # Load it back
            loaded = FailureStore.load(path)
            assert loaded.count == 1
            assert loaded._failures[0].case_id == "tc-1"

    def test_add_from_case_result(self):
        store = FailureStore()
        case = TestCase(id="fail-1", query="Q", expected_answer="A")
        result = CaseResult(
            case=case,
            judge_results=[JudgeResult("faithfulness", 0.1, "Hallucinated")],
            generated_answer="Wrong answer",
            retrieval_path="vector",
            latency_ms=200,
        )
        failure = store.add_from_result(result)
        assert failure.category == FailureCategory.HALLUCINATION
        assert store.count == 1

    def test_failed_results_integration(self):
        """Verify EvaluationMetrics.failed_results works with FailureStore."""
        metrics = EvaluationMetrics()
        case1 = TestCase(id="1", query="Q1", expected_answer="A1")
        case2 = TestCase(id="2", query="Q2", expected_answer="A2")

        metrics.add(case1, [JudgeResult("test", 0.8, "Pass")])
        metrics.add(case2, [JudgeResult("test", 0.2, "Fail")])

        assert len(metrics.failed_results) == 1

        store = FailureStore()
        for result in metrics.failed_results:
            store.add_from_result(result)
        assert store.count == 1
