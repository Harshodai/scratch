"""
NoOp LLM — Development/testing LLM implementation.

Returns template-based responses that include the provided context,
allowing pipeline testing without API calls.

Production replacement: BedrockLLM, OpenAILLM, or LocalLLM.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from centrag.abstractions.llm import LLMResponse, QueryComplexity
from centrag.utils.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = get_logger("implementations.llm.noop")


class NoOpLLM:
    """Deterministic Mock LLM for local development and testing.

    The WHY:
        Enterprise RAG systems are expensive and slow to test with real
        APIs. The NoOpLLM provides a "Zero-Cost" development path,
        allowing developers to test pipeline logic, UI state transitions,
        and integration flows without hitting AWS or OpenAI. It
        generates deterministic responses based on the provided
        context, ensuring that tests are repeatable and fast.

    Design Pattern:
        MOCK / STUB — Implements `LLMProtocol` but returns
        static/template content instead of calling a remote model.

    Usage:
        llm = NoOpLLM()
        # Returns a mock response summarizing the context
        resp = await llm.generate("How do I X?", ["Source 1", "Source 2"])
    """

    def __init__(
        self,
        model_name: str = "noop-llm-v1",
        default_complexity: QueryComplexity = QueryComplexity.MODERATE,
    ) -> None:
        self._model = model_name
        self._default_complexity = default_complexity

    async def generate(
        self,
        prompt: str,
        context: list[str],
        system_prompt: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 2048,
    ) -> LLMResponse:
        """
        Generate a response from prompt + context.

        Returns a structured response that incorporates the
        provided context chunks, simulating real LLM behavior.
        """
        start = time.monotonic()

        # Build a deterministic answer from context
        if context:
            context_summary = "\n".join(f"[Source {i + 1}]: {chunk[:200]}" for i, chunk in enumerate(context[:5]))
            answer = (
                f"Based on the provided sources, here is what I found:\n\n"
                f"{context_summary}\n\n"
                f"This answer was generated from {len(context)} source(s) "
                f"in response to: {prompt[:100]}"
            )
        else:
            answer = "No relevant context was provided. Please ensure documents have been uploaded and indexed."

        # Estimate token counts
        input_tokens = len(prompt.split()) + sum(len(c.split()) for c in context)
        output_tokens = len(answer.split())
        latency_ms = (time.monotonic() - start) * 1000

        logger.info(
            "noop_generate",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            context_chunks=len(context),
        )

        return LLMResponse(
            content=answer,
            model=self._model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            metadata={"provider": "noop", "temperature": temperature},
        )

    async def classify_complexity(self, query: str) -> QueryComplexity:
        """
        Classify query complexity using simple heuristics.

        A real implementation would use the LLM to classify.
        This uses word count and question word analysis.
        """
        words = query.lower().split()
        word_count = len(words)

        # Simple heuristic classification
        multi_hop_indicators = {"compare", "contrast", "relationship", "between", "versus", "vs"}
        complex_indicators = {"why", "how", "explain", "analyze", "evaluate", "synthesize"}

        if word_count > 30 or multi_hop_indicators & set(words):
            result = QueryComplexity.COMPLEX
        elif word_count < 8 and not (complex_indicators & set(words)):
            result = QueryComplexity.SIMPLE
        else:
            result = QueryComplexity.MODERATE

        logger.debug("noop_classify", query_preview=query[:50], complexity=result.value)
        return result

    async def generate_stream(
        self,
        prompt: str,
        context: list[str],
        system_prompt: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 2048,
    ) -> AsyncIterator[str]:
        """
        Streaming generation — yields response word by word.

        Simulates streaming for pipeline testing.
        """
        response = await self.generate(
            prompt=prompt,
            context=context,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        # Yield word by word to simulate streaming
        for word in response.content.split():
            yield word + " "
