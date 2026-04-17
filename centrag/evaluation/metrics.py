"""
Evaluation Metrics — Aggregate statistics and per-case breakdowns.

Collects JudgeResult scores across test cases and computes:
    - Per-judge averages (faithfulness, relevance, coverage)
    - Overall composite score
    - Per-difficulty breakdowns
    - Pass/fail counts at configurable thresholds
    - Information Retrieval metrics: Precision@K, Recall@K, MRR, NDCG@K

Design Pattern: COLLECTOR — accumulates results, then reports.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from centrag.evaluation.dataset import Difficulty, TestCase

if TYPE_CHECKING:
    from centrag.evaluation.judges import JudgeResult


# =============================================================================
# Information Retrieval Metrics — Pure functions for composability
# =============================================================================


def precision_at_k(retrieved_ids: list[str], relevant_ids: set[str], k: int) -> float:
    """Precision@K — What fraction of the top-K retrieved docs are relevant?

    The WHY:
        Measures how many of the documents we returned are actually useful.
        High precision means fewer irrelevant results polluting the LLM context.

    Args:
        retrieved_ids: Ordered list of document IDs returned by the retriever.
        relevant_ids: Set of ground-truth relevant document IDs.
        k: Cutoff rank.

    Returns:
        Float in [0.0, 1.0]. 1.0 means every doc in top-K is relevant.
    """
    if k <= 0 or not retrieved_ids:
        return 0.0
    top_k = retrieved_ids[:k]
    hits = sum(1 for doc_id in top_k if doc_id in relevant_ids)
    return hits / k


def recall_at_k(retrieved_ids: list[str], relevant_ids: set[str], k: int) -> float:
    """Recall@K — What fraction of all relevant docs appear in the top-K?

    The WHY:
        Measures completeness. Did we find ALL the documents that matter?
        Critical for multi-hop queries and comprehensive summaries.

    Args:
        retrieved_ids: Ordered list of document IDs returned by the retriever.
        relevant_ids: Set of ground-truth relevant document IDs.
        k: Cutoff rank.

    Returns:
        Float in [0.0, 1.0]. 1.0 means all relevant docs were retrieved.
    """
    if k <= 0 or not relevant_ids:
        return 0.0
    top_k = retrieved_ids[:k]
    hits = sum(1 for doc_id in top_k if doc_id in relevant_ids)
    return hits / len(relevant_ids)


def mean_reciprocal_rank(retrieved_ids: list[str], relevant_ids: set[str]) -> float:
    """MRR — How high does the first relevant document appear?

    The WHY:
        In Q&A, users expect the answer in the FIRST result. MRR penalizes
        systems where the correct document is buried at rank 5 or 10.
        MRR = 1/rank_of_first_relevant. Perfect MRR = 1.0 (first result).

    Args:
        retrieved_ids: Ordered list of document IDs.
        relevant_ids: Set of ground-truth relevant document IDs.

    Returns:
        Float in [0.0, 1.0]. 1.0 means the first result is relevant.
    """
    for rank, doc_id in enumerate(retrieved_ids, start=1):
        if doc_id in relevant_ids:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(retrieved_ids: list[str], relevant_ids: set[str], k: int) -> float:
    """NDCG@K — Normalized Discounted Cumulative Gain.

    The WHY:
        Unlike Precision@K, NDCG rewards relevant documents that appear
        HIGHER in the ranking. A relevant doc at position 1 contributes
        more than one at position 5. This closely models user behavior
        in search interfaces where top results get the most attention.

    Args:
        retrieved_ids: Ordered list of document IDs.
        relevant_ids: Set of ground-truth relevant document IDs.
        k: Cutoff rank.

    Returns:
        Float in [0.0, 1.0]. 1.0 means perfect ranking.
    """
    if k <= 0 or not relevant_ids:
        return 0.0

    # DCG: sum of (relevance / log2(rank + 1)) for top-K
    dcg = 0.0
    for rank, doc_id in enumerate(retrieved_ids[:k], start=1):
        rel = 1.0 if doc_id in relevant_ids else 0.0
        dcg += rel / math.log2(rank + 1)

    # IDCG: best possible DCG (all relevant docs at top)
    ideal_hits = min(len(relevant_ids), k)
    idcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))

    if idcg == 0.0:
        return 0.0
    return dcg / idcg


def f1_at_k(retrieved_ids: list[str], relevant_ids: set[str], k: int) -> float:
    """F1@K — Harmonic mean of Precision@K and Recall@K.

    The WHY:
        Provides a balanced view of precision and recall at a given cutoff.
        Useful when both false positives (noise in context) and false
        negatives (missing relevant docs) are equally costly.
    """
    p = precision_at_k(retrieved_ids, relevant_ids, k)
    r = recall_at_k(retrieved_ids, relevant_ids, k)
    if p + r == 0.0:
        return 0.0
    return 2 * p * r / (p + r)


# =============================================================================
# Per-Case Result
# =============================================================================


@dataclass
class CaseResult:
    """Result of evaluating a single test case across all judges."""

    case: TestCase
    judge_results: list[JudgeResult] = field(default_factory=list)
    generated_answer: str = ""
    retrieval_path: str = ""  # "pageindex", "vector", "hybrid"
    latency_ms: float = 0.0
    retrieved_doc_ids: list[str] = field(default_factory=list)

    @property
    def composite_score(self) -> float:
        """Average across all judges."""
        if not self.judge_results:
            return 0.0
        return sum(r.score for r in self.judge_results) / len(self.judge_results)

    @property
    def passed(self) -> bool:
        """Did this case pass (composite >= 0.5)?"""
        return self.composite_score >= 0.5

    @property
    def relevant_ids(self) -> set[str]:
        """Ground-truth relevant doc IDs from the test case."""
        return set(self.case.expected_doc_ids)

    def retrieval_metrics(self, k: int = 5) -> dict[str, float]:
        """Compute IR metrics for this case at cutoff K.

        The WHY:
            Separates retrieval quality from generation quality.
            A perfect LLM cannot compensate for a broken retriever.
        """
        if not self.retrieved_doc_ids or not self.relevant_ids:
            return {
                "precision_at_k": 0.0,
                "recall_at_k": 0.0,
                "mrr": 0.0,
                "ndcg_at_k": 0.0,
                "f1_at_k": 0.0,
            }
        return {
            "precision_at_k": round(precision_at_k(self.retrieved_doc_ids, self.relevant_ids, k), 4),
            "recall_at_k": round(recall_at_k(self.retrieved_doc_ids, self.relevant_ids, k), 4),
            "mrr": round(mean_reciprocal_rank(self.retrieved_doc_ids, self.relevant_ids), 4),
            "ndcg_at_k": round(ndcg_at_k(self.retrieved_doc_ids, self.relevant_ids, k), 4),
            "f1_at_k": round(f1_at_k(self.retrieved_doc_ids, self.relevant_ids, k), 4),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case.id,
            "query": self.case.query,
            "difficulty": self.case.difficulty.value,
            "generated_answer": self.generated_answer[:200],
            "expected_answer": self.case.expected_answer[:200],
            "retrieval_path": self.retrieval_path,
            "composite_score": round(self.composite_score, 4),
            "passed": self.passed,
            "latency_ms": round(self.latency_ms, 1),
            "retrieval_metrics": self.retrieval_metrics(),
            "judges": [r.to_dict() for r in self.judge_results],
        }


# =============================================================================
# Aggregate Report
# =============================================================================


@dataclass
class EvaluationReport:
    """
    Complete evaluation report with aggregate and per-case data.

    Generated by EvaluationMetrics.generate_report().
    """

    total_cases: int = 0
    passed_cases: int = 0
    failed_cases: int = 0
    composite_score: float = 0.0
    per_judge_scores: dict[str, float] = field(default_factory=dict)
    per_difficulty: dict[str, dict[str, float]] = field(default_factory=dict)
    retrieval_metrics: dict[str, float] = field(default_factory=dict)
    case_results: list[dict[str, Any]] = field(default_factory=list)

    @property
    def pass_rate(self) -> float:
        if self.total_cases == 0:
            return 0.0
        return self.passed_cases / self.total_cases

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": {
                "total_cases": self.total_cases,
                "passed": self.passed_cases,
                "failed": self.failed_cases,
                "pass_rate": round(self.pass_rate, 4),
                "composite_score": round(self.composite_score, 4),
            },
            "retrieval_metrics": self.retrieval_metrics,
            "per_judge": {k: round(v, 4) for k, v in self.per_judge_scores.items()},
            "per_difficulty": self.per_difficulty,
            "cases": self.case_results,
        }


# =============================================================================
# Metrics Collector
# =============================================================================


class EvaluationMetrics:
    """
    Collects and aggregates evaluation results.

    Usage:
        metrics = EvaluationMetrics()
        for case in dataset.cases:
            answer = engine.retrieve(case.query)
            results = [judge.evaluate(...) for judge in judges]
            metrics.add(case, results, answer, retrieved_doc_ids=["doc1"])
        report = metrics.generate_report()
    """

    def __init__(self) -> None:
        self._results: list[CaseResult] = []

    @property
    def count(self) -> int:
        return len(self._results)

    @property
    def failed_results(self) -> list[CaseResult]:
        """All cases that failed evaluation (composite < 0.5)."""
        return [r for r in self._results if not r.passed]

    def add(
        self,
        case: TestCase,
        judge_results: list[JudgeResult],
        generated_answer: str = "",
        retrieval_path: str = "",
        latency_ms: float = 0.0,
        retrieved_doc_ids: list[str] | None = None,
    ) -> CaseResult:
        """Add evaluation results for a single test case."""
        result = CaseResult(
            case=case,
            judge_results=judge_results,
            generated_answer=generated_answer,
            retrieval_path=retrieval_path,
            latency_ms=latency_ms,
            retrieved_doc_ids=retrieved_doc_ids or [],
        )
        self._results.append(result)
        return result

    def generate_report(self) -> EvaluationReport:
        """Generate aggregate report from all collected results."""
        if not self._results:
            return EvaluationReport()

        total = len(self._results)
        passed = sum(1 for r in self._results if r.passed)

        # Per-judge averages
        judge_scores: dict[str, list[float]] = {}
        for result in self._results:
            for jr in result.judge_results:
                judge_scores.setdefault(jr.judge_name, []).append(jr.score)

        per_judge = {name: sum(scores) / len(scores) for name, scores in judge_scores.items()}

        # Overall composite
        composite = sum(r.composite_score for r in self._results) / total

        # Per-difficulty breakdown
        per_difficulty: dict[str, dict[str, float]] = {}
        for diff in Difficulty:
            diff_results = [r for r in self._results if r.case.difficulty == diff]
            if diff_results:
                per_difficulty[diff.value] = {
                    "count": len(diff_results),
                    "avg_score": round(sum(r.composite_score for r in diff_results) / len(diff_results), 4),
                    "pass_rate": round(sum(1 for r in diff_results if r.passed) / len(diff_results), 4),
                }

        # Aggregate retrieval metrics (average across cases that have them)
        ir_cases = [r for r in self._results if r.retrieved_doc_ids and r.relevant_ids]
        agg_retrieval: dict[str, float] = {}
        if ir_cases:
            all_ir = [r.retrieval_metrics() for r in ir_cases]
            for metric_name in all_ir[0]:
                vals = [m[metric_name] for m in all_ir]
                agg_retrieval[metric_name] = round(sum(vals) / len(vals), 4)

        return EvaluationReport(
            total_cases=total,
            passed_cases=passed,
            failed_cases=total - passed,
            composite_score=composite,
            per_judge_scores=per_judge,
            per_difficulty=per_difficulty,
            retrieval_metrics=agg_retrieval,
            case_results=[r.to_dict() for r in self._results],
        )
