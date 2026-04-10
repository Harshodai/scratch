"""
BM25 Sparse Embedder Implementation

SOLID: Single Responsibility — Tokenizes and calculates token frequencies for sparse vectors.
SOLID: Liskov Substitution — Implements SparseEmbedderProtocol.

This embedder uses a lightweight, local tokenizer and frequency map to generate sparse vectors.
In a true production environment with BM25, IDF scores are needed across the corpus. Since
CentRAG calculates BM25 scores dynamically at index/search, this generates term frequencies (TF)
that Qdrant's BM25 feature expects.
"""

import collections
import hashlib
import re
from typing import Dict

from centrag.abstractions.embedder import SparseEmbedderProtocol


class BM25SparseEmbedder(SparseEmbedderProtocol):
    """
    Lightweight sparse embedder generating (token_hash -> term_frequency) vectors.
    Designed for native Qdrant BM25 sparse vector ingest.
    """

    def __init__(self, stop_words: set[str] | None = None) -> None:
        """
        Args:
            stop_words: Optional set of words to ignore.
        """
        self.stop_words = stop_words or {
            "a", "an", "and", "are", "as", "at", "be", "but", "by",
            "for", "if", "in", "into", "is", "it", "no", "not", "of",
            "on", "or", "such", "that", "the", "their", "then", "there",
            "these", "they", "this", "to", "was", "will", "with"
        }

    async def embed_sparse(self, text: str) -> dict[int, float]:
        """
        Tokenize the text, remove stop words, and calculate term frequencies.
        Hashes tokens to integer indices to map directly to a sparse vector space.
        """
        # Prevent ReDoS or OOM by enforcing a maximum tokenizable text length.
        # Fall back to truncation if exceeding typical page size (e.g. 100k chars)
        max_length = 100_000
        safe_text = text[:max_length].lower()
        
        # Lowercase and extract alphanumeric sequences
        tokens = re.findall(r'\b\w+\b', safe_text)
        
        # Filter stop words
        filtered_tokens = [t for t in tokens if t not in self.stop_words and not t.isnumeric()]
        
        # Count frequencies
        frequencies = collections.Counter(filtered_tokens)
        
        # Map tokens to integer hashes (consistent across runs for the same vocab)
        # In production NLP, this would ideally be an exact vocabulary mapping. 
        # Using built-in hash() is NOT deterministic across python processes.
        # We use a stable string hashing mechanism to ensure cross-process consistency.
        sparse_vector: Dict[int, float] = {}
        for token, count in frequencies.items():
            # A simple deterministic hash modulo a large prime space to prevent excessive collisions
            token_id = self._deterministic_hash(token)
            sparse_vector[token_id] = float(count)
            
        return sparse_vector

    @staticmethod
    def _deterministic_hash(token: str) -> int:
        """Stable hashing function using hashlib.md5 to avoid python's hash() randomization and pure-python bottlenecks."""
        hashed_bytes = hashlib.md5(token.encode('utf-8')).digest()
        # Convert first 8 bytes of hash into an integer, bounded to avoid excessive sparsity ranges.
        integer_val = int.from_bytes(hashed_bytes[:8], byteorder='big')
        return integer_val % (10**9 + 7)
