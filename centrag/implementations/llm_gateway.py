"""
LLM Gateway — Resilient LLM proxy with circuit breaker + cost tracking.

SHARED INFRASTRUCTURE: Wraps any LLMProtocol with production guardrails.

Features:
    1. Circuit Breaker — prevents cascading failures when LLM provider is down
    2. Cost Tracking — per-team token budgets with real-time enforcement
    3. Latency Monitoring — histogram P50/P95/P99 tracking
    4. Model Routing — Adaptive RAG: simple→cheap, complex→frontier
    5. Retry with Backoff — transient error recovery

Design Pattern: DECORATOR — wraps LLMProtocol without modifying implementations.

SOLID: Single Responsibility — only resilience + observability. No generation logic.
SOLID: Open/Closed — add new resilience patterns without modifying LLM impls.
SOLID: Liskov Substitution — LLMGateway IS-A LLMProtocol to callers.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from enum import Enum
from typing import Any

from centrag.abstractions.llm import LLMProtocol, LLMResponse, QueryComplexity
from centrag.utils.logger import get_logger

logger = get_logger("llm_gateway")


# ── Circuit Breaker ─────────────────────────────────────────────────


class CircuitState(str, Enum):
    """Circuit breaker states."""

    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Failing — reject all calls
    HALF_OPEN = "half_open"  # Testing recovery — allow 1 call


@dataclass
class CircuitBreakerConfig:
    """Policy for circuit breaker behavior."""

    failure_threshold: int = 5  # Consecutive failures to trip
    recovery_timeout: float = 30.0  # Seconds before half-open
    success_threshold: int = 2  # Consecutive successes to close


class CircuitBreaker:
    """
    Circuit breaker for LLM API calls.

    State transitions:
        CLOSED → OPEN: after `failure_threshold` consecutive failures
        OPEN → HALF_OPEN: after `recovery_timeout` seconds
        HALF_OPEN → CLOSED: after `success_threshold` consecutive successes
        HALF_OPEN → OPEN: on any failure
    """

    def __init__(self, config: CircuitBreakerConfig | None = None) -> None:
        self._config = config or CircuitBreakerConfig()
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time = 0.0

    @property
    def state(self) -> CircuitState:
        """Current state with automatic OPEN → HALF_OPEN transition."""
        if self._state == CircuitState.OPEN:
            elapsed = time.monotonic() - self._last_failure_time
            if elapsed >= self._config.recovery_timeout:
                self._state = CircuitState.HALF_OPEN
                self._success_count = 0
                logger.info("circuit_half_open", elapsed_seconds=elapsed)
        return self._state

    def record_success(self) -> None:
        """Record a successful call."""
        if self._state == CircuitState.HALF_OPEN:
            self._success_count += 1
            if self._success_count >= self._config.success_threshold:
                self._state = CircuitState.CLOSED
                self._failure_count = 0
                logger.info("circuit_closed", after_successes=self._success_count)
        else:
            self._failure_count = 0

    def record_failure(self) -> None:
        """Record a failed call."""
        self._failure_count += 1
        self._last_failure_time = time.monotonic()

        if self._state == CircuitState.HALF_OPEN:
            self._state = CircuitState.OPEN
            logger.warning("circuit_reopened", from_state="half_open")
        elif self._failure_count >= self._config.failure_threshold:
            self._state = CircuitState.OPEN
            logger.warning(
                "circuit_opened",
                failure_count=self._failure_count,
                threshold=self._config.failure_threshold,
            )

    @property
    def is_call_allowed(self) -> bool:
        """Can we make a call right now?"""
        return self.state != CircuitState.OPEN


# ── Cost Tracker ────────────────────────────────────────────────────


@dataclass
class CostRecord:
    """Per-team cost tracking record."""

    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_calls: int = 0
    total_cost_usd: float = 0.0
    last_call_time: float = 0.0


class CostTracker:
    """
    In-memory per-team cost tracking with budget enforcement.

    Production: Replace with Redis-backed tracker for multi-process.
    """

    # Model pricing (input $/1M tokens, output $/1M tokens)
    MODEL_PRICING: dict[str, tuple[float, float]] = {
        "gpt-4o": (2.50, 10.0),
        "gpt-4o-mini": (0.15, 0.60),
        "gpt-4-turbo": (10.0, 30.0),
        "claude-3-5-sonnet": (3.0, 15.0),
        "claude-3-haiku": (0.25, 1.25),
        "noop-llm-v1": (0.0, 0.0),
    }

    def __init__(self, default_budget_usd: float = 10.0) -> None:
        self._records: dict[str, CostRecord] = {}
        self._budgets: dict[str, float] = {}
        self._default_budget = default_budget_usd

    def track(
        self,
        team_id: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> float:
        """Track a call and return the cost in USD."""
        input_price, output_price = self.MODEL_PRICING.get(model, (5.0, 15.0))
        cost = (input_tokens * input_price + output_tokens * output_price) / 1_000_000

        record = self._records.setdefault(team_id, CostRecord())
        record.total_input_tokens += input_tokens
        record.total_output_tokens += output_tokens
        record.total_calls += 1
        record.total_cost_usd += cost
        record.last_call_time = time.monotonic()

        return cost

    def get_remaining_budget(self, team_id: str) -> float:
        """Get remaining budget for a team."""
        budget = self._budgets.get(team_id, self._default_budget)
        spent = self._records.get(team_id, CostRecord()).total_cost_usd
        return max(0.0, budget - spent)

    def is_within_budget(self, team_id: str) -> bool:
        """Check if team has remaining budget."""
        return self.get_remaining_budget(team_id) > 0

    def set_budget(self, team_id: str, budget_usd: float) -> None:
        """Set custom budget for a team."""
        self._budgets[team_id] = budget_usd

    def get_usage(self, team_id: str) -> dict[str, Any]:
        """Get usage summary for a team."""
        record = self._records.get(team_id, CostRecord())
        budget = self._budgets.get(team_id, self._default_budget)
        return {
            "team_id": team_id,
            "total_calls": record.total_calls,
            "total_input_tokens": record.total_input_tokens,
            "total_output_tokens": record.total_output_tokens,
            "total_cost_usd": round(record.total_cost_usd, 6),
            "budget_usd": budget,
            "remaining_usd": round(max(0, budget - record.total_cost_usd), 6),
        }

    def reset(self, team_id: str) -> None:
        """Reset usage for a team (e.g., monthly reset)."""
        self._records.pop(team_id, None)


# ── Latency Monitor ────────────────────────────────────────────────


class LatencyMonitor:
    """
    Simple latency histogram for LLM calls.

    Tracks percentiles (P50, P95, P99) over a sliding window.
    """

    def __init__(self, window_size: int = 100) -> None:
        self._window: list[float] = []
        self._max_size = window_size

    def record(self, latency_ms: float) -> None:
        """Record a latency measurement."""
        self._window.append(latency_ms)
        if len(self._window) > self._max_size:
            self._window.pop(0)

    def percentile(self, p: float) -> float:
        """Get the p-th percentile latency."""
        if not self._window:
            return 0.0
        sorted_vals = sorted(self._window)
        idx = int(len(sorted_vals) * p / 100.0)
        idx = min(idx, len(sorted_vals) - 1)
        return sorted_vals[idx]

    @property
    def stats(self) -> dict[str, float]:
        """Get latency statistics."""
        return {
            "p50_ms": round(self.percentile(50), 2),
            "p95_ms": round(self.percentile(95), 2),
            "p99_ms": round(self.percentile(99), 2),
            "count": len(self._window),
        }


# ── Model Router ────────────────────────────────────────────────────


@dataclass(frozen=True)
class ModelRoutingConfig:
    """Map query complexity to LLM models."""

    simple_model: str = "gpt-4o-mini"
    moderate_model: str = "gpt-4o"
    complex_model: str = "gpt-4o"


# ── LLM Gateway ────────────────────────────────────────────────────


class LLMGateway:
    """
    Production LLM proxy with resilience and observability.

    Wraps any LLMProtocol with:
        - Circuit breaker (prevent cascading failures)
        - Cost tracking (per-team budgets)
        - Latency monitoring (P50/P95/P99)
        - Retry with backoff (transient recovery)

    SOLID: Decorator Pattern — LLMGateway IS-A LLMProtocol.

    Usage:
        llm = NoOpLLM()
        gateway = LLMGateway(llm, team_id="team-1")
        response = await gateway.generate("What is X?", ["context..."])
    """

    def __init__(
        self,
        llm: LLMProtocol,
        team_id: str = "default",
        circuit_config: CircuitBreakerConfig | None = None,
        cost_tracker: CostTracker | None = None,
        max_retries: int = 3,
        base_backoff: float = 1.0,
    ) -> None:
        self._llm = llm
        self._team_id = team_id
        self._circuit = CircuitBreaker(circuit_config)
        self._cost_tracker = cost_tracker or CostTracker()
        self._latency = LatencyMonitor()
        self._max_retries = max_retries
        self._base_backoff = base_backoff

    @property
    def circuit_state(self) -> CircuitState:
        return self._circuit.state

    @property
    def latency_stats(self) -> dict[str, float]:
        return self._latency.stats

    @property
    def usage(self) -> dict[str, Any]:
        return self._cost_tracker.get_usage(self._team_id)

    async def generate(
        self,
        prompt: str,
        context: list[str],
        system_prompt: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 2048,
    ) -> LLMResponse:
        """
        Generate with circuit breaker, retry, and cost tracking.

        Raises:
            CircuitOpenError: if circuit breaker is OPEN
            BudgetExceededError: if team has exhausted budget
            RuntimeError: if all retries exhausted
        """
        # Budget gate
        if not self._cost_tracker.is_within_budget(self._team_id):
            raise BudgetExceededError(
                f"Team {self._team_id} has exceeded LLM budget. Usage: {self._cost_tracker.get_usage(self._team_id)}"
            )

        # Circuit breaker gate
        if not self._circuit.is_call_allowed:
            raise CircuitOpenError(f"Circuit breaker is OPEN. Recovery in {self._circuit._config.recovery_timeout}s")

        # Retry loop
        last_error: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            try:
                start = time.monotonic()
                response = await self._llm.generate(
                    prompt=prompt,
                    context=context,
                    system_prompt=system_prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                latency = (time.monotonic() - start) * 1000

                # Record success
                self._circuit.record_success()
                self._latency.record(latency)

                # Track cost
                cost = self._cost_tracker.track(
                    team_id=self._team_id,
                    model=response.model,
                    input_tokens=response.input_tokens,
                    output_tokens=response.output_tokens,
                )

                logger.info(
                    "llm_call_success",
                    model=response.model,
                    latency_ms=round(latency, 1),
                    cost_usd=round(cost, 6),
                    team_id=self._team_id,
                    attempt=attempt,
                )

                return response

            except Exception as e:
                last_error = e
                self._circuit.record_failure()

                logger.warning(
                    "llm_call_failed",
                    attempt=attempt,
                    max_retries=self._max_retries,
                    error=str(e),
                    team_id=self._team_id,
                )

                if attempt < self._max_retries:
                    backoff = self._base_backoff * (2 ** (attempt - 1))
                    await asyncio.sleep(backoff)

        raise RuntimeError(f"LLM call failed after {self._max_retries} retries: {last_error}")

    async def classify_complexity(self, query: str) -> QueryComplexity:
        """Delegate to wrapped LLM."""
        return await self._llm.classify_complexity(query)

    async def generate_stream(
        self,
        prompt: str,
        context: list[str],
        system_prompt: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 2048,
    ) -> AsyncIterator[str]:
        """Streaming with circuit breaker check (no retry for streams)."""
        if not self._circuit.is_call_allowed:
            raise CircuitOpenError("Circuit breaker is OPEN")

        async for chunk in self._llm.generate_stream(prompt, context, system_prompt, temperature, max_tokens):
            yield chunk


# ── Custom Errors ───────────────────────────────────────────────────


class CircuitOpenError(Exception):
    """Raised when circuit breaker is OPEN."""

    pass


class BudgetExceededError(Exception):
    """Raised when team has exceeded LLM budget."""

    pass
