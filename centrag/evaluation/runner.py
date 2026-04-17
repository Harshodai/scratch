"""
Evaluation Runner — Orchestrates the full evaluation pipeline.

The WHY:
    Individual judges, metrics, and failure stores are useless without
    an orchestrator that wires them together. This runner takes a
    RetrievalEngine + GoldenDataset and produces a complete
    EvaluationReport with failure analysis.

    It runs every test case through the live engine, scores with
    both heuristic and (optionally) LLM-backed judges, computes IR
    retrieval metrics, and records failures for debugging.

Design Pattern: FACADE — single entry point for the full eval cycle.
Integration: Called from CLI, CI/CD, or the /v1/evaluate API route.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from centrag.evaluation.dataset import GoldenDataset, TestCase
from centrag.evaluation.failure_store import FailureStore
from centrag.evaluation.judges import (
    CoverageJudge,
    FaithfulnessJudge,
    JudgeResult,
    RelevanceJudge,
)
from centrag.evaluation.metrics import CaseResult, EvaluationMetrics
from centrag.utils.logger import get_logger

if TYPE_CHECKING:
    from centrag.retrieval.engine import RetrievalEngine

logger = get_logger("evaluation.runner")


class EvaluationRunner:
    """End-to-end evaluation orchestrator.

    Runs GoldenDataset test cases through the retrieval engine, scores
    them with heuristic + LLM judges, computes IR metrics, and captures
    failure cases for analysis.

    Usage:
        runner = EvaluationRunner(
            engine=container.engine,
            dataset=GoldenDataset.sample_dataset(),
        )
        report = await runner.run()
        print(f"Pass rate: {report.pass_rate:.1%}")
        runner.failure_store.save()
    """

    def __init__(
        self,
        engine: RetrievalEngine,
        dataset: GoldenDataset,
        heuristic_judges: list[Any] | None = None,
        deepeval_judges: list[Any] | None = None,
        failure_store: FailureStore | None = None,
        team_id: str = "eval-team",
        output_dir: str = "evaluate/reports",
    ) -> None:
        """
        Args:
            engine: The wired RetrievalEngine to evaluate.
            dataset: GoldenDataset with test cases.
            heuristic_judges: Fast, deterministic judges (default: all 3).
            deepeval_judges: LLM-backed judges (optional, requires API key).
            failure_store: Where to record failed cases.
            team_id: Team scope for tenant isolation during eval.
            output_dir: Directory for evaluation reports and failure logs.
        """
        self._engine = engine
        self._dataset = dataset
        self._team_id = team_id

        # Default heuristic judges — always available, zero cost
        self._heuristic_judges = heuristic_judges or [
            FaithfulnessJudge(),
            RelevanceJudge(),
            CoverageJudge(),
        ]

        # LLM-backed judges — optional, loaded lazily
        self._deepeval_judges = deepeval_judges or []

        # Failure tracking
        self.failure_store = failure_store or FailureStore(output_dir=output_dir)

        # Metrics collector
        self._metrics = EvaluationMetrics()

        logger.info(
            "evaluation_runner_initialized",
            test_cases=dataset.size,
            heuristic_judges=len(self._heuristic_judges),
            deepeval_judges=len(self._deepeval_judges),
            team_id=team_id,
        )

    async def run(self) -> Any:
        """Execute the full evaluation pipeline.

        The WHY:
            This is the single orchestration point. It prevents the
            common mistake of forgetting to wire judges, metrics, or
            failure tracking when running evaluations manually.

        Returns:
            EvaluationReport with aggregate scores, per-case results,
            IR metrics, and failure classification.
        """

        logger.info("evaluation_started", total_cases=self._dataset.size)
        start_time = time.monotonic()

        for case in self._dataset.cases:
            case_result = await self._evaluate_single_case(case)
            self._metrics.add(
                case=case_result.case,
                judge_results=case_result.judge_results,
                generated_answer=case_result.generated_answer,
                retrieval_path=case_result.retrieval_path,
                latency_ms=case_result.latency_ms,
                retrieved_doc_ids=case_result.retrieved_doc_ids,
            )

            if not case_result.passed:
                self.failure_store.add_from_result(case_result)
                logger.info(
                    "case_failed",
                    case_id=case.id,
                    score=round(case_result.composite_score, 3),
                    latency_ms=round(case_result.latency_ms, 1),
                )

        total_ms = (time.monotonic() - start_time) * 1000
        report = self._metrics.generate_report()

        logger.info(
            "evaluation_complete",
            total_cases=report.total_cases,
            passed=report.passed_cases,
            failed=report.failed_cases,
            pass_rate=f"{report.pass_rate:.1%}",
            composite=round(report.composite_score, 3),
            total_ms=round(total_ms, 1),
            failures_captured=self.failure_store.count,
        )

        return report

    async def _evaluate_single_case(self, case: TestCase) -> CaseResult:
        """Evaluate one test case through the full pipeline.

        Steps:
          1. Send query to RetrievalEngine
          2. Score with heuristic judges
          3. Score with DeepEval judges (if available)
          4. Compute IR metrics from retrieved doc IDs
          5. Return CaseResult with all scores + latency
        """
        from centrag.abstractions.retrieval import RetrievalRequest
        from centrag.middleware import RequestContext

        start_time = time.monotonic()

        # --- Step 1: Retrieve ---
        try:
            request = RetrievalRequest(
                query=case.query,
                max_results=10,
            )
            ctx = RequestContext(
                team_id=self._team_id,
                team_name="eval",
                api_key_id="eval-harness",
                request_id=f"eval-{case.id}",
            )
            response = await self._engine.retrieve(request, ctx)
            generated_answer = response.answer
            source_texts = [s.content for s in response.sources]
            retrieved_doc_ids = [s.document_id for s in response.sources]
            retrieval_path = response.metadata.get("retrieval_source", "unknown")

        except Exception as e:
            logger.error("case_retrieval_failed", case_id=case.id, error=str(e))
            generated_answer = f"[ERROR] {e}"
            source_texts = []
            retrieved_doc_ids = []
            retrieval_path = "error"

        latency_ms = (time.monotonic() - start_time) * 1000

        # --- Step 2: Heuristic judges ---
        judge_results: list[JudgeResult] = []
        for judge in self._heuristic_judges:
            try:
                result = judge.evaluate(
                    query=case.query,
                    generated_answer=generated_answer,
                    expected_answer=case.expected_answer,
                    sources=source_texts,
                )
                judge_results.append(result)
            except Exception as e:
                logger.warning(
                    "judge_failed",
                    judge=type(judge).__name__,
                    case_id=case.id,
                    error=str(e),
                )

        # --- Step 3: DeepEval judges (optional) ---
        for judge in self._deepeval_judges:
            try:
                result = judge.evaluate(
                    query=case.query,
                    generated_answer=generated_answer,
                    expected_answer=case.expected_answer,
                    sources=source_texts,
                )
                judge_results.append(result)
            except Exception as e:
                logger.warning(
                    "deepeval_judge_failed",
                    judge=type(judge).__name__,
                    case_id=case.id,
                    error=str(e),
                )

        return CaseResult(
            case=case,
            judge_results=judge_results,
            generated_answer=generated_answer,
            retrieval_path=retrieval_path,
            latency_ms=latency_ms,
            retrieved_doc_ids=retrieved_doc_ids,
        )

    @classmethod
    def with_deepeval(
        cls,
        engine: RetrievalEngine,
        dataset: GoldenDataset,
        **kwargs: Any,
    ) -> EvaluationRunner:
        """Factory: Create runner with DeepEval LLM judges enabled.

        The WHY:
            DeepEval judges require an LLM API key and add latency.
            This factory makes it explicit when you want LLM scoring.
            Use the standard constructor for fast, heuristic-only evals.
        """
        try:
            from centrag.evaluation.deepeval_judges import (
                DeepEvalContextualPrecisionJudge,
                DeepEvalContextualRecallJudge,
                DeepEvalFaithfulnessJudge,
                DeepEvalHallucinationJudge,
                DeepEvalRelevanceJudge,
            )

            deepeval_judges = [
                DeepEvalFaithfulnessJudge(),
                DeepEvalRelevanceJudge(),
                DeepEvalHallucinationJudge(),
                DeepEvalContextualPrecisionJudge(),
                DeepEvalContextualRecallJudge(),
            ]
            logger.info("deepeval_judges_loaded", count=len(deepeval_judges))
        except ImportError:
            logger.warning(
                "deepeval_not_available",
                message="Install deepeval: pip install 'deepeval>=1.4.0'",
            )
            deepeval_judges = []

        return cls(
            engine=engine,
            dataset=dataset,
            deepeval_judges=deepeval_judges,
            **kwargs,
        )
