"""
Abstractions package — The heart of SOLID in CentRAG.

┌─────────────────────────────────────────────────────────────────────┐
│  SOLID PRINCIPLE: Dependency Inversion (DIP)                        │
│                                                                     │
│  "High-level modules should NOT depend on low-level modules.        │
│   Both should depend on ABSTRACTIONS."                              │
│                                                                     │
│  Every Protocol in this package is an abstraction.                  │
│  The retrieval engine depends on EmbedderProtocol, not on           │
│  BedrockEmbedder. This means you can swap Bedrock for OpenAI        │
│  or a local model WITHOUT changing any business logic.              │
│                                                                     │
│  SOLID PRINCIPLE: Interface Segregation (ISP)                       │
│                                                                     │
│  Each protocol is SMALL and FOCUSED. EmbedderProtocol only embeds.  │
│  RerankerProtocol only reranks. No "GodService" that does           │
│  everything. If a component needs embedding + reranking, it         │
│  receives TWO separate dependencies, not one bloated interface.     │
└─────────────────────────────────────────────────────────────────────┘
"""
from centrag.abstractions.embedder import EmbedderProtocol
from centrag.abstractions.vectorstore import VectorStoreProtocol
from centrag.abstractions.llm import LLMProtocol
from centrag.abstractions.cache import CacheProtocol
from centrag.abstractions.reranker import RerankerProtocol
from centrag.abstractions.memory import MemoryProtocol
from centrag.abstractions.extractor import ExtractorProtocol
from centrag.abstractions.chunker import ChunkerProtocol
from centrag.abstractions.guardrail import InputRailProtocol, OutputRailProtocol

__all__ = [
    "EmbedderProtocol",
    "VectorStoreProtocol",
    "LLMProtocol",
    "CacheProtocol",
    "RerankerProtocol",
    "MemoryProtocol",
    "ExtractorProtocol",
    "ChunkerProtocol",
    "InputRailProtocol",
    "OutputRailProtocol",
]
