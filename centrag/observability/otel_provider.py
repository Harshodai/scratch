"""
OpenTelemetry Provider — Production-grade observability for FREE.

Stack (all open-source, self-hosted):
  ┌──────────────────────────────────────────────────────────┐
  │  FastAPI App                                             │
  │  └─ OpenTelemetry SDK (auto-instrumentation)             │
  │       ├─ Traces → OTel Collector → Tempo/Jaeger          │
  │       ├─ Metrics → OTel Collector → Prometheus            │
  │       └─ Logs → structlog → Loki                         │
  ├──────────────────────────────────────────────────────────┤
  │  Grafana (visualization + alerting)                      │
  │  └─ Datasources: Prometheus, Tempo, Loki                 │
  └──────────────────────────────────────────────────────────┘

Setup (all free):
  pip install opentelemetry-api opentelemetry-sdk \\
              opentelemetry-instrumentation-fastapi \\
              opentelemetry-exporter-otlp-proto-grpc

Environment variables:
  OTEL_SERVICE_NAME=centrag
  OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
  OTEL_RESOURCE_ATTRIBUTES=deployment.environment=production

Docker Compose for backends:
  See docker-compose.observability.yml in project root.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from centrag.observability import (
    SpanContext,
    SpanKind,
)
from centrag.utils.logger import get_logger

logger = get_logger("observability.otel")


class OTelTracer:
    """
    OpenTelemetry distributed tracing.

    FREE: Self-hosted with Jaeger or Grafana Tempo.
    Implements TracingProtocol.

    Usage:
        tracer = OTelTracer(service_name="centrag")
        async with tracer.span("embed_query", SpanKind.EMBEDDING) as ctx:
            vector = await embedder.embed_query(text)
            ctx.attributes["dimension"] = len(vector)
    """

    def __init__(
        self,
        service_name: str = "centrag",
        endpoint: str = "",
    ) -> None:
        self._service_name = service_name
        self._endpoint = endpoint
        self._tracer = None

    def _get_tracer(self):
        """Lazy-initialize OTel tracer."""
        if self._tracer is None:
            try:
                from opentelemetry import trace
                from opentelemetry.sdk.resources import Resource
                from opentelemetry.sdk.trace import TracerProvider
                from opentelemetry.sdk.trace.export import BatchSpanProcessor

                resource = Resource.create({"service.name": self._service_name})
                provider = TracerProvider(resource=resource)

                if self._endpoint:
                    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

                    exporter = OTLPSpanExporter(endpoint=self._endpoint)
                    provider.add_span_processor(BatchSpanProcessor(exporter))

                trace.set_tracer_provider(provider)
                self._tracer = trace.get_tracer(self._service_name)
                logger.info("otel_tracer_initialized", endpoint=self._endpoint or "in-process")
            except ImportError:
                logger.warning("otel_not_installed", message="pip install opentelemetry-sdk")
                self._tracer = None
        return self._tracer

    @asynccontextmanager
    async def span(
        self,
        name: str,
        kind: SpanKind,
        attributes: dict[str, Any] | None = None,
    ) -> AsyncIterator[SpanContext]:
        ctx = SpanContext(name=name, kind=kind, attributes=attributes or {})
        tracer = self._get_tracer()

        if tracer is None:
            # Fallback: no OTel installed, just yield context
            try:
                yield ctx
            finally:
                ctx.end_time = time.monotonic()
            return

        from opentelemetry import trace  # Ensure trace is in scope for Status/StatusCode

        with tracer.start_as_current_span(name) as otel_span:
            otel_span.set_attribute("span.kind", kind.value)
            if attributes:
                for k, v in attributes.items():
                    otel_span.set_attribute(k, str(v))
            try:
                yield ctx
            except Exception as e:
                ctx.status = "ERROR"
                ctx.error = str(e)
                otel_span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
                otel_span.record_exception(e)
                raise
            finally:
                ctx.end_time = time.monotonic()
                otel_span.set_attribute("duration_ms", ctx.duration_ms)
                for k, v in ctx.attributes.items():
                    otel_span.set_attribute(k, str(v))

    async def flush(self) -> None:
        try:
            from opentelemetry import trace

            provider = trace.get_tracer_provider()
            if hasattr(provider, "force_flush"):
                provider.force_flush()
        except ImportError:
            pass


class OTelMetrics:
    """
    OpenTelemetry metrics → Prometheus.

    FREE: Self-hosted with Prometheus + Grafana.
    Implements MetricsProtocol.

    Prometheus scrapes /metrics endpoint automatically.
    Key RAG metrics tracked:
      - centrag_retrieval_duration_ms (histogram)
      - centrag_cache_hit_total (counter)
      - centrag_llm_tokens_total (counter)
      - centrag_embedding_dimension (gauge)
    """

    def __init__(self, service_name: str = "centrag") -> None:
        self._meter = None
        self._service_name = service_name
        self._counters: dict[str, Any] = {}
        self._histograms: dict[str, Any] = {}
        self._gauges: dict[str, Any] = {}

    def _get_meter(self):
        if self._meter is None:
            try:
                from opentelemetry import metrics
                from opentelemetry.sdk.metrics import MeterProvider

                self._meter = metrics.get_meter(self._service_name)
                logger.info("otel_meter_initialized")
            except ImportError:
                logger.warning("otel_metrics_not_installed")
        return self._meter

    def counter(self, name: str, value: float = 1.0, tags: dict[str, str] | None = None) -> None:
        meter = self._get_meter()
        if meter is None:
            return
        if name not in self._counters:
            self._counters[name] = meter.create_counter(name)
        self._counters[name].add(value, attributes=tags or {})

    def histogram(self, name: str, value: float, tags: dict[str, str] | None = None) -> None:
        meter = self._get_meter()
        if meter is None:
            return
        if name not in self._histograms:
            self._histograms[name] = meter.create_histogram(name)
        self._histograms[name].record(value, attributes=tags or {})

    def gauge(self, name: str, value: float, tags: dict[str, str] | None = None) -> None:
        meter = self._get_meter()
        if meter is None:
            return
        if name not in self._gauges:
            # OTel uses UpDownCounter for gauges
            self._gauges[name] = meter.create_up_down_counter(name)
        # Reset and set (approximate gauge behavior)
        self._gauges[name].add(value, attributes=tags or {})
