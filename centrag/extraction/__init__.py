# centrag/extraction/__init__.py
"""
Extraction Layer — Converts raw documents to structured, chunked text.

This package is the FIRST stage of the RAG pipeline:
  Upload → [EXTRACT] → [CHUNK] → Embed → Store → Retrieve

Architecture:
  ExtractionPipeline (orchestrator)
    └─ selects Parser (Strategy Pattern) based on content_type
    └─ selects Chunker (Strategy Pattern) based on config
    └─ enriches chunks with document metadata
"""

from centrag.extraction.pipeline import ExtractionPipeline

__all__ = ["ExtractionPipeline"]
