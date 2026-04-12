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
    """Immutable context passed through the guardrail chain.

    The WHY:
        Allows safety rails to make policy decisions (e.g., "Allow PII
        for Enterprise tier") without being coupled to the underlying
        web framework or database. It acts as a "State Carrier" during
        the request lifecycle.

    Attributes:
        team_id: Unique UUID of the tenant.
        namespace: Logical grouping (e.g., 'internal-docs').
        tier: Customer service level (Standard, Premium, Enterprise).
        request_id: Correlation ID for distributed tracing.
        extra: Flexible container for domain-specific context (e.g., custom user roles).
    """

    team_id: str
    namespace: str = "default"
    tier: str = "standard"  # "standard" | "premium" | "enterprise"
    request_id: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ValidatedQuery:
    """Result of input rail validation containing the cleaned query.

    The WHY:
        Ensures that downstream retrieval only sees "sanitized"
        information. If a rail redacts PII or removes SQL injection
        attempts, this object preserves both the audit trail and
        the safe content.
    """

    original_query: str
    sanitized_query: str
    flags: list[str] = field(default_factory=list)  # e.g., ["pii_detected"]


@dataclass(frozen=True)
class ValidatedResponse:
    """Result of output rail validation containing the cleaned response.

    The WHY:
        Prevents the LLM from leaking sensitive data (SSNs, API keys)
        that may have existed in the retrieved source chunks. It is
        the final "Quality Check" before a user sees an answer.
    """

    original_answer: str
    sanitized_answer: str
    redactions_applied: list[str] = field(default_factory=list)  # e.g., ["ssn", "email"]
    flags: list[str] = field(default_factory=list)


class GuardrailViolation(Exception):
    """Exception raised when a guardrail blocks a request or response.

    The WHY:
        Provides a structured way to short-circuit the RAG pipeline.
        The RetrievalEngine catches this and returns a safe,
        non-technical error message to the user while logging
        the specific violation for security audits.
    """

    def __init__(self, rail_name: str, message: str, severity: str = "block"):
        self.rail_name = rail_name
        self.severity = severity  # "block" | "warn" | "log"
        super().__init__(f"[{rail_name}] {message}")


@runtime_checkable
class InputRailProtocol(Protocol):
    """Contract for input validation rails (Pre-Retrieval).

    The WHY:
        Implemented using the CHAIN OF RESPONSIBILITY pattern.
        Each rail (e.g., Prompt Injection detection, PII scrubbing)
        processes the query before it hits the vector store.
    """

    @property
    def name(self) -> str:
        """Human-readable rail name for audit logs."""
        ...

    async def validate(
        self,
        query: str,
        context: RailContext,
    ) -> str:
        """Validate and optionally transform the input query.

        Args:
            query: The raw string from the user.
            context: Metadata about the team and request.

        Returns:
            str: The cleaned/validated query string.

        Raises:
            GuardrailViolation: If the query violates safety policies.
        """
        ...


@runtime_checkable
class OutputRailProtocol(Protocol):
    """Contract for output validation rails (Post-Generation).

    The WHY:
        Final safety check. It verifies that the LLM's generated
        answer is grounded in the sources and doesn't contain
        prohibited content or sensitive data.
    """

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
        """Validate and optionally transform the LLM response.

        Args:
            answer: Raw text generated by the LLM.
            sources: The chunks used to ground the answer.
            context: Request metadata.

        Returns:
            str: The final, safe response string.

        Raises:
            GuardrailViolation: If blocking/filtering/redaction is required or groundedness is low.
        """
        ...
