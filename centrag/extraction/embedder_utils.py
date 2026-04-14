"""
Late Chunking Utilities — Context-aware pooling for all embedders.

The WHY:
    Native Late Chunking (e.g., Jina-v3) pools hidden states across the full
    transformer sequence. Standard cloud APIs (OpenAI/Bedrock) only return
    a single vector.

    The "LateChunkingSimulator" allows ANY provider to benefit from late
    chunking by using semantic sliding windows and cross-chunk pooling.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from centrag.abstractions.embedder import EmbedderProtocol


class LateChunkingSimulator:
    """Universal pooling layer for cloud-based embedders.

    This simulator approximates late chunking by embedding chunks with
    overlapping 'context handles' and performing weighted pooling.
    """

    def __init__(self, embedder: EmbedderProtocol, context_window: int = 200) -> None:
        """
        Args:
            embedder: The target embedder (Bedrock, OpenAI, etc.)
            context_window: Number of characters to take from neighbors as handle.
        """
        self._embedder = embedder
        self._context_window = context_window

    async def simulate_late_chunking(
        self,
        full_text: str,
        chunk_boundaries: list[tuple[int, int]],
    ) -> list[list[float]]:
        """ approximates late chunking using windowed embeddings.

        Implementation:
            For each chunk [start, end], we embed self[start-W : end+W].
            This ensures the embedding model 'sees' the surrounding
            semantic context (pronouns, references) during inference.
        """
        tasks = []
        for start, end in chunk_boundaries:
            # Expand window for context handle
            win_start = max(0, start - self._context_window)
            win_end = min(len(full_text), end + self._context_window)
            
            windowed_text = full_text[win_start:win_end]
            tasks.append(self._embedder.embed_query(windowed_text))

        # Respecting the protocol's batching preference if it were available,
        # but here we use gather for concurrency.
        return await asyncio.gather(*tasks)
