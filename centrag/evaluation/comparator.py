"""
Path Comparator — Side-by-side evaluation of retrieval paths.

Runs the same test cases through different retrieval paths
(pageindex, vector, hybrid) and produces a comparison report
showing which path performs better on each quality dimension.

Design Pattern: TEMPLATE METHOD — same evaluation flow, different paths.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from centrag.evaluation.judges import JudgeResult


@dataclass(frozen=True)
class PathScore:
    """Aggregate scores for a single retrieval path."""
    path: str
    case_count: int
    avg_composite: float
    avg_faithfulness: float
    avg_relevance: float
    avg_coverage: float
    avg_latency_ms: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "case_count": self.case_count,
            "avg_composite": round(self.avg_composite, 4),
            "avg_faithfulness": round(self.avg_faithfulness, 4),
            "avg_relevance": round(self.avg_relevance, 4),
            "avg_coverage": round(self.avg_coverage, 4),
            "avg_latency_ms": round(self.avg_latency_ms, 1),
        }


@dataclass
class ComparisonResult:
    """
    Side-by-side comparison of multiple retrieval paths.

    Identifies the winner for each quality dimension and overall.
    """
    path_scores: list[PathScore] = field(default_factory=list)
    winner_overall: str = ""
    winner_faithfulness: str = ""
    winner_relevance: str = ""
    winner_coverage: str = ""
    winner_latency: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "paths": [p.to_dict() for p in self.path_scores],
            "winners": {
                "overall": self.winner_overall,
                "faithfulness": self.winner_faithfulness,
                "relevance": self.winner_relevance,
                "coverage": self.winner_coverage,
                "latency": self.winner_latency,
            },
        }


@dataclass
class _PathAccumulator:
    """Internal: accumulates scores for a path."""
    composites: list[float] = field(default_factory=list)
    faithfulness: list[float] = field(default_factory=list)
    relevance: list[float] = field(default_factory=list)
    coverage: list[float] = field(default_factory=list)
    latencies: list[float] = field(default_factory=list)


class PathComparator:
    """
    Compare retrieval paths across the same test cases.

    Usage:
        comparator = PathComparator()
        comparator.add_result("pageindex", composite=0.8, ...)
        comparator.add_result("vector", composite=0.7, ...)
        comparison = comparator.compare()
        print(comparison.winner_overall)
    """

    def __init__(self) -> None:
        self._paths: dict[str, _PathAccumulator] = {}

    def add_result(
        self,
        path: str,
        composite: float,
        faithfulness: float = 0.0,
        relevance: float = 0.0,
        coverage: float = 0.0,
        latency_ms: float = 0.0,
    ) -> None:
        """Add a single evaluation result for a path."""
        acc = self._paths.setdefault(path, _PathAccumulator())
        acc.composites.append(composite)
        acc.faithfulness.append(faithfulness)
        acc.relevance.append(relevance)
        acc.coverage.append(coverage)
        acc.latencies.append(latency_ms)

    def compare(self) -> ComparisonResult:
        """Generate comparison across all paths."""
        if not self._paths:
            return ComparisonResult()

        scores: list[PathScore] = []
        for path, acc in self._paths.items():
            n = len(acc.composites)
            scores.append(PathScore(
                path=path,
                case_count=n,
                avg_composite=sum(acc.composites) / n if n else 0,
                avg_faithfulness=sum(acc.faithfulness) / n if n else 0,
                avg_relevance=sum(acc.relevance) / n if n else 0,
                avg_coverage=sum(acc.coverage) / n if n else 0,
                avg_latency_ms=sum(acc.latencies) / n if n else 0,
            ))

        def _best(key: str) -> str:
            return max(scores, key=lambda s: getattr(s, key)).path

        def _fastest() -> str:
            return min(scores, key=lambda s: s.avg_latency_ms).path

        return ComparisonResult(
            path_scores=scores,
            winner_overall=_best("avg_composite"),
            winner_faithfulness=_best("avg_faithfulness"),
            winner_relevance=_best("avg_relevance"),
            winner_coverage=_best("avg_coverage"),
            winner_latency=_fastest(),
        )
