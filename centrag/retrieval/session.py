"""
Conversation Session — Session-aware retrieval context.

SHARED INFRASTRUCTURE: Maintains conversation history for multi-turn RAG.

Features:
    - Per-session context window management
    - Automatic message pruning (FIFO with token budget)
    - Session expiry (configurable TTL)
    - History injection into retrieval prompts

Design Pattern: SESSION / UNIT OF WORK — track state across requests.

SOLID: Single Responsibility — only session management. No retrieval logic.
SOLID: Interface Segregation — separate from MemoryProtocol (long-term memory).
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from centrag.utils.logger import get_logger

logger = get_logger("retrieval.session")


class MessageRole(str, Enum):
    """Message roles in a conversation."""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


@dataclass
class Message:
    """A single conversation message."""

    role: MessageRole
    content: str
    timestamp: float = field(default_factory=time.monotonic)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def token_estimate(self) -> int:
        """Rough token count (words × 1.3)."""
        return int(len(self.content.split()) * 1.3)

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role.value,
            "content": self.content,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }


@dataclass
class SessionConfig:
    """Configuration for conversation sessions."""

    max_messages: int = 20  # Max messages per session
    max_context_tokens: int = 4000  # Token budget for context window
    ttl_seconds: float = 3600.0  # Session expiry (1 hour)
    system_prompt: str = (
        "You are a helpful document analysis assistant. "
        "Use the provided sources to answer questions accurately. "
        "Always cite your sources."
    )


class ConversationSession:
    """
    A single conversation session with history and context management.

    Usage:
        session = ConversationSession(session_id="s1", team_id="t1")
        session.add_user_message("What are the key risks?")
        context = session.build_context_window()
        # ... pass context to LLM ...
        session.add_assistant_message("The key risks are...")
    """

    def __init__(
        self,
        session_id: str = "",
        team_id: str = "",
        config: SessionConfig | None = None,
    ) -> None:
        self.session_id = session_id or str(uuid.uuid4())
        self.team_id = team_id
        self.config = config or SessionConfig()
        self._messages: list[Message] = []
        self._created_at = time.monotonic()
        self._last_activity = time.monotonic()

    @property
    def is_expired(self) -> bool:
        """Check if session has exceeded TTL."""
        return (time.monotonic() - self._last_activity) > self.config.ttl_seconds

    @property
    def message_count(self) -> int:
        return len(self._messages)

    @property
    def messages(self) -> list[Message]:
        return list(self._messages)

    def add_user_message(self, content: str, **metadata) -> None:
        """Add a user message to the conversation."""
        self._add_message(MessageRole.USER, content, metadata)

    def add_assistant_message(self, content: str, **metadata) -> None:
        """Add an assistant response to the conversation."""
        self._add_message(MessageRole.ASSISTANT, content, metadata)

    def _add_message(self, role: MessageRole, content: str, metadata: dict) -> None:
        """Add a message and prune if over limits."""
        self._messages.append(
            Message(
                role=role,
                content=content,
                metadata=metadata,
            )
        )
        self._last_activity = time.monotonic()
        self._prune()

    def _prune(self) -> None:
        """Remove oldest messages to stay within limits."""
        # Prune by count
        while len(self._messages) > self.config.max_messages:
            self._messages.pop(0)

        # Prune by token budget
        total_tokens = sum(m.token_estimate for m in self._messages)
        while total_tokens > self.config.max_context_tokens and len(self._messages) > 1:
            removed = self._messages.pop(0)
            total_tokens -= removed.token_estimate

    def build_context_window(self) -> list[dict[str, str]]:
        """
        Build the context window for LLM generation.

        Returns list of {"role": ..., "content": ...} dicts,
        compatible with OpenAI/Anthropic chat APIs.
        """
        window = [{"role": "system", "content": self.config.system_prompt}]
        for msg in self._messages:
            window.append({"role": msg.role.value, "content": msg.content})
        return window

    def get_conversation_summary(self) -> str:
        """
        Generate a text summary of the conversation for context injection.

        Used by the retrieval engine to understand what the user has
        already asked about (for follow-up query resolution).
        """
        if not self._messages:
            return ""

        parts = []
        for msg in self._messages[-6:]:  # Last 6 messages
            role_label = "User" if msg.role == MessageRole.USER else "Assistant"
            parts.append(f"{role_label}: {msg.content[:200]}")

        return "\n".join(parts)

    def clear(self) -> None:
        """Clear all messages (keep session alive)."""
        self._messages.clear()
        self._last_activity = time.monotonic()


class SessionManager:
    """
    Manages multiple conversation sessions per team.

    Usage:
        manager = SessionManager()
        session = manager.get_or_create("session-id", "team-1")
        session.add_user_message("Hello")
    """

    def __init__(self, default_config: SessionConfig | None = None) -> None:
        self._sessions: dict[str, ConversationSession] = {}
        self._config = default_config or SessionConfig()

    def get_or_create(self, session_id: str, team_id: str) -> ConversationSession:
        """Get existing session or create a new one."""
        if session_id in self._sessions:
            session = self._sessions[session_id]
            if session.is_expired:
                logger.info("session_expired", session_id=session_id)
                del self._sessions[session_id]
            else:
                return session

        session = ConversationSession(
            session_id=session_id,
            team_id=team_id,
            config=self._config,
        )
        self._sessions[session_id] = session
        logger.info(
            "session_created",
            session_id=session_id,
            team_id=team_id,
        )
        return session

    def get(self, session_id: str) -> ConversationSession | None:
        """Get a session by ID, or None if not found/expired."""
        session = self._sessions.get(session_id)
        if session and session.is_expired:
            del self._sessions[session_id]
            return None
        return session

    def delete(self, session_id: str) -> bool:
        """Delete a session. Returns True if it existed."""
        return self._sessions.pop(session_id, None) is not None

    def cleanup_expired(self) -> int:
        """Remove all expired sessions. Returns count removed."""
        expired = [sid for sid, s in self._sessions.items() if s.is_expired]
        for sid in expired:
            del self._sessions[sid]
        if expired:
            logger.info("sessions_cleaned", count=len(expired))
        return len(expired)

    @property
    def active_count(self) -> int:
        """Number of active (non-expired) sessions."""
        return sum(1 for s in self._sessions.values() if not s.is_expired)
