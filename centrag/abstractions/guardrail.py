"""
Guardrail abstraction — composable input/output validation rails.

SOLID: Single Responsibility — each rail does ONE check.
       PromptInjectionRail only detects injections.
       PIIRedactionRail only redacts PII.
       They are composed by GuardrailChain, not tangled together.

SOLID: Open/Closed — add new rails without modifying the chain.
       Implement InputRailProtocol or OutputRailProtocol and register.

SOLID: Dependency Inversion — RetrievalEngine depends on GuardrailChain
       (an abstraction), not on specific guardrail functions.

Design Pattern: CHAIN OF RESPONSIBILITY
    - GuardrailChain runs rails in order: rail_1 → rail_2 → rail_3
    - Each rail can short-circuit (raise) or pass through

Design Pattern: COMPOSITE PATTERN
    - GuardrailChain IS-A InputRailProtocol (recursive composition)
    - You can nest chains inside chains for domain-specific pipelines
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class RailContext:
    """
    Immutable context passed through the guardrail chain.

    Carries request metadata needed for policy decisions
    (team identity, namespace, tier) without coupling rails
    to FastAPI or any specific framework.
    """
    team_id: str
    namespace: str = "default"
    tier: str = "standard"  # "standard" | "premium" | "enterprise"
    request_id: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ValidatedQuery:
    """Result of input rail validation. Carries the cleaned query."""
    original_query: str
    sanitized_query: str
    flags: list[str] = field(default_factory=list)  # e.g., ["pii_detected"]


@dataclass(frozen=True)
class ValidatedResponse:
    """Result of output rail validation. Carries the cleaned response."""
    original_answer: str
    sanitized_answer: str
    redactions_applied: list[str] = field(default_factory=list)  # e.g., ["ssn", "email"]
    flags: list[str] = field(default_factory=list)


class GuardrailViolation(Exception):
    """Raised when a guardrail blocks a request or response."""

    def __init__(self, rail_name: str, message: str, severity: str = "block"):
        self.rail_name = rail_name
        self.severity = severity  # "block" | "warn" | "log"
        super().__init__(f"[{rail_name}] {message}")


@runtime_checkable
class InputRailProtocol(Protocol):
    """Contract for input validation rails."""

    @property
    def name(self) -> str:
        """Human-readable rail name for audit logs."""
        ...

    async def validate(
        self,
        query: str,
        context: RailContext,
    ) -> str:
        """
        Validate and optionally transform the input query.

        Returns:
            Cleaned/validated query string.

        Raises:
            GuardrailViolation if the query is blocked.
        """
        ...


@runtime_checkable
class OutputRailProtocol(Protocol):
    """Contract for output validation rails."""

    @property
    def name(self) -> str:
        """Human-readable rail name for audit logs."""
        ...

    async def validate(
        self,
        answer: str,
        sources: list[Any],
        context: RailContext,
    ) -> str:
        """
        Validate and optionally transform the LLM response.

        Returns:
            Cleaned/validated response string.

        Raises:
            GuardrailViolation if the response is blocked.
        """
        ...
