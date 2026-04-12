"""
Observability Protocol — SOLID abstraction for metrics, tracing, and logging.

Design Pattern: STRATEGY + DECORATOR
    - ObservabilityProtocol defines the contract
    - Concrete implementations: OpenTelemetry, Langfuse, Console (free)
    - Used as decorators/context managers around pipeline steps

SOLID Principles:
    - S: Each provider does ONE thing (metrics OR tracing OR logging)
    - O: Add new providers without modifying existing ones
    - L: Any provider can substitute another (Protocol conformance)
    - I: Separate protocols for Metrics, Tracing, Logging
    - D: Engine depends on abstractions, not concrete providers

FREE Observability Options (ranked by production readiness):
    ┌────────────────────────────────────────────────────────────────┐
    │  Tier 1 — Zero Cost, Self-Hosted                              │
    │  • OpenTelemetry + Prometheus + Grafana (LGTM stack)          │
    │  • Langfuse self-hosted (MIT license, full features)          │
    │  • structlog + JSON → any log aggregator                      │
    ├────────────────────────────────────────────────────────────────┤
    │  Tier 2 — Free Tiers (managed)                                │
    │  • Langfuse Cloud: 50k observations/month free                │
    │  • Grafana Cloud: 10k metrics, 50GB logs free                 │
    │  • SigNoz Cloud: 30-day retention free                        │
    ├────────────────────────────────────────────────────────────────┤
    │  Tier 3 — Development Only                                    │
    │  • ConsoleObserver (built-in, zero dependencies)              │
    │  • Jaeger all-in-one (docker, local tracing)                  │
    └────────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

# =============================================================================
# Data Types
# =============================================================================


class SpanKind(StrEnum):
    RETRIEVAL = "retrieval"
    EMBEDDING = "embedding"
    GENERATION = "generation"
    RERANKING = "reranking"
    GUARDRAIL = "guardrail"
    CACHE = "cache"
    MEMORY = "memory"
    TOOL = "tool"


@dataclass
class SpanContext:
    """Mutable context for a traced span."""

    name: str
    kind: SpanKind
    start_time: float = field(default_factory=time.monotonic)
    end_time: float | None = None
    attributes: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)
    status: str = "OK"
    error: str | None = None

    @property
    def duration_ms(self) -> float:
        if self.end_time is None:
            return (time.monotonic() - self.start_time) * 1000
        return (self.end_time - self.start_time) * 1000


@dataclass(frozen=True)
class MetricPoint:
    """A single metric data point."""

    name: str
    value: float
    tags: dict[str, str] = field(default_factory=dict)
    unit: str = ""


# =============================================================================
# Protocols (Interface Segregation)
# =============================================================================


@runtime_checkable
class TracingProtocol(Protocol):
    """Contract for distributed tracing providers."""

    @asynccontextmanager
    async def span(
        self,
        name: str,
        kind: SpanKind,
        attributes: dict[str, Any] | None = None,
    ) -> AsyncIterator[SpanContext]:
        """Create a traced span as an async context manager."""
        ...

    async def flush(self) -> None:
        """Flush pending traces to the backend."""
        ...


@runtime_checkable
class MetricsProtocol(Protocol):
    """Contract for metrics collection."""

    def counter(self, name: str, value: float = 1.0, tags: dict[str, str] | None = None) -> None:
        """Increment a counter metric."""
        ...

    def histogram(self, name: str, value: float, tags: dict[str, str] | None = None) -> None:
        """Record a histogram/distribution value."""
        ...

    def gauge(self, name: str, value: float, tags: dict[str, str] | None = None) -> None:
        """Set a gauge metric."""
        ...


@runtime_checkable
class CostTrackingProtocol(Protocol):
    """Contract for LLM cost tracking (Langfuse-compatible)."""

    async def track_generation(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        latency_ms: float,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Track a single LLM generation for cost analysis."""
        ...

    async def track_embedding(
        self,
        model: str,
        input_tokens: int,
        dimension: int,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Track an embedding call."""
        ...

    async def get_usage_summary(
        self,
        team_id: str,
        period: str = "day",
    ) -> dict[str, Any]:
        """Get usage summary for a team (for budget gating)."""
        ...
