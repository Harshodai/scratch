"""
AWS Bedrock Embedder — Production embedding via Amazon Titan Text Embeddings V2.

Model: amazon.titan-embed-text-v2:0
  - Dimensions: 256, 512, or 1024 (configurable)
  - Max input: 8,192 tokens
  - Normalization: built-in (server-side)

Design Pattern: STRATEGY (swappable via EmbedderProtocol)
SOLID: Single Responsibility — only handles embedding, nothing else.
SOLID: Dependency Inversion — depends on EmbedderProtocol, not concrete class.

Credentials: Uses boto3's default credential chain:
  1. Environment variables (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY)
  2. AWS config file (~/.aws/credentials)
  3. IAM role (ECS task role, EC2 instance profile, Lambda execution role)
  4. SSO token

Required IAM permission: bedrock:InvokeModel on the model ARN.
"""

from __future__ import annotations

import json
from typing import Any

from centrag.extraction.embedder_utils import LateChunkingSimulator
from centrag.utils.logger import get_logger

logger = get_logger("implementations.embedder.bedrock")


class BedrockEmbedder:
    """Production-grade embedding engine utilizing Amazon Titan Models.

    The WHY:
        Embeddings are the bridge between human language and
        mathematical similarity. This engine transforms unstructured
        text into dense vector coordinates (up to 1024 dimensions)
        using AWS Bedrock. By using the amazon.titan-embed-text-v2 model,
        we achieve state-of-the-art retrieval precision while ensuring
        low-latency inference for real-time RAG applications.

    Design Pattern:
        STRATEGY PATTERN — This is one of many possible embedder
        implementations. It is injected into the `RetrievalEngine`
        to handle the semantic transformation step.

    Usage:
        embedder = BedrockEmbedder(region_name="us-east-1")
        vector = await embedder.embed_query("Who is the CEO?")
    """

    def __init__(
        self,
        region_name: str = "",
        model_id: str = "amazon.titan-embed-text-v2:0",
        dimension: int = 1024,
        normalize: bool = True,
        # Credentials — leave empty to use boto3 default chain
        aws_access_key_id: str = "",
        aws_secret_access_key: str = "",
        aws_session_token: str = "",
    ) -> None:
        self._model_id = model_id
        self._dimension = dimension
        self._normalize = normalize
        self._region = region_name

        # Lazy-initialized boto3 client (Pattern 3: Pervasive Lazy Loading)
        self._client = None
        self._credentials = {
            k: v
            for k, v in {
                "aws_access_key_id": aws_access_key_id,
                "aws_secret_access_key": aws_secret_access_key,
                "aws_session_token": aws_session_token,
            }.items()
            if v  # Only pass non-empty credentials
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
            logger.info(
                "bedrock_client_initialized",
                region=self._region or "default",
                model=self._model_id,
                dimension=self._dimension,
            )
        return self._client

    async def embed_query(self, text: str) -> list[float]:
        """
        Embed a single query string.

        Calls Bedrock InvokeModel synchronously via boto3 (no async SDK).
        For production throughput, wrap in run_in_executor.
        """
        import asyncio

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._embed_sync, text)

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """
        Embed multiple documents in sequence.

        Titan V2 doesn't support batch embedding in a single API call,
        so we process sequentially. For production bulk indexing:
        - Use asyncio.gather with a semaphore for controlled concurrency
        - Or use the OpenAI Batch API pattern
        """
        import asyncio

        loop = asyncio.get_running_loop()

        # Sequential to respect rate limits; override with semaphore if needed
        results = []
        for text in texts:
            vec = await loop.run_in_executor(None, self._embed_sync, text)
            results.append(vec)
        return results

    async def embed_with_late_chunking(
        self,
        full_text: str,
        chunk_boundaries: list[tuple[int, int]],
    ) -> list[list[float]]:
        """
        Late Chunking: embed chunks with full-document context.

        Uses the LateChunkingSimulator to approximate contextual
        pooling for Titan models by using semantic sliding windows.
        """
        simulator = LateChunkingSimulator(self)
        return await simulator.simulate_late_chunking(full_text, chunk_boundaries)

    def _embed_sync(self, text: str) -> list[float]:
        """Synchronous embedding call to Bedrock."""
        client = self._get_client()

        request_body = json.dumps(
            {
                "inputText": text,
                "dimensions": self._dimension,
                "normalize": self._normalize,
            }
        )

        response = client.invoke_model(
            body=request_body,
            modelId=self._model_id,
            accept="application/json",
            contentType="application/json",
        )

        response_body = json.loads(response["body"].read())
        embedding = response_body["embedding"]
        input_tokens = response_body.get("inputTextTokenCount", 0)

        logger.debug(
            "bedrock_embed",
            input_tokens=input_tokens,
            dimension=len(embedding),
            text_preview=text[:50],
        )

        return embedding

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def model_id(self) -> str:
        return self._model_id
