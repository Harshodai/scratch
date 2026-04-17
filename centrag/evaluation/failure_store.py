"""
Failure Store — Persistence for evaluation failure cases.

The WHY:
    When the RAG pipeline fails (low scores, hallucinations, retrieval misses),
    we need to know EXACTLY what happened, WHY, and HOW OFTEN. This module
    captures failure cases with a structured taxonomy, enabling:
    1. Targeted debugging (which queries consistently fail?)
    2. Regression testing (did my change fix the known failures?)
    3. Golden dataset expansion (failures become new test cases)
    4. Retraining signals (failed retrievals → fine-tune reranker)

Design Pattern: REPOSITORY — abstracts persistence of failure data.
SOLID: Single Responsibility — only failure capture and retrieval.
SOLID: Open/Closed — add new failure types without modifying existing code.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from centrag.utils.logger import get_logger

if TYPE_CHECKING:
    from centrag.evaluation.metrics import CaseResult

logger = get_logger("evaluation.failure_store")


class FailureCategory(StrEnum):
    """Taxonomy of RAG failure modes.

    The WHY:
        Different failure types require different remediation strategies:
        - retrieval_miss → improve embeddings or add BM25 sparse search
        - hallucination → tighten faithfulness guardrails
        - off_topic → improve query routing or intent detection
        - low_coverage → add more source documents or improve chunking
        - latency_exceeded → optimize caching or reduce re-ranking
        - guardrail_block → review PII/content safety thresholds
    """

    RETRIEVAL_MISS = "retrieval_miss"
    HALLUCINATION = "hallucination"
    OFF_TOPIC = "off_topic"
    LOW_COVERAGE = "low_coverage"
    LATENCY_EXCEEDED = "latency_exceeded"
    GUARDRAIL_BLOCK = "guardrail_block"
    UNKNOWN = "unknown"


@dataclass
class FailureCase:
    """A single evaluation failure with structured diagnostics.

    Immutable record of WHAT failed, WHY, and in WHICH context.
    """

    case_id: str
    query: str
    expected_answer: str
    generated_answer: str
    category: FailureCategory
    composite_score: float
    retrieval_path: str
    latency_ms: float
    judge_scores: dict[str, float] = field(default_factory=dict)
    retrieval_metrics: dict[str, float] = field(default_factory=dict)
    difficulty: str = "moderate"
    tags: list[str] = field(default_factory=list)
    timestamp: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def classify_failure(result: CaseResult) -> FailureCategory:
    """Automatically classify a failure based on judge scores and retrieval metrics.

    The WHY:
        Manual classification does not scale. This heuristic classifier
        assigns the most likely root cause so engineers can filter and
        prioritize failures by category.
    """
    scores: dict[str, float] = {}
    for jr in result.judge_results:
        scores[jr.judge_name] = jr.score

    # Priority-ordered classification rules
    faithfulness = scores.get("faithfulness", scores.get("deepeval_faithfulness", 1.0))
    relevance = scores.get("relevance", scores.get("deepeval_relevance", 1.0))
    coverage = scores.get("coverage", scores.get("deepeval_contextual_recall", 1.0))
    hallucination = scores.get("deepeval_hallucination", 1.0)

    if hallucination < 0.3:
        return FailureCategory.HALLUCINATION
    if faithfulness < 0.3:
        return FailureCategory.HALLUCINATION
    if relevance < 0.3:
        return FailureCategory.OFF_TOPIC

    if result.latency_ms > 10000:
        return FailureCategory.LATENCY_EXCEEDED

    # Check retrieval metrics ONLY when ground truth doc IDs exist.
    # Without expected_doc_ids, retrieval_metrics() returns all zeros,
    # which would falsely classify every case as RETRIEVAL_MISS.
    if result.case.expected_doc_ids:
        ir = result.retrieval_metrics()
        if ir.get("recall_at_k", 1.0) < 0.2:
            return FailureCategory.RETRIEVAL_MISS

    if coverage < 0.3:
        return FailureCategory.LOW_COVERAGE

    return FailureCategory.UNKNOWN


def case_result_to_failure(result: CaseResult) -> FailureCase:
    """Convert a failed CaseResult into a FailureCase with classification."""
    category = classify_failure(result)

    judge_scores = {jr.judge_name: round(jr.score, 4) for jr in result.judge_results}

    return FailureCase(
        case_id=result.case.id,
        query=result.case.query,
        expected_answer=result.case.expected_answer,
        generated_answer=result.generated_answer,
        category=category,
        composite_score=round(result.composite_score, 4),
        retrieval_path=result.retrieval_path,
        latency_ms=round(result.latency_ms, 1),
        judge_scores=judge_scores,
        retrieval_metrics=result.retrieval_metrics(),
        difficulty=result.case.difficulty.value,
        tags=list(result.case.tags),
    )


class FailureStore:
    """Persist and query evaluation failure cases.

    Supports two backends:
        - JSON file (for CI artifacts, local debugging)
        - In-memory (for testing)

    Production extension: Add SQLAlchemy model for DB persistence (see models.py).

    Usage:
        store = FailureStore(output_dir="evaluate/reports")
        for result in metrics.failed_results:
            store.add(case_result_to_failure(result))
        store.save()
        print(store.summary())
    """

    def __init__(self, output_dir: str | None = None) -> None:
        self._failures: list[FailureCase] = []
        self._output_dir = Path(output_dir) if output_dir else None

    @property
    def count(self) -> int:
        return len(self._failures)

    def add(self, failure: FailureCase) -> None:
        """Add a failure case."""
        self._failures.append(failure)
        logger.info(
            "failure_case_captured",
            case_id=failure.case_id,
            category=failure.category.value,
            score=failure.composite_score,
        )

    def add_from_result(self, result: CaseResult) -> FailureCase:
        """Convert a CaseResult to FailureCase and add it."""
        failure = case_result_to_failure(result)
        self.add(failure)
        return failure

    def filter_by_category(self, category: FailureCategory) -> list[FailureCase]:
        """Get all failures of a specific type."""
        return [f for f in self._failures if f.category == category]

    def summary(self) -> dict[str, Any]:
        """Aggregate failure statistics by category."""
        by_category: dict[str, int] = {}
        for f in self._failures:
            by_category[f.category.value] = by_category.get(f.category.value, 0) + 1

        avg_score = (
            sum(f.composite_score for f in self._failures) / len(self._failures)
            if self._failures
            else 0.0
        )

        return {
            "total_failures": self.count,
            "by_category": by_category,
            "avg_composite_score": round(avg_score, 4),
            "worst_case": min(
                (f.to_dict() for f in self._failures),
                key=lambda x: x["composite_score"],
                default=None,
            ),
        }

    def save(self, filename: str = "failures.json") -> str | None:
        """Save all failure cases to JSON file.

        Returns the path to the saved file, or None if no output dir configured.
        """
        if not self._output_dir:
            logger.warning("failure_store_no_output_dir", message="No output dir configured, skipping save")
            return None

        self._output_dir.mkdir(parents=True, exist_ok=True)
        path = self._output_dir / filename

        data = {
            "summary": self.summary(),
            "failures": [f.to_dict() for f in self._failures],
        }

        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False, default=str)

        logger.info("failure_store_saved", path=str(path), count=self.count)
        return str(path)

    @classmethod
    def load(cls, path: str) -> FailureStore:
        """Load failure cases from a JSON file."""
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)

        store = cls()
        for item in data.get("failures", []):
            item["category"] = FailureCategory(item.get("category", "unknown"))
            store._failures.append(FailureCase(**item))

        logger.info("failure_store_loaded", path=path, count=store.count)
        return store
