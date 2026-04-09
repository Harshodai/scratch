"""
Storage package — Unified DocumentStore for dual-path RAG.

┌─────────────────────────────────────────────────────────────────────┐
│  SHARED INFRASTRUCTURE: Used by BOTH retrieval paths                │
│                                                                     │
│  DocumentStore is the single source of truth for all document       │
│  artifacts. Both the vectorless (PageIndex) and vector (Qdrant)     │
│  paths read from the same cleaned content stored here.              │
│                                                                     │
│  Layout per document:                                               │
│    data/documents/{team_id}/{doc_id}/                               │
│      ├── meta.json           — shared metadata                      │
│      ├── cleaned_text.txt    — PII-scrubbed text (shared)           │
│      ├── pageindex_tree.json — VECTORLESS path artifact             │
│      ├── page_cache.json     — VECTORLESS path artifact             │
│      └── chunks.json         — VECTOR path artifact (Day 3)         │
│                                                                     │
│  SDLC Boundary:                                                     │
│    - DocumentStore itself is path-neutral (shared)                  │
│    - pageindex_tree.json / page_cache.json → vectorless only        │
│    - chunks.json → vector only                                      │
│    - meta.json / cleaned_text.txt → both paths                     │
└─────────────────────────────────────────────────────────────────────┘
"""
from centrag.storage.document_store import DocumentStore, DocumentMeta

__all__ = [
    "DocumentStore",
    "DocumentMeta",
]
