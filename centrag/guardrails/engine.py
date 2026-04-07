"""
GuardrailEngine — Composable guardrail chain for the RAG pipeline.

REPLACES the old flat guardrails.py with a proper composable pipeline.
Implements Chain of Responsibility + Composite pattern.

Architecture:
  ┌──────────────────────────────────────────────────────┐
  │                  GuardrailEngine                      │
  ├──────────────────────────────────────────────────────┤
  │  INPUT RAILS (run before retrieval):                 │
  │    1. PromptInjectionRail                            │
  │    2. InputLengthRail                                │
  │    3. NamespaceAccessRail                            │
  │    4. InputPIIDetectionRail                          │
  │    5. BudgetGateRail                                 │
  ├──────────────────────────────────────────────────────┤
  │  OUTPUT RAILS (run after LLM generation):            │
  │    1. ResponseLengthRail                             │
  │    2. ConfidenceGateRail                             │
  │    3. OutputPIIRedactionRail                         │
  │    4. BlockedPatternRail                             │
  └──────────────────────────────────────────────────────┘

Each rail is independently testable, configurable, and toggleable.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import structlog

from centrag.abstractions.guardrail import (
    InputRailProtocol,
    OutputRailProtocol,
    RailContext,
    GuardrailViolation,
)
from centrag.guardrails.pii import PII_PATTERNS, redact_pii, detect_pii

logger = structlog.get_logger("guardrails.engine")


# =============================================================================
# Configuration — Policy-as-Code
# =============================================================================

@dataclass(frozen=True)
class GuardrailsConfig:
    """
    Complete guardrails configuration. Previously declared but unused (L328-335).
    Now actually wired into GuardrailEngine.
    """
    # Input validation
    max_query_length: int = 2000
    min_query_length: int = 3
    enable_prompt_injection_detection: bool = True
    enable_namespace_access_control: bool = True
    enable_input_pii_detection: bool = True
    enable_budget_gate: bool = True
    allowed_namespaces: list[str] = field(default_factory=list)

    # Output validation
    max_response_length: int = 10_000
    max_sources: int = 20
    require_sources: bool = True
    min_confidence_threshold: float = 0.3
    enable_output_pii_redaction: bool = True
    enable_blocked_pattern_filter: bool = True

    # Prompt injection patterns
    blocked_input_patterns: list[str] = field(default_factory=lambda: [
        r"ignore\s+(?:previous|all|above)\s+instructions",
        r"system\s*prompt",
        r"you\s+are\s+now",
        r"reveal\s+(?:your|the)\s+(?:system|initial)",
        r"<\s*script",
        r"(?:DROP|DELETE|TRUNCATE)\s+TABLE",
        r"UNION\s+SELECT",
    ])

    # Blocked output patterns (LLM leaks)
    blocked_output_patterns: list[str] = field(default_factory=lambda: [
        r"as\s+an\s+ai\s+(?:language\s+)?model",
        r"I\s+(?:cannot|can't)\s+access",
    ])


# =============================================================================
# Input Rails
# =============================================================================

class PromptInjectionRail:
    """Detect and block prompt injection attempts."""

    def __init__(self, patterns: list[str]) -> None:
        self._patterns = [re.compile(p, re.IGNORECASE) for p in patterns]

    @property
    def name(self) -> str:
        return "prompt_injection"

    async def validate(self, query: str, context: RailContext) -> str:
        for pattern in self._patterns:
            if pattern.search(query):
                logger.warning(
                    "prompt_injection_blocked",
                    team_id=context.team_id,
                    pattern=pattern.pattern,
                    query_preview=query[:50],
                )
                raise GuardrailViolation(
                    self.name,
                    "Query contains blocked content. This attempt has been logged.",
                    severity="block",
                )
        return query


class InputLengthRail:
    """Enforce query length bounds."""

    def __init__(self, min_length: int = 3, max_length: int = 2000) -> None:
        self._min = min_length
        self._max = max_length

    @property
    def name(self) -> str:
        return "input_length"

    async def validate(self, query: str, context: RailContext) -> str:
        stripped = query.strip()
        if len(stripped) < self._min:
            raise GuardrailViolation(
                self.name, f"Query too short (minimum {self._min} characters)."
            )
        if len(stripped) > self._max:
            raise GuardrailViolation(
                self.name, f"Query too long (maximum {self._max} characters)."
            )
        return stripped


class NamespaceAccessRail:
    """Enforce namespace-level access control."""

    def __init__(self, allowed_namespaces: list[str]) -> None:
        self._allowed = allowed_namespaces

    @property
    def name(self) -> str:
        return "namespace_access"

    async def validate(self, query: str, context: RailContext) -> str:
        if self._allowed and context.namespace not in self._allowed:
            raise GuardrailViolation(
                self.name,
                f"Namespace '{context.namespace}' is not in allowed namespaces.",
                severity="block",
            )
        return query


class InputPIIDetectionRail:
    """Detect PII in input queries (flag, don't block)."""

    @property
    def name(self) -> str:
        return "input_pii_detection"

    async def validate(self, query: str, context: RailContext) -> str:
        pii_found = detect_pii(query)
        if pii_found:
            logger.warning(
                "pii_detected_in_query",
                team_id=context.team_id,
                pii_types=pii_found,
                query_preview=query[:50],
            )
        return query  # Flag only, don't block


class BudgetGateRail:
    """Check cost budget before processing."""

    def __init__(self, cost_tracker: Any = None) -> None:
        self._tracker = cost_tracker

    @property
    def name(self) -> str:
        return "budget_gate"

    async def validate(self, query: str, context: RailContext) -> str:
        if self._tracker is None:
            return query  # No tracker configured, skip

        within_budget = await self._tracker.check_budget(
            context.team_id, context.tier
        )
        if not within_budget:
            raise GuardrailViolation(
                self.name,
                f"Token budget exceeded for tier '{context.tier}'. "
                f"Please upgrade or wait for the next billing period.",
                severity="block",
            )
        return query


# =============================================================================
# Output Rails
# =============================================================================

class ResponseLengthRail:
    """Truncate overlong responses."""

    def __init__(self, max_length: int = 10_000) -> None:
        self._max = max_length

    @property
    def name(self) -> str:
        return "response_length"

    async def validate(
        self, answer: str, sources: list[Any], context: RailContext
    ) -> str:
        if len(answer) > self._max:
            return answer[:self._max] + "\n\n[Response truncated]"
        return answer


class ConfidenceGateRail:
    """Apply confidence warnings when retrieval quality is low."""

    def __init__(self, min_threshold: float = 0.3) -> None:
        self._threshold = min_threshold

    @property
    def name(self) -> str:
        return "confidence_gate"

    async def validate(
        self, answer: str, sources: list[Any], context: RailContext
    ) -> str:
        if not sources:
            return (
                "I could not find relevant sources to answer this question confidently. "
                "Try rephrasing your query or uploading additional documents."
            )

        # Calculate average confidence from sources
        scores = [
            s.relevance_score for s in sources
            if hasattr(s, "relevance_score")
        ]
        if scores:
            avg = sum(scores) / len(scores)
            if avg < self._threshold:
                return (
                    f"⚠️ Low confidence ({avg:.0%}): {answer}\n\n"
                    "The retrieved documents may not be highly relevant to your question."
                )
        return answer


class OutputPIIRedactionRail:
    """Redact PII from LLM output before returning to user."""

    @property
    def name(self) -> str:
        return "output_pii_redaction"

    async def validate(
        self, answer: str, sources: list[Any], context: RailContext
    ) -> str:
        return redact_pii(answer)


class BlockedPatternRail:
    """Remove LLM self-reference leaks from output."""

    def __init__(self, patterns: list[str]) -> None:
        self._patterns = [re.compile(p, re.IGNORECASE) for p in patterns]

    @property
    def name(self) -> str:
        return "blocked_pattern"

    async def validate(
        self, answer: str, sources: list[Any], context: RailContext
    ) -> str:
        for pattern in self._patterns:
            answer = pattern.sub("[REDACTED]", answer)
        return answer


# =============================================================================
# GuardrailEngine — Composite
# =============================================================================

class GuardrailEngine:
    """
    Composite guardrail engine — runs configured rails in order.

    Usage:
        config = GuardrailsConfig()
        engine = GuardrailEngine(config)

        # In RetrievalEngine.__init__():
        input_rails=engine.input_rails,
        output_rails=engine.output_rails,
    """

    def __init__(self, config: GuardrailsConfig | None = None) -> None:
        self.config = config or GuardrailsConfig()
        self._input_rails: list[InputRailProtocol] = []
        self._output_rails: list[OutputRailProtocol] = []
        self._build_rails()

    def _build_rails(self) -> None:
        """Construct rail chain from config."""
        cfg = self.config

        # Input rails (order matters)
        self._input_rails.append(
            InputLengthRail(cfg.min_query_length, cfg.max_query_length)
        )
        if cfg.enable_prompt_injection_detection:
            self._input_rails.append(
                PromptInjectionRail(cfg.blocked_input_patterns)
            )
        if cfg.enable_namespace_access_control and cfg.allowed_namespaces:
            self._input_rails.append(
                NamespaceAccessRail(cfg.allowed_namespaces)
            )
        if cfg.enable_input_pii_detection:
            self._input_rails.append(InputPIIDetectionRail())
        if cfg.enable_budget_gate:
            self._input_rails.append(BudgetGateRail())

        # Output rails (order matters)
        self._output_rails.append(
            ResponseLengthRail(cfg.max_response_length)
        )
        self._output_rails.append(
            ConfidenceGateRail(cfg.min_confidence_threshold)
        )
        if cfg.enable_output_pii_redaction:
            self._output_rails.append(OutputPIIRedactionRail())
        if cfg.enable_blocked_pattern_filter:
            self._output_rails.append(
                BlockedPatternRail(cfg.blocked_output_patterns)
            )

    @property
    def input_rails(self) -> list[InputRailProtocol]:
        """Get input rails for injection into RetrievalEngine."""
        return self._input_rails

    @property
    def output_rails(self) -> list[OutputRailProtocol]:
        """Get output rails for injection into RetrievalEngine."""
        return self._output_rails

    def add_input_rail(self, rail: InputRailProtocol) -> None:
        """Add a custom input rail (e.g., domain-specific validation)."""
        self._input_rails.append(rail)

    def add_output_rail(self, rail: OutputRailProtocol) -> None:
        """Add a custom output rail."""
        self._output_rails.append(rail)
