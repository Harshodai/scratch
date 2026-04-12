"""
NoOp Embedder — Development/testing implementation.

Returns deterministic random vectors for any input text.
Useful for testing the pipeline end-to-end without requiring
AWS Bedrock credentials or a local model.

Production replacement: BedrockEmbedder, OpenAIEmbedder, or LocalEmbedder.
"""

from __future__ import annotations

import hashlib
import random

from centrag.utils.logger import get_logger

logger = get_logger("implementations.embedder.noop")

NOOP_DIMENSION = 1024  # Match Titan Embed v2 default


class NoOpEmbedder:
    """
    Deterministic fake embedder for development.

    Generates reproducible vectors based on text hash — same text
    always produces the same vector, enabling consistent test results.

    Implements EmbedderProtocol.
    """

    def __init__(self, dimension: int = NOOP_DIMENSION) -> None:
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    def _text_to_vector(self, text: str) -> list[float]:
        """Deterministic: same text → same vector."""
        seed = int(hashlib.sha256(text.encode()).hexdigest(), 16) % (2**32)
        rng = random.Random(seed)
        vec = [rng.gauss(0, 1) for _ in range(self._dimension)]
        # Normalize to unit length
        norm = sum(v * v for v in vec) ** 0.5
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec

    async def embed_query(self, text: str) -> list[float]:
        """Embed a single query string."""
        logger.debug("noop_embed_query", text_preview=text[:50])
        return self._text_to_vector(text)

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts in batch."""
        logger.debug("noop_embed_documents", count=len(texts))
        return [self._text_to_vector(t) for t in texts]

    async def embed_with_late_chunking(
        self,
        full_text: str,
        chunk_boundaries: list[tuple[int, int]],
    ) -> list[list[float]]:
        """
        Late chunking stub — embeds each chunk independently.

        A real implementation would embed the full document first,
        then pool token embeddings per boundary.
        """
        logger.debug(
            "noop_late_chunking",
            text_len=len(full_text),
            chunk_count=len(chunk_boundaries),
        )
        chunks = [full_text[start:end] for start, end in chunk_boundaries]
        return [self._text_to_vector(c) for c in chunks]
