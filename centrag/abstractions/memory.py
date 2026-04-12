"""
Memory abstraction — persistent cross-session memory for teams/users.

SOLID: Interface Segregation — memory is SEPARATE from RAG retrieval.
       The retrieval engine optionally includes memory, not the other way around.

Design Pattern: COMPOSITE PATTERN
    - Memory combines multiple stores (Redis working + PG episodic + Neptune KG)
    - But exposes a single unified interface

RAG Advancement: TEMPORAL MEMORY (Zep/Graphiti pattern, 2025)
    - Facts are VERSIONED with valid_from/valid_to, never overwritten
    - Contradiction detection + resolution via temporal chaining
    - Decay scoring: unused memories gradually lose priority
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Protocol, runtime_checkable


class MemoryType(str, Enum):
    FACT = "fact"  # "Our primary database is CockroachDB"
    PREFERENCE = "preference"  # "User prefers tables over charts"
    EVENT = "event"  # "Migration completed on 2026-03-15"
    RELATION = "relation"  # "Team Alpha owns Service X"


@dataclass(frozen=True)
class MemoryEntry:
    """Immutable memory fact with temporal metadata."""

    id: str
    content: str
    memory_type: MemoryType
    relevance_score: float
    valid_from: datetime
    valid_to: datetime | None  # None = currently valid
    decay_score: float = 1.0  # 1.0 = fresh, approaches 0 = stale
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_current(self) -> bool:
        return self.valid_to is None


@runtime_checkable
class MemoryProtocol(Protocol):
    """Contract for the memory layer."""

    async def add(
        self,
        content: str,
        memory_type: MemoryType,
        team_id: str,
        user_id: str | None = None,
    ) -> MemoryEntry:
        """
        Store a new memory. If it conflicts with an existing one,
        the old memory gets valid_to=NOW() (temporal versioning).
        """
        ...

    async def recall(
        self,
        query: str,
        team_id: str,
        user_id: str | None = None,
        limit: int = 5,
    ) -> list[MemoryEntry]:
        """Retrieve relevant, CURRENTLY VALID memories for context injection."""
        ...

    async def forget(self, memory_id: str, team_id: str) -> None:
        """Explicitly invalidate a memory (sets valid_to = NOW)."""
        ...
