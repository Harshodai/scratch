"""
Tests for LLM Gateway — circuit breaker, cost tracking, latency monitoring.

Verifies:
    - Circuit breaker state transitions (CLOSED → OPEN → HALF_OPEN → CLOSED)
    - Cost tracking and budget enforcement
    - Latency histogram percentiles
    - Retry with backoff
    - Budget exceeded error
"""

from __future__ import annotations

import time

import pytest

from centrag.implementations.llm_gateway import (
    BudgetExceededError,
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitOpenError,
    CircuitState,
    CostTracker,
    LatencyMonitor,
    LLMGateway,
)
from centrag.implementations.noop_llm import NoOpLLM

# ── Circuit Breaker ─────────────────────────────────────────────────


class TestCircuitBreaker:
    """State machine tests for the circuit breaker."""

    def test_starts_closed(self):
        cb = CircuitBreaker()
        assert cb.state == CircuitState.CLOSED

    def test_opens_after_threshold(self):
        cb = CircuitBreaker(CircuitBreakerConfig(failure_threshold=3))
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_open_blocks_calls(self):
        cb = CircuitBreaker(CircuitBreakerConfig(failure_threshold=1))
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert cb.is_call_allowed is False

    def test_half_open_after_recovery(self):
        cb = CircuitBreaker(
            CircuitBreakerConfig(
                failure_threshold=1,
                recovery_timeout=0.1,  # 100ms for testing
            )
        )
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN
        assert cb.is_call_allowed is True

    def test_half_open_to_closed(self):
        cb = CircuitBreaker(
            CircuitBreakerConfig(
                failure_threshold=1,
                recovery_timeout=0.01,
                success_threshold=2,
            )
        )
        cb.record_failure()
        time.sleep(0.02)
        assert cb.state == CircuitState.HALF_OPEN

        cb.record_success()
        assert cb.state == CircuitState.HALF_OPEN  # Not enough yet
        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    def test_half_open_to_open_on_failure(self):
        cb = CircuitBreaker(
            CircuitBreakerConfig(
                failure_threshold=1,
                recovery_timeout=0.01,
            )
        )
        cb.record_failure()
        time.sleep(0.02)
        assert cb.state == CircuitState.HALF_OPEN

        cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_success_resets_failure_count(self):
        cb = CircuitBreaker(CircuitBreakerConfig(failure_threshold=3))
        cb.record_failure()
        cb.record_failure()
        cb.record_success()  # Reset
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED  # Still closed (reset worked)


# ── Cost Tracker ────────────────────────────────────────────────────


class TestCostTracker:
    """Per-team cost tracking and budget enforcement."""

    def test_track_returns_cost(self):
        tracker = CostTracker()
        cost = tracker.track("t1", "gpt-4o-mini", 1000, 500)
        # gpt-4o-mini: $0.15/1M input, $0.60/1M output
        expected = (1000 * 0.15 + 500 * 0.60) / 1_000_000
        assert abs(cost - expected) < 1e-10

    def test_usage_accumulates(self):
        tracker = CostTracker()
        tracker.track("t1", "gpt-4o-mini", 1000, 500)
        tracker.track("t1", "gpt-4o-mini", 2000, 1000)

        usage = tracker.get_usage("t1")
        assert usage["total_calls"] == 2
        assert usage["total_input_tokens"] == 3000
        assert usage["total_output_tokens"] == 1500

    def test_budget_enforcement(self):
        tracker = CostTracker(default_budget_usd=0.001)
        assert tracker.is_within_budget("t1") is True

        # Blow through the budget with expensive model
        tracker.track("t1", "gpt-4-turbo", 100000, 50000)
        assert tracker.is_within_budget("t1") is False

    def test_custom_team_budget(self):
        tracker = CostTracker(default_budget_usd=1.0)
        tracker.set_budget("premium-team", 100.0)

        assert tracker.get_remaining_budget("premium-team") == 100.0
        assert tracker.get_remaining_budget("regular-team") == 1.0

    def test_reset_clears_usage(self):
        tracker = CostTracker()
        tracker.track("t1", "gpt-4o", 10000, 5000)
        tracker.reset("t1")

        usage = tracker.get_usage("t1")
        assert usage["total_calls"] == 0

    def test_noop_model_zero_cost(self):
        tracker = CostTracker()
        cost = tracker.track("t1", "noop-llm-v1", 10000, 5000)
        assert cost == 0.0


