"""
Evaluation Judges — Automated quality scoring for RAG answers.

Implements LLM-as-Judge pattern with three independent judges:
    1. FaithfulnessJudge — Is the answer grounded in the sources?
    2. RelevanceJudge — Does the answer address the query?
    3. CoverageJudge — Does the answer cover key facts from the expected answer?

Each judge produces a JudgeResult with a 0.0–1.0 score and reasoning.

Design Pattern: STRATEGY — judges are interchangeable, composable.
SOLID: Single Responsibility — each judge evaluates ONE quality dimension.
SOLID: Open/Closed — add new judges without modifying existing ones.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class JudgeResult:
    """Result from a single judge evaluation."""

    judge_name: str
    score: float  # 0.0 (bad) to 1.0 (perfect)
    reasoning: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "judge_name": self.judge_name,
            "score": round(self.score, 4),
            "reasoning": self.reasoning,
            "details": self.details,
        }


@runtime_checkable
class JudgeProtocol(Protocol):
    """Contract for evaluation judges."""

    @property
    def name(self) -> str: ...

    def evaluate(
        self,
        query: str,
        generated_answer: str,
        expected_answer: str,
        sources: list[str],
    ) -> JudgeResult: ...


class FaithfulnessJudge:
    """
    Evaluates whether the answer is grounded in the provided sources.

    Checks that claims in the generated answer can be traced back
    to the source documents. Penalizes hallucinations.

    Scoring:
        1.0 — All claims supported by sources
        0.5 — Some claims unsupported
        0.0 — No source support / hallucinated
    """

    @property
    def name(self) -> str:
        return "faithfulness"

    def evaluate(
        self,
        query: str,
        generated_answer: str,
        expected_answer: str,
        sources: list[str],
    ) -> JudgeResult:
        if not generated_answer.strip():
            return JudgeResult(
                judge_name=self.name,
                score=0.0,
                reasoning="Empty answer provided",
            )

        if not sources:
            return JudgeResult(
                judge_name=self.name,
                score=0.0,
                reasoning="No sources provided to verify faithfulness",
            )

        # Extract key phrases from the answer
        answer_words = set(self._extract_content_words(generated_answer))
        source_words = set()
        for src in sources:
            source_words.update(self._extract_content_words(src))

        if not answer_words:
            return JudgeResult(
                judge_name=self.name,
                score=0.0,
                reasoning="No meaningful content in answer",
            )

        # Calculate overlap ratio
        overlap = answer_words & source_words
        coverage = len(overlap) / len(answer_words) if answer_words else 0.0

        # Score thresholds
        if coverage >= 0.6:
            score = min(1.0, 0.5 + coverage * 0.5)
        elif coverage >= 0.3:
            score = 0.3 + coverage * 0.4
        else:
            score = coverage * 0.5

        return JudgeResult(
            judge_name=self.name,
            score=round(score, 4),
            reasoning=f"{len(overlap)}/{len(answer_words)} content words found in sources ({coverage:.0%} overlap)",
            details={
                "overlap_count": len(overlap),
                "answer_words": len(answer_words),
                "coverage_ratio": round(coverage, 4),
            },
        )

    @staticmethod
    def _extract_content_words(text: str) -> list[str]:
        """Extract meaningful content words (skip stopwords)."""
        stopwords = {
            "the",
            "a",
            "an",
            "is",
            "are",
            "was",
            "were",
            "be",
            "been",
            "being",
            "have",
            "has",
            "had",
            "do",
            "does",
            "did",
            "will",
            "would",
            "could",
            "should",
            "may",
            "might",
            "can",
            "shall",
            "in",
            "on",
            "at",
            "to",
            "for",
            "of",
            "with",
            "by",
            "from",
            "and",
            "or",
            "but",
            "not",
            "no",
            "if",
            "then",
            "so",
            "as",
            "that",
            "this",
            "it",
            "its",
            "they",
            "their",
            "them",
            "we",
            "our",
            "you",
            "your",
            "i",
            "my",
            "me",
            "he",
            "she",
            "his",
            "her",
            "what",
            "which",
            "who",
            "where",
            "when",
            "how",
            "why",
        }
        words = re.findall(r"\b[a-z]{3,}\b", text.lower())
        return [w for w in words if w not in stopwords]


class RelevanceJudge:
    """
    Evaluates whether the answer addresses the query.

    Checks that the generated answer is relevant to the question asked.
    A faithful but off-topic answer should score low.

    Scoring:
        1.0 — Directly addresses the query
        0.5 — Partially relevant
        0.0 — Off-topic
    """

    @property
    def name(self) -> str:
        return "relevance"

    def evaluate(
        self,
        query: str,
        generated_answer: str,
        expected_answer: str,
        sources: list[str],
    ) -> JudgeResult:
        if not generated_answer.strip():
            return JudgeResult(
                judge_name=self.name,
                score=0.0,
                reasoning="Empty answer provided",
            )

        # Extract query intent words
        query_words = set(FaithfulnessJudge._extract_content_words(query))
        answer_words = set(FaithfulnessJudge._extract_content_words(generated_answer))

        if not query_words:
            return JudgeResult(
                judge_name=self.name,
                score=0.5,
                reasoning="Unable to extract query intent",
            )

        # Check how many query concepts appear in the answer
        query_overlap = query_words & answer_words
        query_coverage = len(query_overlap) / len(query_words)

        # Also check if expected answer concepts are present
        expected_words = set(FaithfulnessJudge._extract_content_words(expected_answer))
        expected_overlap = expected_words & answer_words
        expected_coverage = len(expected_overlap) / len(expected_words) if expected_words else 0.0

        # Combined score: query relevance + expected answer alignment
        score = 0.4 * query_coverage + 0.6 * expected_coverage

        return JudgeResult(
            judge_name=self.name,
            score=round(min(1.0, score), 4),
            reasoning=f"Query coverage: {query_coverage:.0%}, Expected answer alignment: {expected_coverage:.0%}",
            details={
                "query_coverage": round(query_coverage, 4),
                "expected_coverage": round(expected_coverage, 4),
                "query_overlap_count": len(query_overlap),
                "expected_overlap_count": len(expected_overlap),
            },
        )


class CoverageJudge:
    """
    Evaluates whether the answer covers key facts from the expected answer.

    Checks that the generated answer includes the same key information
    as the ground truth. Measures recall of expected content.

    Scoring:
        1.0 — All key facts present
        0.5 — Some key facts missing
        0.0 — No key facts found
    """

    @property
    def name(self) -> str:
        return "coverage"

    def evaluate(
        self,
        query: str,
        generated_answer: str,
        expected_answer: str,
        sources: list[str],
    ) -> JudgeResult:
        if not generated_answer.strip():
            return JudgeResult(
                judge_name=self.name,
                score=0.0,
                reasoning="Empty answer provided",
            )

        if not expected_answer.strip():
            return JudgeResult(
                judge_name=self.name,
                score=1.0,
                reasoning="No expected answer to compare against",
            )

        # Extract key facts (content bigrams for better precision)
        expected_facts = self._extract_key_facts(expected_answer)
        generated_facts = self._extract_key_facts(generated_answer)

        if not expected_facts:
            return JudgeResult(
                judge_name=self.name,
                score=0.5,
                reasoning="Unable to extract key facts from expected answer",
            )

        # Count how many expected facts are covered
        covered = sum(1 for fact in expected_facts if fact in generated_facts)
        coverage = covered / len(expected_facts)

        return JudgeResult(
            judge_name=self.name,
            score=round(coverage, 4),
            reasoning=f"{covered}/{len(expected_facts)} key facts covered ({coverage:.0%})",
            details={
                "covered_facts": covered,
                "total_expected_facts": len(expected_facts),
                "coverage_ratio": round(coverage, 4),
            },
        )

    @staticmethod
    def _extract_key_facts(text: str) -> set[str]:
        """Extract key fact phrases (content words, lowered)."""
        words = FaithfulnessJudge._extract_content_words(text)
        # Use individual words as facts for robustness
        return set(words)
