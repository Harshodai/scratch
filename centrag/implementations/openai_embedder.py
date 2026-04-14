"""
OpenAI Embedder — Production embedding via OpenAI text-embedding-3-small/large.

Models:
  - text-embedding-3-small: 1536 dims, $0.02/1M tokens (best value)
  - text-embedding-3-large: 3072 dims, $0.13/1M tokens (highest quality)
  - text-embedding-ada-002: 1536 dims, legacy

Design Pattern: STRATEGY (swappable via EmbedderProtocol)
SOLID: Single Responsibility — only handles embedding.
SOLID: Open/Closed — add new OpenAI models without modifying this class.

Credentials: Set OPENAI_API_KEY environment variable or pass directly.
  - The openai SDK reads OPENAI_API_KEY automatically.
  - For Azure OpenAI, set OPENAI_API_BASE and OPENAI_API_TYPE.

Required: pip install openai
"""

from __future__ import annotations

from typing import Any
from centrag.extraction.embedder_utils import LateChunkingSimulator

from centrag.utils.logger import get_logger

logger = get_logger("implementations.embedder.openai")


class OpenAIEmbedder:
    """Industry-standard embedding generation using OpenAI's text-embedding-3 models.

    The WHY:
        OpenAI provides high-density, standardized embeddings that are
        compatible with almost every vector database. This implementation
        focuses on high-throughput batching, allowing us to embed
        thousands of document chunks in a single API call. This is
        essential for the initial "Cold Indexing" of large document
        repositories where speed is the primary bottleneck.

    Design Pattern:
        STRATEGY — Implements `EmbedderProtocol`. Its optimized
        input-list processing makes it the ideal choice for heavy
        ingestion jobs.

    Usage:
        embedder = OpenAIEmbedder(model="text-embedding-3-small")
        # Optimized for batch ingestion
        vectors = await embedder.embed_documents(["doc1", "doc2", ...])
    """

    def __init__(
        self,
        model: str = "text-embedding-3-small",
        dimension: int = 1536,
        # Credentials — leave empty to use environment variables
        api_key: str = "",
        base_url: str = "",
        organization: str = "",
        # Performance tuning
        max_retries: int = 3,
        timeout: float = 30.0,
    ) -> None:
        self._model = model
        self._dimension = dimension
        self._api_key = api_key
        self._base_url = base_url
        self._organization = organization
        self._max_retries = max_retries
        self._timeout = timeout

        # Lazy-initialized async client (Pattern 3: Pervasive Lazy Loading)
        self._client = None

    def _get_client(self):
        """Lazy-init the AsyncOpenAI client."""
        if self._client is None:
            from openai import AsyncOpenAI

            kwargs: dict[str, Any] = {
                "max_retries": self._max_retries,
                "timeout": self._timeout,
            }
            # Only pass non-empty values (let SDK read from env otherwise)
            if self._api_key:
                kwargs["api_key"] = self._api_key
            if self._base_url:
                kwargs["base_url"] = self._base_url
            if self._organization:
                kwargs["organization"] = self._organization

            self._client = AsyncOpenAI(**kwargs)
            logger.info(
                "openai_client_initialized",
                model=self._model,
                dimension=self._dimension,
                base_url=self._base_url or "https://api.openai.com/v1",
            )
        return self._client

    async def embed_query(self, text: str) -> list[float]:
        """
        Embed a single query string.

        Uses the OpenAI embeddings.create API with the async client.
        """
        client = self._get_client()

        response = await client.embeddings.create(
            input=text,
            model=self._model,
            dimensions=self._dimension,
        )

        embedding = response.data[0].embedding
        usage = response.usage

        logger.debug(
            "openai_embed_query",
            input_tokens=usage.total_tokens if usage else 0,
            dimension=len(embedding),
            text_preview=text[:50],
        )

        return embedding

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """
        Embed multiple documents in a single API call.

        OpenAI supports multi-input embedding — passing a list of
        strings returns all embeddings in one request. This is
        significantly faster than sequential singleton calls.

        The implementation chunks input into segments of 2000 to
        remain within OpenAI API limits and processes these segments
        sequentially.
        """
        if not texts:
            return []

        client = self._get_client()

        # OpenAI embeddings.create accepts a list of strings natively
        # Chunk into batches of 2000 to stay within limits
        batch_size = 2000
        all_embeddings: list[list[float]] = []

        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]

            response = await client.embeddings.create(
                input=batch,
                model=self._model,
                dimensions=self._dimension,
            )

            # Response.data is sorted by index, but we sort explicitly
            sorted_data = sorted(response.data, key=lambda x: x.index)
            batch_embeddings = [item.embedding for item in sorted_data]
            all_embeddings.extend(batch_embeddings)

            logger.debug(
                "openai_embed_batch",
                batch_index=i // batch_size,
                batch_size=len(batch),
                total_tokens=response.usage.total_tokens if response.usage else 0,
            )

        return all_embeddings

    async def embed_with_late_chunking(
        self,
        full_text: str,
        chunk_boundaries: list[tuple[int, int]],
    ) -> list[list[float]]:
        """
        Late Chunking: embed chunks with full-document context.

        Uses the LateChunkingSimulator to approximate contextual
        pooling for OpenAI models by using semantic sliding windows.
        """
        simulator = LateChunkingSimulator(self)
        return await simulator.simulate_late_chunking(full_text, chunk_boundaries)

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def model(self) -> str:
        return self._model
