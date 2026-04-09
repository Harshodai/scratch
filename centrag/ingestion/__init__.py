"""
Ingestion package — Unified document ingestion for dual-path RAG.

┌─────────────────────────────────────────────────────────────────────┐
│  SHARED INFRASTRUCTURE: Feeds BOTH retrieval paths                  │
│                                                                     │
│  IngestionService is the single entry point for all document        │
│  ingestion. It orchestrates:                                        │
│    1. Parsing (via ExtractionPipeline)                              │
│    2. Cleaning (PII scrub + normalization, Day 2)                   │
│    3. Tree building (VECTORLESS path — PageIndex)                   │
│    4. Chunking + embedding (VECTOR path — Day 3)                   │
│                                                                     │
│  The user uploads ONCE; both paths get populated automatically.    │
└─────────────────────────────────────────────────────────────────────┘
"""
from centrag.ingestion.service import IngestionService, IngestionResult
from centrag.ingestion.cleaner import DocumentCleaner, DocumentCleanerConfig, CleaningResult
from centrag.ingestion.worker import IngestionWorker, IngestionJob, WorkerConfig, JobStatus

__all__ = [
    "IngestionService",
    "IngestionResult",
    "DocumentCleaner",
    "DocumentCleanerConfig",
    "CleaningResult",
    "IngestionWorker",
    "IngestionJob",
    "WorkerConfig",
    "JobStatus",
]
