"""
Tests for Evaluation Harness — Golden Dataset, Judges, Metrics, Comparator.

Verifies:
    - Golden Dataset lifecycle (add, filter, serialize)
    - Judge scoring (faithfulness, relevance, coverage)
    - Metrics aggregation and reporting
    - Path comparator winners
"""

from __future__ import annotations

import json
import os
import tempfile

import pytest

from centrag.evaluation.comparator import PathComparator
from centrag.evaluation.dataset import Difficulty, GoldenDataset, TestCase
from centrag.evaluation.judges import (
    CoverageJudge,
    FaithfulnessJudge,
    JudgeResult,
    RelevanceJudge,
)
from centrag.evaluation.metrics import EvaluationMetrics

# ── Golden Dataset ──────────────────────────────────────────────────


class TestGoldenDataset:
    """Dataset lifecycle tests."""

    def test_create_empty(self):
        ds = GoldenDataset()
        assert ds.size == 0

    def test_add_case(self):
        ds = GoldenDataset()
        case = TestCase(id="tc-1", query="What?", expected_answer="Something")
        ds.add(case)
        assert ds.size == 1

    def test_filter_by_difficulty(self):
        ds = GoldenDataset(
            [
                TestCase(id="1", query="Q1", expected_answer="A1", difficulty=Difficulty.SIMPLE),
                TestCase(id="2", query="Q2", expected_answer="A2", difficulty=Difficulty.COMPLEX),
                TestCase(id="3", query="Q3", expected_answer="A3", difficulty=Difficulty.SIMPLE),
            ]
        )
        simple = ds.filter_by_difficulty(Difficulty.SIMPLE)
        assert len(simple) == 2

    def test_filter_by_tag(self):
        ds = GoldenDataset(
            [
                TestCase(id="1", query="Q1", expected_answer="A1", tags=["risk"]),
                TestCase(id="2", query="Q2", expected_answer="A2", tags=["finance"]),
                TestCase(id="3", query="Q3", expected_answer="A3", tags=["risk", "finance"]),
            ]
        )
        risk = ds.filter_by_tag("risk")
        assert len(risk) == 2

    def test_get_by_id(self):
        ds = GoldenDataset(
            [
                TestCase(id="tc-42", query="Q", expected_answer="A"),
            ]
        )
        assert ds.get_by_id("tc-42") is not None
        assert ds.get_by_id("missing") is None

    def test_json_roundtrip(self):
        ds = GoldenDataset(
            [
                TestCase(id="1", query="Q1", expected_answer="A1", difficulty=Difficulty.COMPLEX),
                TestCase(id="2", query="Q2", expected_answer="A2", tags=["test"]),
            ]
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "golden.json")
            ds.to_json(path)

            loaded = GoldenDataset.from_json(path)
            assert loaded.size == 2
            assert loaded.get_by_id("1").difficulty == Difficulty.COMPLEX

    def test_sample_dataset(self):
        ds = GoldenDataset.sample_dataset()
        assert ds.size == 5
        assert any(c.difficulty == Difficulty.COMPLEX for c in ds.cases)


# ── Faithfulness Judge ──────────────────────────────────────────────


class TestFaithfulnessJudge:
    """Source grounding evaluation."""

    def test_empty_answer_scores_zero(self):
        judge = FaithfulnessJudge()
        result = judge.evaluate("Q?", "", "Expected", ["source"])
        assert result.score == 0.0

    def test_no_sources_scores_zero(self):
        judge = FaithfulnessJudge()
        result = judge.evaluate("Q?", "Answer text here", "Expected", [])
        assert result.score == 0.0

    def test_high_overlap_scores_high(self):
        judge = FaithfulnessJudge()
        sources = ["The annual revenue was $42 million with strong growth in APAC markets"]
        answer = "The revenue was $42 million, showing strong growth in APAC markets"
        result = judge.evaluate("What was revenue?", answer, "Expected", sources)
        assert result.score >= 0.5

    def test_no_overlap_scores_low(self):
        judge = FaithfulnessJudge()
        sources = ["The company operates in North America"]
        answer = "Quantum computing will revolutionize artificial intelligence"
        result = judge.evaluate("Q?", answer, "Expected", sources)
        assert result.score < 0.5

    def test_result_has_details(self):
        judge = FaithfulnessJudge()
        result = judge.evaluate("Q?", "Some answer text", "Expected", ["source context"])
        assert "overlap_count" in result.details


# ── Relevance Judge ─────────────────────────────────────────────────


class TestRelevanceJudge:
    """Query addressing evaluation."""

    def test_empty_answer_scores_zero(self):
        judge = RelevanceJudge()
        result = judge.evaluate("What is revenue?", "", "Revenue is $42M", [])
        assert result.score == 0.0

    def test_relevant_answer_scores_high(self):
        judge = RelevanceJudge()
        result = judge.evaluate(
            "What are the key risk factors?",
            "The key risk factors include market volatility and regulatory changes",
            "The key risk factors are market volatility, regulatory changes, and cyber threats",
            [],
        )
        assert result.score >= 0.4

    def test_irrelevant_answer_scores_low(self):
        judge = RelevanceJudge()
        result = judge.evaluate(
            "What are the key risk factors?",
            "The weather forecast shows sunny skies tomorrow",
            "Risk factors include market volatility",
            [],
        )
        assert result.score < 0.5


