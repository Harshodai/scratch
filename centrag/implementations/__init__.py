# centrag/implementations/__init__.py
"""
Concrete implementations of CentRAG abstractions.

This package contains REAL implementations of the Protocol abstractions
defined in centrag.abstractions. Each implementation is independently
testable and swappable via dependency injection.

Available implementations:
  - NoOp*:   Stubs for development/testing (no external dependencies)
  - Bedrock*: AWS Bedrock (embeddings, LLM)   [TODO: production]
  - Qdrant*:  Qdrant vector store              [TODO: production]
  - Cohere*:  Cohere reranker                  [TODO: production]
"""

from centrag.implementations.noop_embedder import NoOpEmbedder
from centrag.implementations.noop_vectorstore import NoOpVectorStore
from centrag.implementations.noop_llm import NoOpLLM
from centrag.implementations.noop_reranker import NoOpReranker

__all__ = [
    "NoOpEmbedder",
    "NoOpVectorStore",
    "NoOpLLM",
    "NoOpReranker",
]