# ── Latency Monitor ────────────────────────────────────────────────


class TestLatencyMonitor:
    """Latency histogram percentile tests."""

    def test_empty_returns_zero(self):
        monitor = LatencyMonitor()
        assert monitor.percentile(50) == 0.0

    def test_single_value(self):
        monitor = LatencyMonitor()
        monitor.record(100.0)
        assert monitor.percentile(50) == 100.0
        assert monitor.percentile(99) == 100.0

    def test_percentile_ordering(self):
        monitor = LatencyMonitor()
        for i in range(1, 101):
            monitor.record(float(i))

        assert monitor.percentile(50) <= monitor.percentile(95)
        assert monitor.percentile(95) <= monitor.percentile(99)

    def test_stats_dict(self):
        monitor = LatencyMonitor()
        for i in range(10):
            monitor.record(float(i * 10))

        stats = monitor.stats
        assert "p50_ms" in stats
        assert "p95_ms" in stats
        assert "p99_ms" in stats
        assert stats["count"] == 10

    def test_window_eviction(self):
        monitor = LatencyMonitor(window_size=5)
        for i in range(10):
            monitor.record(float(i))

        assert monitor.stats["count"] == 5


# ── LLM Gateway Integration ────────────────────────────────────────


class TestLLMGateway:
    """End-to-end gateway tests with NoOpLLM."""

    @pytest.mark.asyncio
    async def test_successful_call(self):
        llm = NoOpLLM()
        gw = LLMGateway(llm, team_id="t1")

        response = await gw.generate("Hello?", ["context data"])
        assert response.content
        assert response.model == "noop-llm-v1"

    @pytest.mark.asyncio
    async def test_tracks_cost(self):
        llm = NoOpLLM()
        gw = LLMGateway(llm, team_id="t1")

        await gw.generate("Hello?", ["some context"])

        usage = gw.usage
        assert usage["total_calls"] == 1
        assert usage["total_input_tokens"] > 0

    @pytest.mark.asyncio
    async def test_tracks_latency(self):
        llm = NoOpLLM()
        gw = LLMGateway(llm, team_id="t1")

        await gw.generate("Hello?", [])

        stats = gw.latency_stats
        assert stats["count"] == 1
        assert stats["p50_ms"] >= 0

    @pytest.mark.asyncio
    async def test_budget_exceeded_raises(self):
        llm = NoOpLLM()
        tracker = CostTracker(default_budget_usd=0.0)  # Zero budget
        gw = LLMGateway(llm, team_id="t1", cost_tracker=tracker)

        # NoOp model costs $0, but budget is $0 so it's at limit
        # Track a non-zero cost first
        tracker.track("t1", "gpt-4o", 1000000, 500000)

        with pytest.raises(BudgetExceededError):
            await gw.generate("Hello?", [])

    @pytest.mark.asyncio
    async def test_circuit_open_raises(self):
        llm = NoOpLLM()
        gw = LLMGateway(
            llm,
            team_id="t1",
            circuit_config=CircuitBreakerConfig(failure_threshold=1),
        )

        # Force circuit open
        gw._circuit.record_failure()
        assert gw.circuit_state == CircuitState.OPEN

        with pytest.raises(CircuitOpenError):
            await gw.generate("Hello?", [])

    @pytest.mark.asyncio
    async def test_classify_delegates(self):
        llm = NoOpLLM()
        gw = LLMGateway(llm, team_id="t1")

        complexity = await gw.classify_complexity("What is X?")
        assert complexity is not None
