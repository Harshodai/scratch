"""
Guardrails Package — Composable, production-grade guardrails for CentRAG.

This package replaces the monolithic centrag/guardrails.py with a properly
composable Chain of Responsibility pattern.

Backward Compatibility:
    The original guardrails.py still exists at centrag/guardrails.py for
    any code that imports from it directly. This package provides the
    new composable API.

Usage:
    from centrag.guardrails.engine import GuardrailEngine, GuardrailsConfig

    config = GuardrailsConfig(
        enable_prompt_injection_detection=True,
        enable_output_pii_redaction=True,
        min_confidence_threshold=0.3,
    )
    guardrails = GuardrailEngine(config)

    # Inject into RetrievalEngine
    engine = RetrievalEngine(
        ...,
        input_rails=guardrails.input_rails,
        output_rails=guardrails.output_rails,
    )
"""

from centrag.guardrails.cost_tracker import BUDGET_LIMITS, InMemoryCostTracker, TokenUsage
from centrag.guardrails.engine import GuardrailEngine, GuardrailsConfig
from centrag.guardrails.pii import PII_PATTERNS, detect_pii, redact_pii

__all__ = [
    "GuardrailEngine",
    "GuardrailsConfig",
    "PII_PATTERNS",
    "redact_pii",
    "detect_pii",
    "InMemoryCostTracker",
    "TokenUsage",
    "BUDGET_LIMITS",
]
