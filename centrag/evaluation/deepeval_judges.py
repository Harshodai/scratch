"""
DeepEval Judges — LLM-backed evaluation judges using the DeepEval framework.

The WHY:
    The built-in word-overlap judges (FaithfulnessJudge, RelevanceJudge,
    CoverageJudge) are fast and deterministic but miss semantic nuance.
    These DeepEval-backed judges use real LLMs to evaluate answer quality
    with claim-level NLI verification, semantic similarity, and structured
    hallucination detection.

    They implement the same JudgeProtocol, so they are drop-in replacements
    in the evaluation harness.

    Framework Decision:
        DeepEval chosen over RAGAS (metrics-only lib, no test infra)
        and LangChain Eval (vendor lock-in to LangChain ecosystem).
        DeepEval provides Pytest-native testing, CI/CD gates, component-level
        debugging, and works with any LLM provider.

Design Pattern: ADAPTER — wraps DeepEval metrics behind our JudgeProtocol.
SOLID: Open/Closed — new judge, existing evaluation harness unchanged.
"""

from __future__ import annotations

from typing import Any

from centrag.evaluation.judges import JudgeResult
from centrag.utils.logger import get_logger

logger = get_logger("evaluation.deepeval_judges")

# Lazy imports to avoid requiring deepeval at import time
_DEEPEVAL_AVAILABLE: bool | None = None


def _check_deepeval() -> bool:
    """Check if DeepEval is installed (dev dependency, not always present)."""
    global _DEEPEVAL_AVAILABLE
    if _DEEPEVAL_AVAILABLE is None:
        try:
            import deepeval  # noqa: F401

            _DEEPEVAL_AVAILABLE = True
        except ImportError:
            _DEEPEVAL_AVAILABLE = False
            logger.warning(
                "deepeval_not_installed",
                message="DeepEval is not installed. Install with: pip install deepeval>=1.4.0",
            )
    return _DEEPEVAL_AVAILABLE


class DeepEvalFaithfulnessJudge:
    """LLM-backed faithfulness evaluation using DeepEval's FaithfulnessMetric.

    The WHY:
        Claims in the answer are decomposed and individually verified
        against the source documents using NLI (Natural Language Inference).
        This catches semantic hallucinations that word-overlap misses, e.g.,
        "Revenue grew 15%" in the answer when sources say "Revenue fell 15%".

    Scoring:
        1.0 — All claims are supported by sources
        0.0 — All claims are hallucinated
    """

    @property
    def name(self) -> str:
        return "deepeval_faithfulness"

    def evaluate(
        self,
        query: str,
        generated_answer: str,
        expected_answer: str,
        sources: list[str],
    ) -> JudgeResult:
        if not _check_deepeval():
            return JudgeResult(
                judge_name=self.name,
                score=0.0,
                reasoning="DeepEval not installed — cannot run LLM-backed evaluation",
            )

        if not generated_answer.strip():
            return JudgeResult(judge_name=self.name, score=0.0, reasoning="Empty answer")

        try:
            from deepeval.metrics import FaithfulnessMetric
            from deepeval.test_case import LLMTestCase

            test_case = LLMTestCase(
                input=query,
                actual_output=generated_answer,
                retrieval_context=sources,
            )

            metric = FaithfulnessMetric(threshold=0.5)
            metric.measure(test_case)

            return JudgeResult(
                judge_name=self.name,
                score=round(metric.score, 4),
                reasoning=metric.reason or "DeepEval faithfulness evaluation",
                details={
                    "threshold": metric.threshold,
                    "framework": "deepeval",
                },
            )

        except Exception as e:
            logger.warning("deepeval_faithfulness_failed", error=str(e))
            return JudgeResult(
                judge_name=self.name,
                score=0.0,
                reasoning=f"DeepEval evaluation failed: {e}",
            )


class DeepEvalRelevanceJudge:
    """LLM-backed answer relevance evaluation using DeepEval's AnswerRelevancyMetric.

    The WHY:
        Checks whether the generated answer semantically addresses the
        user's question. A word-overlap judge might score "The company
        revenue was high" as relevant to "What was the revenue?" but miss
        that it doesn't actually answer the question with specifics.

    Scoring:
        1.0 — Answer directly and completely addresses the query
        0.0 — Answer is off-topic
    """

    @property
    def name(self) -> str:
        return "deepeval_relevance"

    def evaluate(
        self,
        query: str,
        generated_answer: str,
        expected_answer: str,
        sources: list[str],
    ) -> JudgeResult:
        if not _check_deepeval():
            return JudgeResult(
                judge_name=self.name,
                score=0.0,
                reasoning="DeepEval not installed",
            )

        if not generated_answer.strip():
            return JudgeResult(judge_name=self.name, score=0.0, reasoning="Empty answer")

        try:
            from deepeval.metrics import AnswerRelevancyMetric
            from deepeval.test_case import LLMTestCase

            test_case = LLMTestCase(
                input=query,
                actual_output=generated_answer,
                retrieval_context=sources,
            )

            metric = AnswerRelevancyMetric(threshold=0.5)
            metric.measure(test_case)

            return JudgeResult(
                judge_name=self.name,
                score=round(metric.score, 4),
                reasoning=metric.reason or "DeepEval relevance evaluation",
                details={"threshold": metric.threshold, "framework": "deepeval"},
            )

        except Exception as e:
            logger.warning("deepeval_relevance_failed", error=str(e))
            return JudgeResult(
                judge_name=self.name,
                score=0.0,
                reasoning=f"DeepEval evaluation failed: {e}",
            )


