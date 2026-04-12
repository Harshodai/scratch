"""
AWS Bedrock LLM — Production generation via Anthropic Claude 3.5 Sonnet on Bedrock.

Model: anthropic.claude-3-5-sonnet-20240620-v1:0
  - Context Window: 200k tokens
  - Max Output: 4,096 tokens
  - Features: Native streaming, tool use, multimodality.

Design Pattern: STRATEGY (swappable via LLMProtocol)
SOLID: Single Responsibility — only handles generation.
SOLID: Open/Closed — add new Bedrock models without modifying this class.

Required IAM permission: bedrock:InvokeModel on the model ARN.
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any

from centrag.abstractions.llm import LLMResponse, QueryComplexity
from centrag.utils.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = get_logger("implementations.llm.bedrock")


class BedrockLLM:
    """Enterprise LLM implementation using Anthropic Claude models on AWS Bedrock.

    The WHY:
        Bedrock is the choice for enterprise RAG due to its VPC security,
        IAM governance, and regional data residency. This implementation
        provides a high-performance, async wrapper around the Bedrock
        runtime, ensuring that CentRAG can leverage Claude 3.5 Sonnet's
        superior reasoning while staying within the AWS ecosystem.
    """

    def __init__(
        self,
        region_name: str = "us-east-1",
        model_id: str = "anthropic.claude-3-5-sonnet-20240620-v1:0",
        # Credentials — leave empty to use boto3 default chain
        aws_access_key_id: str = "",
        aws_secret_access_key: str = "",
        aws_session_token: str = "",
    ) -> None:
        self._region = region_name
        self._model_id = model_id
        
        # Lazy-initialized boto3 client
        self._client = None
        self._credentials = {
            k: v
            for k, v in {
                "aws_access_key_id": aws_access_key_id,
                "aws_secret_access_key": aws_secret_access_key,
                "aws_session_token": aws_session_token,
            }.items()
            if v
        }

    def _get_client(self):
        """Lazy-init the bedrock-runtime client."""
        if self._client is None:
            import boto3

            kwargs: dict[str, Any] = {}
            if self._region:
                kwargs["region_name"] = self._region
            kwargs.update(self._credentials)

            self._client = boto3.client("bedrock-runtime", **kwargs)
            logger.info("bedrock_llm_initialized", region=self._region, model=self._model_id)
        return self._client

    async def generate(
        self,
        prompt: str,
        context: list[str],
        system_prompt: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 2048,
    ) -> LLMResponse:
        """Generate a response using Bedrock InvokeModel."""
        import asyncio

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            self._generate_sync,
            prompt,
            context,
            system_prompt,
            temperature,
            max_tokens,
        )

    def _generate_sync(
        self,
        prompt: str,
        context: list[str],
        system_prompt: str | None,
        temperature: float,
        max_tokens: int,
    ) -> LLMResponse:
        """Synchronous generation call to Bedrock."""
        client = self._get_client()
        start = time.monotonic()

        # Format for Claude 3 (Messages API style)
        context_str = "\n\n".join(context)
        user_content = f"Context:\n{context_str}\n\nQuestion: {prompt}"
        
        request_body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [
                {"role": "user", "content": [{"type": "text", "text": user_content}]}
            ],
        }
        if system_prompt:
            request_body["system"] = system_prompt

        response = client.invoke_model(
            modelId=self._model_id,
            body=json.dumps(request_body),
        )

        response_body = json.loads(response["body"].read())
        latency = (time.monotonic() - start) * 1000

        # Extract bits from Bedrock response
        content = ""
        for item in response_body.get("content", []):
            if item.get("type") == "text":
                content += item.get("text", "")

        return LLMResponse(
            content=content,
            model=self._model_id,
            input_tokens=response_body.get("usage", {}).get("input_tokens", 0),
            output_tokens=response_body.get("usage", {}).get("output_tokens", 0),
            latency_ms=latency,
            metadata={
                "stop_reason": response_body.get("stop_reason"),
            },
        )

    async def classify_complexity(self, query: str) -> QueryComplexity:
        """Heuristic for complexity classification (Adaptive RAG)."""
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
        """
        Stream response tokens from Bedrock.
        Uses invoke_model_with_response_stream.
        """
        import asyncio
        client = self._get_client()

        context_str = "\n\n".join(context)
        user_content = f"Context:\n{context_str}\n\nQuestion: {prompt}"
        
        request_body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [
                {"role": "user", "content": [{"type": "text", "text": user_content}]}
            ],
        }
        if system_prompt:
            request_body["system"] = system_prompt

        # For streaming via boto3 comfortably in an async context, 
        # we run the blocking iterator in the executor.
        def get_stream():
            return client.invoke_model_with_response_stream(
                modelId=self._model_id,
                body=json.dumps(request_body),
            )

        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(None, get_stream)

        for event in response.get("body"):
            chunk = json.loads(event.get("chunk").get("bytes").decode())
            if chunk.get("type") == "content_block_delta":
                yield chunk.get("delta", {}).get("text", "")
            elif chunk.get("type") == "message_stop":
                break
            # Yield control to prevent thread starvation during IO iteration
            await asyncio.sleep(0)
