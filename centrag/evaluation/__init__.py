"""
Evaluation Package — Golden Dataset + LLM-as-Judge evaluation harness.

SHARED INFRASTRUCTURE: Measures RAG pipeline quality across both paths.

Components:
    - GoldenDataset: test cases with expected answers
    - Judges: automated quality scoring (faithfulness, relevance, coverage)
    - Metrics: aggregate statistics and per-case breakdowns
    - Comparator: side-by-side path comparison (pageindex vs vector vs hybrid)
"""
from centrag.evaluation.dataset import GoldenDataset, TestCase
from centrag.evaluation.judges import (
    FaithfulnessJudge,
    RelevanceJudge,
    CoverageJudge,
    JudgeResult,
)
from centrag.evaluation.metrics import EvaluationMetrics, EvaluationReport
from centrag.evaluation.comparator import PathComparator, ComparisonResult

__all__ = [
    "GoldenDataset",
    "TestCase",
    "FaithfulnessJudge",
    "RelevanceJudge",
    "CoverageJudge",
    "JudgeResult",
    "EvaluationMetrics",
    "EvaluationReport",
    "PathComparator",
    "ComparisonResult",
]
