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
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from datetime import datetime


class MemoryType(StrEnum):
    """Categories of facts stored in CentRAG's temporal memory.

    The WHY:
        Different facts have different decay rates and confidence
        thresholds. User Preferences (e.g., "I prefer dark mode")
        rarely change, while Event facts (e.g., "Deployment is today")
        become stale almost immediately.
    """

    FACT = "fact"  # e.g., "Our primary database is CockroachDB"
    PREFERENCE = "preference"  # e.g., "User prefers tables over charts"
    EVENT = "event"  # e.g., "Migration completed on 2026-03-15"
    RELATION = "relation"  # e.g., "Team Alpha owns Service X"


@dataclass(frozen=True)
class MemoryEntry:
    """Immutable memory fact with temporal metadata.

    The WHY:
        By using Temporal Versioning (`valid_from` / `valid_to`), we ensure
        that a RAG system can "learn" and "forget" without losing audit
        history. If a user changes their preference, the old fact is
        not deleted but marked as "expired."

    Attributes:
        id: Unique UUID for this specific version of the fact.
        content: The actual text or knowledge captured (grounded).
        memory_type: Categorization based on the MemoryType enum.
        relevance_score: How closely this matches current user queries.
        valid_from: When this knowledge became "TRUE."
        valid_to: When this knowledge was superseded or expired.
        decay_score: A fading weight (1.0 to 0.0) based on age and usage frequency.
    """

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
        """Helper to determine if this fact is currently active.

        Returns:
            bool: True if the fact has not been superseded.
        """
        return self.valid_to is None


@runtime_checkable
class MemoryProtocol(Protocol):
    """Contract for the CentRAG memory layer.

    The WHY:
        This protocol implements a COMPOSITE PATTERN. While
        the engine sees a single memory protocol, the implementation
        may orchestrate between Redis (Working Memory) and
        Postgres/Neptune (Episodic/Graph Memory).

    Isolation:
        All memory operations are strictly partitioned by `team_id`
        to ensure cross-tenant data privacy.
    """

    async def add(
        self,
        content: str,
        memory_type: MemoryType,
        team_id: str,
        user_id: str | None = None,
    ) -> MemoryEntry:
        """Store a new memory.

        Side Effects:
            If the new content contradicts an existing memory, the
            existing record is "expired" (sets valid_to = NOW) to
            maintain the temporal chain.

        Args:
            content: The raw text knowledge to store.
            memory_type: Category (FACT, PREFERENCE, etc.).
            team_id: Tenant UUID.
            user_id: Optional user identifier for personalized memory.

        Returns:
            MemoryEntry: The finalized, timestamped memory record.
        """
        ...

    async def recall(
        self,
        query: str,
        team_id: str,
        user_id: str | None = None,
        limit: int = 5,
    ) -> list[MemoryEntry]:
        """Retrieve relevant, CURRENTLY VALID memories for context.

        The WHY:
            Memory recall allows the RAG generator to "know" who the
            user is and what they've previously said, creating a
            seamless conversational experience over long periods.

        Args:
            query: The current prompt or query for similarity lookup.
            team_id: Tenant UUID.
            user_id: Optional user identifier.
            limit: Maximum number of memories to return.

        Returns:
            list[MemoryEntry]: A list of facts to be prepended to the LLM context.
        """
        ...

    async def forget(self, memory_id: str, team_id: str) -> None:
        """Explicitly invalidate a memory (sets valid_to = NOW).

        Args:
            memory_id: The specific UUID to expire.
            team_id: The tenant owning the memory.
        """
        ...
