"""
OpenAI LLM — Production generation via OpenAI GPT-4o family.

Features:
    - Async generation with standard retry logic (via SDK).
    - Streaming support for reduced time-to-first-byte.
    - Adaptive RAG: classify_complexity() routing.

Design Pattern: STRATEGY (swappable via LLMProtocol)
SOLID: Single Responsibility — only handles generation.
SOLID: Open/Closed — add new OpenAI models without modifying this class.

Required: pip install openai
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from centrag.abstractions.llm import LLMResponse, QueryComplexity
from centrag.utils.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = get_logger("implementations.llm.openai")


class OpenAILLM:
    """Enterprise-grade LLM implementation using OpenAI's GPT models.

    The WHY:
        GPT-4o and GPT-4o-mini provide the industry benchmark for
        reasoning and speed. This implementation provides a clean,
        async wrapper around the OpenAI SDK that fits the CentRAG
        `LLMProtocol`, enabling seamless switching between OpenAI
        and AWS Bedrock.
    """

    def __init__(
        self,
        model: str = "gpt-4o",
        api_key: str = "",
        base_url: str = "",
        organization: str = "",
        max_retries: int = 3,
        timeout: float = 60.0,
    ) -> None:
        self._model = model
        self._api_key = api_key
        self._base_url = base_url
        self._organization = organization
        self._max_retries = max_retries
        self._timeout = timeout

        self._client = None

    def _get_client(self):
        """Lazy-init the AsyncOpenAI client."""
        if self._client is None:
            from openai import AsyncOpenAI

            kwargs: dict[str, Any] = {
                "max_retries": self._max_retries,
                "timeout": self._timeout,
            }
            if self._api_key:
                kwargs["api_key"] = self._api_key
            if self._base_url:
                kwargs["base_url"] = self._base_url
            if self._organization:
                kwargs["organization"] = self._organization

            self._client = AsyncOpenAI(**kwargs)
            logger.info("openai_llm_initialized", model=self._model)
        return self._client

    async def generate(
        self,
        prompt: str,
        context: list[str],
        system_prompt: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 2048,
    ) -> LLMResponse:
        """Generate a response using the Chat Completions API."""
        client = self._get_client()
        start = time.monotonic()

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        context_str = "\n\n".join(context)
        user_content = f"Context:\n{context_str}\n\nQuestion: {prompt}"
        messages.append({"role": "user", "content": user_content})

        response = await client.chat.completions.create(
            model=self._model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        latency = (time.monotonic() - start) * 1000
        choice = response.choices[0]
        usage = response.usage

        return LLMResponse(
            content=choice.message.content or "",
            model=response.model,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
            latency_ms=latency,
            metadata={
                "finish_reason": choice.finish_reason,
                "system_fingerprint": response.system_fingerprint,
            },
        )

    async def classify_complexity(self, query: str) -> QueryComplexity:
        """
        Adaptive RAG classification.
        For now, uses a fast heuristic. In production, this can be a call to gpt-4o-mini.
        """
        query_len = len(query)
        if query_len < 50:
            return QueryComplexity.SIMPLE
        if query_len < 200:
            return QueryComplexity.MODERATE
        return QueryComplexity.COMPLEX

    async def generate_stream(
        self,
        prompt: str,
        context: list[str],
        system_prompt: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 2048,
    ) -> AsyncIterator[str]:
        """Stream response tokens."""
        client = self._get_client()

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        context_str = "\n\n".join(context)
        user_content = f"Context:\n{context_str}\n\nQuestion: {prompt}"
        messages.append({"role": "user", "content": user_content})

        stream = await client.chat.completions.create(
            model=self._model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        )

        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
