"""
LLM abstraction — handles text generation with context.

SOLID: Open/Closed — add new LLM providers without modifying existing code.

Design Pattern: STRATEGY PATTERN
    - BedrockLLM, OpenAILLM, LocalLLM implement this
    - The retrieval engine calls generate() without knowing which LLM is behind it

RAG Advancement: ADAPTIVE RETRIEVAL (2025-2026)
    - classify_complexity() lets the system route simple queries to cheaper models
    - and complex queries to frontier models (Claude 3.5 Sonnet vs Haiku)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator, Protocol, runtime_checkable


class QueryComplexity(str, Enum):
    """Used by Adaptive RAG to route queries to appropriate models."""

    SIMPLE = "simple"      # Direct factual — use fast/cheap model or cache
    MODERATE = "moderate"  # Needs retrieval — standard RAG
    COMPLEX = "complex"    # Multi-hop reasoning — frontier model + iterative


@dataclass(frozen=True)
class LLMResponse:
    """Immutable LLM response with cost tracking for observability."""

    content: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: float
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def estimated_cost_usd(self) -> float:
        """Rough cost estimate for Langfuse tracking."""
        # Bedrock Claude 3.5 Sonnet pricing (approximate)
        return (self.input_tokens * 3.0 + self.output_tokens * 15.0) / 1_000_000


@runtime_checkable
class LLMProtocol(Protocol):
    """Contract for all LLM providers."""

    async def generate(
        self,
        prompt: str,
        context: list[str],
        system_prompt: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 2048,
    ) -> LLMResponse:
        """Generate a response given a prompt and retrieved context chunks."""
        ...

    async def classify_complexity(self, query: str) -> QueryComplexity:
        """
        ADAPTIVE RAG (2025): Classify query complexity to route appropriately.

        Simple queries → skip retrieval or use cache
        Moderate → standard RAG pipeline
        Complex → multi-hop retrieval + frontier model
        """
        ...

    def generate_stream(
        self,
        prompt: str,
        context: list[str],
        system_prompt: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 2048,
    ) -> AsyncIterator[str]:
        """
        Stream response tokens for reduced time-to-first-byte.

        Yields chunks of text as they're generated.
        The engine checks hasattr(llm, 'generate_stream') before calling,
        so implementations may omit this for batch-only providers.
        """
        ...