# ── Coverage Judge ──────────────────────────────────────────────────


class TestCoverageJudge:
    """Key fact recall evaluation."""

    def test_empty_answer_scores_zero(self):
        judge = CoverageJudge()
        result = judge.evaluate("Q?", "", "Expected facts", [])
        assert result.score == 0.0

    def test_full_coverage_scores_high(self):
        judge = CoverageJudge()
        expected = "Revenue was $42 million with 15% growth"
        generated = "The company reported revenue of $42 million, achieving 15% growth year-over-year"
        result = judge.evaluate("What was revenue?", generated, expected, [])
        assert result.score >= 0.5

    def test_partial_coverage(self):
        judge = CoverageJudge()
        expected = "Three risks: market volatility, regulatory changes, cybersecurity threats"
        generated = "The main risk is market volatility"
        result = judge.evaluate("Q?", generated, expected, [])
        assert 0.0 < result.score < 1.0

    def test_empty_expected_scores_full(self):
        judge = CoverageJudge()
        result = judge.evaluate("Q?", "Some answer", "", [])
        assert result.score == 1.0


# ── Evaluation Metrics ──────────────────────────────────────────────


class TestEvaluationMetrics:
    """Aggregate metrics and reporting."""

    def test_empty_report(self):
        metrics = EvaluationMetrics()
        report = metrics.generate_report()
        assert report.total_cases == 0

    def test_add_and_count(self):
        metrics = EvaluationMetrics()
        case = TestCase(id="1", query="Q", expected_answer="A")
        metrics.add(case, [JudgeResult("test", 0.8, "Good")])
        assert metrics.count == 1

    def test_report_aggregation(self):
        metrics = EvaluationMetrics()
        case1 = TestCase(id="1", query="Q1", expected_answer="A1", difficulty=Difficulty.SIMPLE)
        case2 = TestCase(id="2", query="Q2", expected_answer="A2", difficulty=Difficulty.COMPLEX)

        metrics.add(
            case1,
            [
                JudgeResult("faithfulness", 0.8, "Good"),
                JudgeResult("relevance", 0.9, "Great"),
            ],
        )
        metrics.add(
            case2,
            [
                JudgeResult("faithfulness", 0.6, "OK"),
                JudgeResult("relevance", 0.7, "Fine"),
            ],
        )

        report = metrics.generate_report()
        assert report.total_cases == 2
        assert report.per_judge_scores["faithfulness"] == pytest.approx(0.7)
        assert report.per_judge_scores["relevance"] == pytest.approx(0.8)
        assert "simple" in report.per_difficulty
        assert "complex" in report.per_difficulty

    def test_pass_rate(self):
        metrics = EvaluationMetrics()
        case = TestCase(id="1", query="Q", expected_answer="A")

        metrics.add(case, [JudgeResult("test", 0.8, "Pass")])
        metrics.add(case, [JudgeResult("test", 0.2, "Fail")])

        report = metrics.generate_report()
        assert report.passed_cases == 1
        assert report.failed_cases == 1
        assert report.pass_rate == 0.5

    def test_report_serializable(self):
        metrics = EvaluationMetrics()
        case = TestCase(id="1", query="Q", expected_answer="A")
        metrics.add(case, [JudgeResult("test", 0.8, "OK")])

        report = metrics.generate_report()
        data = report.to_dict()
        # Must be JSON serializable
        json_str = json.dumps(data)
        assert "summary" in json_str


# ── Path Comparator ─────────────────────────────────────────────────


class TestPathComparator:
    """Side-by-side path comparison."""

    def test_empty_comparison(self):
        comp = PathComparator()
        result = comp.compare()
        assert len(result.path_scores) == 0

    def test_single_path(self):
        comp = PathComparator()
        comp.add_result("vector", composite=0.8, faithfulness=0.7, relevance=0.9, coverage=0.8)

        result = comp.compare()
        assert len(result.path_scores) == 1
        assert result.winner_overall == "vector"

    def test_two_paths_correct_winner(self):
        comp = PathComparator()
        # PageIndex wins on quality
        comp.add_result("pageindex", composite=0.9, faithfulness=0.85, relevance=0.95, coverage=0.9, latency_ms=200)
        # Vector wins on speed
        comp.add_result("vector", composite=0.7, faithfulness=0.65, relevance=0.75, coverage=0.7, latency_ms=50)

        result = comp.compare()
        assert result.winner_overall == "pageindex"
        assert result.winner_faithfulness == "pageindex"
        assert result.winner_latency == "vector"

    def test_multiple_results_per_path(self):
        comp = PathComparator()
        comp.add_result("pageindex", composite=0.8, faithfulness=0.7)
        comp.add_result("pageindex", composite=0.9, faithfulness=0.9)
        comp.add_result("vector", composite=0.6, faithfulness=0.5)
        comp.add_result("vector", composite=0.7, faithfulness=0.6)

        result = comp.compare()
        pi = next(p for p in result.path_scores if p.path == "pageindex")
        assert pi.case_count == 2
        assert pi.avg_composite == pytest.approx(0.85)

    def test_comparison_serializable(self):
        comp = PathComparator()
        comp.add_result("hybrid", composite=0.8, relevance=0.85)

        result = comp.compare()
        data = result.to_dict()
        json_str = json.dumps(data)
        assert "winners" in json_str
