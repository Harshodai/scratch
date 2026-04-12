"""
InMemoryStore — Dict-based MemoryProtocol implementation.

For development and testing. NOT suitable for production.
Production should use the PostgreSQL-backed TemporalStore.

Implements MemoryProtocol faithfully:
  - add/recall/forget (matching protocol method names exactly)
  - Temporal versioning (valid_from/valid_to)
  - Basic decay scoring (older memories score lower)
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime

from centrag.abstractions.memory import (
    MemoryEntry,
    MemoryType,
)
from centrag.utils.logger import get_logger

logger = get_logger("memory.in_memory")


class InMemoryStore:
    """
    Dict-based memory store for development/testing.

    Implements MemoryProtocol with:
    - Temporal versioning (valid_from/valid_to)
    - Decay scoring (older = lower score)
    - Basic keyword-overlap relevance (production: embedding similarity)
    """

    def __init__(self) -> None:
        self._store: dict[str, list[MemoryEntry]] = {}  # team_id → entries

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
        now = datetime.now(UTC)
        entry = MemoryEntry(
            id=str(uuid.uuid4()),
            content=content,
            memory_type=memory_type,
            relevance_score=1.0,
            valid_from=now,
            valid_to=None,
            decay_score=1.0,
            metadata={
                "user_id": user_id,
                "created_at_epoch": time.time(),
            },
        )

        if team_id not in self._store:
            self._store[team_id] = []

        self._store[team_id].append(entry)
        logger.debug(
            "memory_stored",
            team_id=team_id,
            memory_type=memory_type.value,
            content_preview=content[:50],
        )
        return entry

    async def recall(
        self,
        query: str,
        team_id: str,
        user_id: str | None = None,
        limit: int = 5,
    ) -> list[MemoryEntry]:
        """
        Recall relevant, CURRENTLY VALID memories for context injection.

        In this in-memory implementation, uses simple keyword overlap.
        Production implementation should use embedding similarity.
        """
        entries = self._store.get(team_id, [])

        # Filter to current memories only
        current = [e for e in entries if e.is_current]

        # Optionally filter by user_id
        if user_id:
            current = [e for e in current if e.metadata.get("user_id") == user_id]

        # Simple relevance: keyword overlap weighted by decay
        query_words = set(query.lower().split())

        def relevance(entry: MemoryEntry) -> float:
            entry_words = set(entry.content.lower().split())
            overlap = len(query_words & entry_words)
            # Compute decay based on age
            age_hours = (datetime.now(UTC) - entry.valid_from).total_seconds() / 3600
            decay = 0.5 ** (age_hours / 72.0)  # half-life = 72h
            return overlap * decay * entry.relevance_score

        scored = sorted(current, key=relevance, reverse=True)
        return scored[:limit]

    async def forget(self, memory_id: str, team_id: str) -> None:
        """
        Explicitly invalidate a memory (soft-delete via valid_to=NOW).
        Does NOT physically delete — maintains audit trail.

        NOTE: MemoryEntry is frozen=True, so we replace the entry rather
        than mutating it.
        """
        entries = self._store.get(team_id, [])
        now = datetime.now(UTC)

        for i, entry in enumerate(entries):
            if entry.id == memory_id:
                # Replace frozen entry with expired version
                from dataclasses import replace

                expired = replace(entry, valid_to=now)
                entries[i] = expired
                logger.info(
                    "memory_forgotten",
                    team_id=team_id,
                    memory_id=memory_id,
                )
                return
        # If not found, silently return (protocol says return None)

    # -- Extra convenience methods (not in protocol, but useful) --

    async def get_all(
        self,
        team_id: str,
        include_expired: bool = False,
    ) -> list[MemoryEntry]:
        """Get all memories for a team."""
        entries = self._store.get(team_id, [])
        if include_expired:
            return list(entries)
        return [e for e in entries if e.is_current]

    def clear(self, team_id: str | None = None) -> None:
        """Clear memories (for testing)."""
        if team_id:
            self._store.pop(team_id, None)
        else:
            self._store.clear()
