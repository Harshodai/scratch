"""
Evaluation API — Run evaluation harness from HTTP.

The WHY:
    Exposes the EvaluationRunner as an API endpoint so that:
    1. CI/CD pipelines can trigger evaluations via HTTP
    2. The CentRAG Admin dashboard can show live eval results
    3. Manual testing can be done without writing Python scripts

Design Pattern: FACADE — hides evaluation complexity behind one endpoint.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from centrag.utils.logger import get_logger

logger = get_logger("routes.evaluate")

router = APIRouter(tags=["evaluation"])


class EvaluateRequestBody(BaseModel):
    """Request body for the evaluation endpoint."""

    team_id: str = Field("eval-team", description="Team scope for evaluation")
    use_deepeval: bool = Field(False, description="Enable LLM-backed judges (requires deepeval)")
    max_cases: int = Field(0, ge=0, le=100, description="Limit cases (0 = all)")


class EvaluateResponse(BaseModel):
    """Evaluation results summary."""

    total_cases: int
    passed: int
    failed: int
    pass_rate: float
    composite_score: float
    retrieval_metrics: dict[str, float]
    per_judge: dict[str, float]
    per_difficulty: dict[str, dict[str, Any]]
    failure_summary: dict[str, Any]


@router.post("/evaluate", operation_id="evaluate", response_model=EvaluateResponse)
async def evaluate(
    body: EvaluateRequestBody,
    request: Request,
) -> EvaluateResponse:
    """Run the evaluation harness against the golden dataset.

    Executes all test cases through the live RetrievalEngine,
    scores with judges, computes IR metrics, and captures failures.

    Returns aggregate results for CI/CD gating.
    """
    from centrag.evaluation.dataset import GoldenDataset
    from centrag.evaluation.runner import EvaluationRunner

    engine = request.app.state.retrieval_engine

    dataset = GoldenDataset.sample_dataset()
    if body.max_cases > 0:
        dataset = GoldenDataset(
            cases=dataset.cases[: body.max_cases],
        )

    if body.use_deepeval:
        runner = EvaluationRunner.with_deepeval(
            engine=engine,
            dataset=dataset,
            team_id=body.team_id,
        )
    else:
        runner = EvaluationRunner(
            engine=engine,
            dataset=dataset,
            team_id=body.team_id,
        )

    report = await runner.run()
    report_dict = report.to_dict()

    return EvaluateResponse(
        total_cases=report_dict["summary"]["total_cases"],
        passed=report_dict["summary"]["passed"],
        failed=report_dict["summary"]["failed"],
        pass_rate=report_dict["summary"]["pass_rate"],
        composite_score=report_dict["summary"]["composite_score"],
        retrieval_metrics=report_dict.get("retrieval_metrics", {}),
        per_judge=report_dict.get("per_judge", {}),
        per_difficulty=report_dict.get("per_difficulty", {}),
        failure_summary=runner.failure_store.summary(),
    )
