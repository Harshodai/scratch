# centrag/memory/__init__.py
"""
Memory Subsystem — Persistent, temporal, versioned fact storage.

Separates memory PROTOCOL (in centrag.abstractions.memory) from
IMPLEMENTATIONS (in this package).
"""

from centrag.memory.in_memory_store import InMemoryStore

__all__ = ["InMemoryStore"]
