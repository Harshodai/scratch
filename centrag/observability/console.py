"""
Console Observer — Zero-dependency observability for development.

FREE: No external services needed. Logs everything to structlog.

Use as a starting point, then swap to OpenTelemetry or Langfuse
in production without changing any calling code (Strategy pattern).
"""

from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from centrag.observability import (
    SpanContext,
    SpanKind,
)
from centrag.utils.logger import get_logger

logger = get_logger("observability.console")


class ConsoleTracer:
    """
    Logs all spans to structlog (console/JSON).

    FREE — zero external dependencies.
    Implements TracingProtocol.
    """

    @asynccontextmanager
    async def span(
        self,
        name: str,
        kind: SpanKind,
        attributes: dict[str, Any] | None = None,
    ) -> AsyncIterator[SpanContext]:
        ctx = SpanContext(name=name, kind=kind, attributes=attributes or {})
        logger.info("span_start", span=name, kind=kind.value)

        try:
            yield ctx
        except Exception as e:
            ctx.status = "ERROR"
            ctx.error = str(e)
            raise
        finally:
            ctx.end_time = time.monotonic()
            logger.info(
                "span_end",
                span=name,
                kind=kind.value,
                duration_ms=round(ctx.duration_ms, 2),
                status=ctx.status,
                error=ctx.error,
                attributes=ctx.attributes,
            )

    async def flush(self) -> None:
        pass  # structlog flushes immediately


class ConsoleMetrics:
    """
    In-memory metrics with periodic log dumping.

    FREE — zero external dependencies.
    Implements MetricsProtocol.

    For production, swap to PrometheusMetrics or OTelMetrics.
    """

    def __init__(self) -> None:
        self._counters: dict[str, float] = defaultdict(float)
        self._histograms: dict[str, list[float]] = defaultdict(list)
        self._gauges: dict[str, float] = {}

    def counter(self, name: str, value: float = 1.0, tags: dict[str, str] | None = None) -> None:
        key = f"{name}:{_tags_key(tags)}" if tags else name
        self._counters[key] += value

    def histogram(self, name: str, value: float, tags: dict[str, str] | None = None) -> None:
        key = f"{name}:{_tags_key(tags)}" if tags else name
        self._histograms[key].append(value)

    def gauge(self, name: str, value: float, tags: dict[str, str] | None = None) -> None:
        key = f"{name}:{_tags_key(tags)}" if tags else name
        self._gauges[key] = value

    def dump(self) -> dict[str, Any]:
        """Dump current metrics state (for /metrics endpoint or logging)."""
        result = {
            "counters": dict(self._counters),
            "gauges": dict(self._gauges),
            "histograms": {
                k: {
                    "count": len(v),
                    "min": min(v) if v else 0,
                    "max": max(v) if v else 0,
                    "avg": sum(v) / len(v) if v else 0,
                    "p99": sorted(v)[int(len(v) * 0.99)] if v else 0,
                }
                for k, v in self._histograms.items()
            },
        }
        logger.info("metrics_dump", **result)
        return result


class ConsoleCostTracker:
    """
    In-memory cost tracking for development.

    FREE — no database required. Logs cost events to structlog.
    Implements CostTrackingProtocol.

    Production replacement: LangfuseCostTracker (self-hosted, also free).
    """

    # Approximate pricing per 1M tokens (as of 2025)
    PRICING: dict[str, dict[str, float]] = {
        "amazon.titan-embed-text-v2:0": {"input": 0.02},
        "text-embedding-3-small": {"input": 0.02},
        "text-embedding-3-large": {"input": 0.13},
        "anthropic.claude-3-5-sonnet-20241022-v2:0": {"input": 3.0, "output": 15.0},
        "gpt-4o": {"input": 2.5, "output": 10.0},
        "gpt-4o-mini": {"input": 0.15, "output": 0.6},
        "noop-llm-v1": {"input": 0.0, "output": 0.0},
    }

    def __init__(self) -> None:
        self._usage: dict[str, dict[str, float]] = defaultdict(
            lambda: {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "calls": 0}
        )

    async def track_generation(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        latency_ms: float,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        pricing = self.PRICING.get(model, {"input": 0.0, "output": 0.0})
        cost = (input_tokens * pricing.get("input", 0) + output_tokens * pricing.get("output", 0)) / 1_000_000

        self._usage[model]["input_tokens"] += input_tokens
        self._usage[model]["output_tokens"] += output_tokens
        self._usage[model]["cost_usd"] += cost
        self._usage[model]["calls"] += 1

        logger.info(
            "cost_tracked_generation",
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=round(cost, 6),
            latency_ms=round(latency_ms, 2),
        )

    async def track_embedding(
        self,
        model: str,
        input_tokens: int,
        dimension: int,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        pricing = self.PRICING.get(model, {"input": 0.0})
        cost = input_tokens * pricing.get("input", 0) / 1_000_000

        self._usage[model]["input_tokens"] += input_tokens
        self._usage[model]["cost_usd"] += cost
        self._usage[model]["calls"] += 1

        logger.debug(
            "cost_tracked_embedding",
            model=model,
            input_tokens=input_tokens,
            cost_usd=round(cost, 8),
        )

    async def get_usage_summary(
        self,
        team_id: str,
        period: str = "day",
    ) -> dict[str, Any]:
        """Return current session usage (in-memory only)."""
        total_cost = sum(u["cost_usd"] for u in self._usage.values())
        return {
            "team_id": team_id,
            "period": period,
            "total_cost_usd": round(total_cost, 6),
            "models": dict(self._usage),
        }


def _tags_key(tags: dict[str, str] | None) -> str:
    if not tags:
        return ""
    return ",".join(f"{k}={v}" for k, v in sorted(tags.items()))