class DeepEvalHallucinationJudge:
    """LLM-backed hallucination detection using DeepEval's HallucinationMetric.

    The WHY:
        Explicitly detects fabricated facts NOT present in any source.
        Unlike faithfulness which checks "are claims supported?",
        hallucination detection asks "did the model invent facts?"
        These are complementary but distinct signals.

    Scoring:
        1.0 — No hallucinations detected
        0.0 — Answer is entirely hallucinated
    """

    @property
    def name(self) -> str:
        return "deepeval_hallucination"

    def evaluate(
        self,
        query: str,
        generated_answer: str,
        expected_answer: str,
        sources: list[str],
    ) -> JudgeResult:
        if not _check_deepeval():
            return JudgeResult(
                judge_name=self.name,
                score=0.0,
                reasoning="DeepEval not installed",
            )

        if not generated_answer.strip():
            return JudgeResult(judge_name=self.name, score=0.0, reasoning="Empty answer")

        # HallucinationMetric uses `context` (the source docs)
        try:
            from deepeval.metrics import HallucinationMetric
            from deepeval.test_case import LLMTestCase

            test_case = LLMTestCase(
                input=query,
                actual_output=generated_answer,
                context=sources,
            )

            metric = HallucinationMetric(threshold=0.5)
            metric.measure(test_case)

            # HallucinationMetric: score closer to 0 means MORE hallucination.
            return JudgeResult(
                judge_name=self.name,
                score=round(metric.score, 4),
                reasoning=metric.reason or "DeepEval hallucination evaluation",
                details={"threshold": metric.threshold, "framework": "deepeval"},
            )

        except Exception as e:
            logger.warning("deepeval_hallucination_failed", error=str(e))
            return JudgeResult(
                judge_name=self.name,
                score=0.0,
                reasoning=f"DeepEval evaluation failed: {e}",
            )


class DeepEvalContextualPrecisionJudge:
    """LLM-backed contextual precision — are the retrieved chunks relevant?

    The WHY:
        Measures whether the retriever returned chunks that actually
        helped answer the question. Irrelevant chunks are noise that
        dilute the LLM's attention and increase costs.

    Scoring:
        1.0 — All retrieved chunks are relevant to the query
        0.0 — None of the retrieved chunks are relevant
    """

    @property
    def name(self) -> str:
        return "deepeval_contextual_precision"

    def evaluate(
        self,
        query: str,
        generated_answer: str,
        expected_answer: str,
        sources: list[str],
    ) -> JudgeResult:
        if not _check_deepeval():
            return JudgeResult(
                judge_name=self.name,
                score=0.0,
                reasoning="DeepEval not installed",
            )

        try:
            from deepeval.metrics import ContextualPrecisionMetric
            from deepeval.test_case import LLMTestCase

            test_case = LLMTestCase(
                input=query,
                actual_output=generated_answer,
                expected_output=expected_answer,
                retrieval_context=sources,
            )

            metric = ContextualPrecisionMetric(threshold=0.5)
            metric.measure(test_case)

            return JudgeResult(
                judge_name=self.name,
                score=round(metric.score, 4),
                reasoning=metric.reason or "DeepEval contextual precision evaluation",
                details={"threshold": metric.threshold, "framework": "deepeval"},
            )

        except Exception as e:
            logger.warning("deepeval_contextual_precision_failed", error=str(e))
            return JudgeResult(
                judge_name=self.name,
                score=0.0,
                reasoning=f"DeepEval evaluation failed: {e}",
            )


class DeepEvalContextualRecallJudge:
    """LLM-backed contextual recall — did we retrieve ALL relevant chunks?

    The WHY:
        Measures whether the retriever found all the information needed
        to answer the question. Missing critical chunks means the LLM
        will produce incomplete or wrong answers.

    Scoring:
        1.0 — All expected information is present in retrieved chunks
        0.0 — None of the expected information was retrieved
    """

    @property
    def name(self) -> str:
        return "deepeval_contextual_recall"

    def evaluate(
        self,
        query: str,
        generated_answer: str,
        expected_answer: str,
        sources: list[str],
    ) -> JudgeResult:
        if not _check_deepeval():
            return JudgeResult(
                judge_name=self.name,
                score=0.0,
                reasoning="DeepEval not installed",
            )

        try:
            from deepeval.metrics import ContextualRecallMetric
            from deepeval.test_case import LLMTestCase

            test_case = LLMTestCase(
                input=query,
                actual_output=generated_answer,
                expected_output=expected_answer,
                retrieval_context=sources,
            )

            metric = ContextualRecallMetric(threshold=0.5)
            metric.measure(test_case)

            return JudgeResult(
                judge_name=self.name,
                score=round(metric.score, 4),
                reasoning=metric.reason or "DeepEval contextual recall evaluation",
                details={"threshold": metric.threshold, "framework": "deepeval"},
            )

        except Exception as e:
            logger.warning("deepeval_contextual_recall_failed", error=str(e))
            return JudgeResult(
                judge_name=self.name,
                score=0.0,
                reasoning=f"DeepEval evaluation failed: {e}",
            )
