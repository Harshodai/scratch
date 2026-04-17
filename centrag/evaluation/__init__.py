"""
Evaluation Package — Golden Dataset + LLM-as-Judge evaluation harness.

SHARED INFRASTRUCTURE: Measures RAG pipeline quality across both paths.

Components:
    - GoldenDataset: test cases with expected answers
    - Judges: automated quality scoring (faithfulness, relevance, coverage)
    - Metrics: aggregate statistics and per-case breakdowns
    - IR Metrics: precision@K, recall@K, MRR, NDCG@K, F1@K
    - Comparator: side-by-side path comparison (pageindex vs vector vs hybrid)
    - FailureStore: persistence for evaluation failure cases
    - EvaluationRunner: orchestrates full eval pipeline (engine → judges → metrics → failures)
"""

from centrag.evaluation.comparator import ComparisonResult, PathComparator
from centrag.evaluation.dataset import GoldenDataset, TestCase
from centrag.evaluation.failure_store import FailureCase, FailureCategory, FailureStore
from centrag.evaluation.runner import EvaluationRunner
from centrag.evaluation.judges import (
    CoverageJudge,
    FaithfulnessJudge,
    JudgeResult,
    RelevanceJudge,
)
from centrag.evaluation.metrics import (
    EvaluationMetrics,
    EvaluationReport,
    f1_at_k,
    mean_reciprocal_rank,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
)

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
    # IR Metrics
    "precision_at_k",
    "recall_at_k",
    "mean_reciprocal_rank",
    "ndcg_at_k",
    "f1_at_k",
    # Failure Store
    "FailureStore",
    "FailureCase",
    "FailureCategory",
    # Runner
    "EvaluationRunner",
]
