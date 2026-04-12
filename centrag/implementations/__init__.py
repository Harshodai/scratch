# centrag/implementations/__init__.py
"""
Concrete implementations of CentRAG abstractions.

This package contains REAL implementations of the Protocol abstractions
defined in centrag.abstractions. Each implementation is independently
testable and swappable via dependency injection in centrag.wiring.

Available implementations:
  Embedders:
    - NoOpEmbedder:     Hash-based deterministic vectors (dev/test)
    - BedrockEmbedder:  AWS Bedrock Titan Text Embeddings V2 (production)
    - OpenAIEmbedder:   OpenAI text-embedding-3-small/large (production)

  Vector Stores:
    - NoOpVectorStore:  In-memory brute-force cosine similarity (dev/test)

  LLMs:
    - NoOpLLM:          Template-based generation (dev/test)

  Rerankers:
    - NoOpReranker:     Keyword overlap scoring (dev/test)

  Extractors:
    - LlamaParseExtractor: High-fidelity hierarchical parsing (production)
"""

from centrag.implementations.bedrock_embedder import BedrockEmbedder
from centrag.implementations.llama_parse_extractor import LlamaParseExtractor
from centrag.implementations.noop_embedder import NoOpEmbedder
from centrag.implementations.noop_llm import NoOpLLM
from centrag.implementations.noop_reranker import NoOpReranker
from centrag.implementations.noop_vectorstore import NoOpVectorStore
from centrag.implementations.openai_embedder import OpenAIEmbedder

__all__ = [
    # Dev/Test (NoOp)
    "NoOpEmbedder",
    "NoOpVectorStore",
    "NoOpLLM",
    "NoOpReranker",
    # Production Embedders
    "BedrockEmbedder",
    "OpenAIEmbedder",
    # Production Extractors
    "LlamaParseExtractor",
]
