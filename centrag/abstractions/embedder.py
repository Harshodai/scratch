"""
Embedder abstraction — converts text to vector embeddings.

SOLID: Interface Segregation — this protocol ONLY handles embedding.
SOLID: Dependency Inversion — retrieval engine depends on this, not on Bedrock.

Design Pattern: STRATEGY PATTERN
    - BedrockEmbedder, OpenAIEmbedder, LocalEmbedder all implement this
    - Swap at startup via config, no code changes in business logic

RAG Advancement: LATE CHUNKING (2025)
    - embed_document() embeds the FULL document first, then chunks token-level.
    - This preserves cross-chunk context (pronouns, references).
    - See: Jina AI Late Chunking paper (arxiv.org/abs/2409.04701)
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class EmbedderProtocol(Protocol):
    """Contract for all embedding providers."""

    @property
    def dimension(self) -> int:
        """Embedding vector dimension (e.g., 1024 for Titan v2)."""
        ...

    async def embed_query(self, text: str) -> list[float]:
        """Embed a single query string. Optimized for search queries."""
        ...

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts in batch. Optimized for ingestion throughput."""
        ...

    async def embed_with_late_chunking(
        self,
        full_text: str,
        chunk_boundaries: list[tuple[int, int]],
    ) -> list[list[float]]:
        """
        ADVANCED (2025): Late chunking — embed full doc, then pool per chunk.

        Instead of embedding each chunk independently (losing cross-chunk context),
        this passes the full document through the model first, then mean-pools
        token embeddings within each chunk boundary.

        Args:
            full_text: The complete document text.
            chunk_boundaries: List of (start_char, end_char) for each chunk.

        Returns:
            One embedding per chunk, but each is context-aware of the full document.
        """
        ...
