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
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


class QueryComplexity(StrEnum):
    """Used by Adaptive RAG to route queries to appropriate models.

    The WHY:
        In industrial RAG, latency and cost are as important as accuracy.
        Adaptive RAG (Classify-then-Route) ensures we don't use a $15/1M token
        model for a question that a $0.15/1M token model can answer.

    Usage:
        >>> complexity = llm.classify_complexity("What is the capital of France?")
        >>> if complexity == QueryComplexity.SIMPLE:
        >>>     # use cheap model
    """

    SIMPLE = "simple"  # Direct factual — use fast/cheap model or cache
    MODERATE = "moderate"  # Needs retrieval — standard RAG
    COMPLEX = "complex"  # Multi-hop reasoning — frontier model + iterative


@dataclass(frozen=True)
class LLMResponse:
    """Immutable LLM response with cost tracking for observability.

    The WHY:
        Production RAG must be observable. By returning structured metadata
        with every generation, we can feed downstream systems like Langfuse
        or CloudWatch without external instrumentation.

    Attributes:
        content: The generated text response.
        model: Identification string of the model used (e.g., 'claude-3-5-sonnet').
        input_tokens: Number of tokens sent in the prompt + context.
        output_tokens: Number of tokens generated.
        latency_ms: Time taken for the full generation in milliseconds.
        metadata: Provider-specific flags like finish_reason or logprobs.
    """

    content: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: float
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def estimated_cost_usd(self) -> float:
        """Rough cost estimate for Langfuse tracking.

        The WHY:
            Enables real-time budget gating and team-based cost allocation
            at the middleware layer rather than waiting for monthly bills.
        """
        # Bedrock Claude 3.5 Sonnet pricing (approximate)
        return (self.input_tokens * 3.0 + self.output_tokens * 15.0) / 1_000_000


@runtime_checkable
class LLMProtocol(Protocol):
    """Contract for all LLM providers in the CentRAG ecosystem.

    The WHY:
        This protocol implements the STRATEGY PATTERN. It allows the core
        RetrievalEngine to operate without knowing whether it is talking to
        AWS Bedrock, OpenAI, or a local Llama-3 instance.

    Design Goal:
        Provide a unified interface for both batch generation and
        Adaptive RAG complexity classification.
    """

    async def generate(
        self,
        prompt: str,
        context: list[str],
        system_prompt: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 2048,
    ) -> LLMResponse:
        """Generate a response given a prompt and retrieved context chunks.

        Args:
            prompt: The user query or refined instruction.
            context: A list of text strings retrieved from the vector store.
            system_prompt: Optional instructions for persona or grounding rules.
            temperature: Sampling temperature (0.0 for deterministic).
            max_tokens: Limit on the output size.

        Returns:
            LLMResponse: A structured object containing text and observability data.
        """
        ...

    async def classify_complexity(self, query: str) -> QueryComplexity:
        """Classify query complexity to route appropriately (Adaptive RAG).

        Args:
            query: The raw user input.

        Returns:
            QueryComplexity: The detected level (SIMPLE, MODERATE, COMPLEX).
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
        """Stream response tokens for reduced time-to-first-byte.

        Args:
            prompt: User query.
            context: Retrieved facts.
            system_prompt: Model steering instructions.
            temperature: Sampling variance.
            max_tokens: Maximum output length.

        Returns:
            AsyncIterator[str]: A stream of token strings.
        """
        ...
