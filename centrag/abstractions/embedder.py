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
    """Contract for all embedding providers in the CentRAG ecosystem.

    The WHY:
        This protocol implements the STRATEGY PATTERN (Dense Retrieval).
        It allows the system to switch between AWS Titan V2, OpenAI
        text-embedding-3, or local models without modifying the
        RetrievalEngine logic.

    Design Goal:
        Provide a unified interface for transforming unstructured text
        into semantic vector space for multi-tenant similarity search.
    """

    @property
    def dimension(self) -> int:
        """Embedding vector dimension.

        The WHY:
            Downstream Vector stores (Qdrant/Pinecone) must be initialized
            with the correct fixed dimension at index creation time.
        """
        ...

    async def embed_query(self, text: str) -> list[float]:
        """Embed a single query string for semantic search.

        The WHY:
            Query embeddings are often shorter and may require different
            model-specific prefixes (e.g., 'search_query: ') compared to
            document embeddings.

        Args:
            text: The user's search query.

        Returns:
            list[float]: A dense vector representing the semantics of the query.
        """
        ...

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts in batch for ingestion.

        The WHY:
            Batching reduces API round-trips and maximizes GPU utilization
            during large-scale document processing.

        Args:
            texts: A list of text chunks to be embedded.

        Returns:
            list[list[float]]: A list of semantic dense vectors.
        """
        ...

    async def embed_with_late_chunking(
        self,
        full_text: str,
        chunk_boundaries: list[tuple[int, int]],
    ) -> list[list[float]]:
        """ADVANCED (2025): Late chunking — embed full doc, then pool per chunk.

        The WHY:
            Standard RAG loses context between chunks (e.g., a pronoun in chunk 2
            referring to a noun in chunk 1). Late chunking passes the full
            document through the model first, then averages tokens within
            each chunk boundary, preserving cross-chunk semantics.

        Args:
            full_text: The complete, un-chunked document text.
            chunk_boundaries: List of (start_char, end_char) for each segment.

        Returns:
            list[list[float]]: Context-aware embeddings for every chunk.

        Usage:
            >>> chunks = [ (0, 100), (101, 250) ]
            >>> vectors = await embedder.embed_with_late_chunking(text, chunks)
        """
        ...


@runtime_checkable
class SparseEmbedderProtocol(Protocol):
    """Contract for sparse embedding providers (e.g., BM25, SPLADE).

    The WHY:
        Semantic search (Dense) is great for concepts, but Keyword search
        (Sparse) is essential for exact terms, part numbers, and acronyms.
        CentRAG uses both in a "Hybrid" pipeline for maximum recall.

    Design Goal:
        Provide a mapping of token importance rather than a dense vector.
    """

    async def embed_sparse(self, text: str) -> dict[int, float]:
        """Embed a string into a sparse vector mapping.

        Args:
            text: Input text for keyword-based importance analysis.

        Returns:
            dict[int, float]: A map where keys are token IDs and values are weights.
        """
        ...
