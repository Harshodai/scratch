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

from centrag.abstractions.embedder import SparseEmbedderProtocol


class BM25SparseEmbedder(SparseEmbedderProtocol):
    """
    Lightweight sparse embedder generating (token_hash -> term_frequency) vectors.
    Designed for native Qdrant BM25 sparse vector ingest.
    """

    _STOP_WORDS_CACHE: dict[str, set[str]] = {}

    def __init__(self, stop_words: set[str] | None = None) -> None:
        """
        Args:
            stop_words: Optional set of words for default/fallback filtering.
        """
        self.default_stop_words = stop_words or {
            "a",
            "an",
            "and",
            "are",
            "as",
            "at",
            "be",
            "but",
            "by",
            "for",
            "if",
            "in",
            "into",
            "is",
            "it",
            "no",
            "not",
            "of",
            "on",
            "or",
            "such",
            "that",
            "the",
            "their",
            "then",
            "there",
            "these",
            "they",
            "this",
            "to",
            "was",
            "will",
            "with",
        }

    def _get_stop_words_for_text(self, text: str) -> set[str]:
        """Dynamically detect language and return appropriate stop words."""
        try:
            from langdetect import detect
            from nltk.corpus import stopwords

            lang_code = detect(text)

            # Map langdetect codes to NLTK language names (common ones)
            # langdetect: en, es, fr, de, it, pt, nl, etc.
            # nltk: english, spanish, french, german, italian, portuguese, dutch, etc.
            lang_map = {
                "en": "english",
                "es": "spanish",
                "fr": "french",
                "de": "german",
                "it": "italian",
                "pt": "portuguese",
                "nl": "dutch",
                "ru": "russian",
                "ar": "arabic",
            }

            lang_name = lang_map.get(lang_code)
            if not lang_name:
                return self.default_stop_words

            if lang_name not in self._STOP_WORDS_CACHE:
                self._STOP_WORDS_CACHE[lang_name] = set(stopwords.words(lang_name))

            return self._STOP_WORDS_CACHE[lang_name]

        except ImportError:
            return self.default_stop_words
        except Exception:
            # Fallback for short/ambiguous text
            return self.default_stop_words

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
        tokens = re.findall(r"\b\w+\b", safe_text)

        # Filter stop words
        stop_words = self._get_stop_words_for_text(safe_text)
        filtered_tokens = [t for t in tokens if t not in stop_words and not t.isnumeric()]

        # Count frequencies
        frequencies = collections.Counter(filtered_tokens)

        # Map tokens to integer hashes (consistent across runs for the same vocab)
        # In production NLP, this would ideally be an exact vocabulary mapping.
        # Using built-in hash() is NOT deterministic across python processes.
        # We use a stable string hashing mechanism to ensure cross-process consistency.
        sparse_vector: dict[int, float] = {}
        for token, count in frequencies.items():
            # A simple deterministic hash modulo a large prime space to prevent excessive collisions
            token_id = self._deterministic_hash(token)
            sparse_vector[token_id] = float(count)

        return sparse_vector

    @staticmethod
    def _deterministic_hash(token: str) -> int:
        """Stable hashing function using hashlib.sha256 to avoid python's hash() randomization and pure-python bottlenecks."""
        hashed_bytes = hashlib.sha256(token.encode("utf-8")).digest()
        # Convert first 8 bytes of hash into an integer, bounded to avoid excessive sparsity ranges.
        integer_val = int.from_bytes(hashed_bytes[:8], byteorder="big")
        return integer_val % (10**9 + 7)
