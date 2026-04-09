"""
Tests for ConversationSession and SessionManager.

Verifies:
    - Message lifecycle (add, prune, clear)
    - Token budget pruning
    - Session TTL expiry
    - Context window generation
    - SessionManager CRUD + cleanup
"""
from __future__ import annotations

import time
import pytest

from centrag.retrieval.session import (
    ConversationSession,
    SessionConfig,
    SessionManager,
    MessageRole,
)


# ── Message Management ──────────────────────────────────────────────

class TestMessageManagement:
    """Add, retrieve, and clear messages."""

    def test_add_user_message(self):
        session = ConversationSession(session_id="s1", team_id="t1")
        session.add_user_message("Hello")

        assert session.message_count == 1
        assert session.messages[0].role == MessageRole.USER
        assert session.messages[0].content == "Hello"

    def test_add_assistant_message(self):
        session = ConversationSession()
        session.add_assistant_message("Hi there!")

        assert session.message_count == 1
        assert session.messages[0].role == MessageRole.ASSISTANT

    def test_conversation_flow(self):
        session = ConversationSession()
        session.add_user_message("What are the risks?")
        session.add_assistant_message("The key risks are...")
        session.add_user_message("Tell me more about risk 1")

        assert session.message_count == 3

    def test_clear_messages(self):
        session = ConversationSession()
        session.add_user_message("Hello")
        session.add_assistant_message("Hi")
        session.clear()

        assert session.message_count == 0

    def test_metadata_on_message(self):
        session = ConversationSession()
        session.add_user_message("Query", source="api", request_id="r1")

        msg = session.messages[0]
        assert msg.metadata["source"] == "api"
        assert msg.metadata["request_id"] == "r1"


# ── Pruning ─────────────────────────────────────────────────────────

class TestPruning:
    """Message count and token budget pruning."""

    def test_prune_by_count(self):
        config = SessionConfig(max_messages=3)
        session = ConversationSession(config=config)

        for i in range(5):
            session.add_user_message(f"Message {i}")

        assert session.message_count == 3
        # Oldest messages pruned
        assert "Message 2" in session.messages[0].content

    def test_prune_by_token_budget(self):
        config = SessionConfig(
            max_messages=100,
            max_context_tokens=20,  # Very small budget
        )
        session = ConversationSession(config=config)

        session.add_user_message("A " * 50)  # ~65 tokens
        session.add_user_message("B " * 50)  # ~65 tokens

        # Should prune to fit budget
        assert session.message_count >= 1
        # At least the most recent message survives
        assert "B" in session.messages[-1].content


# ── Context Window ──────────────────────────────────────────────────

class TestContextWindow:
    """Context window generation for LLM."""

    def test_includes_system_prompt(self):
        config = SessionConfig(system_prompt="You are helpful.")
        session = ConversationSession(config=config)
        session.add_user_message("Hello")

        window = session.build_context_window()
        assert window[0]["role"] == "system"
        assert window[0]["content"] == "You are helpful."

    def test_includes_all_messages(self):
        session = ConversationSession()
        session.add_user_message("Q1")
        session.add_assistant_message("A1")
        session.add_user_message("Q2")

        window = session.build_context_window()
        # system + 3 messages
        assert len(window) == 4
        assert window[1]["role"] == "user"
        assert window[2]["role"] == "assistant"
        assert window[3]["role"] == "user"

    def test_conversation_summary(self):
        session = ConversationSession()
        session.add_user_message("What are the risks?")
        session.add_assistant_message("The main risks are A, B, C.")

        summary = session.get_conversation_summary()
        assert "User:" in summary
        assert "Assistant:" in summary
        assert "risks" in summary.lower()

    def test_empty_summary(self):
        session = ConversationSession()
        assert session.get_conversation_summary() == ""


# ── Session Expiry ──────────────────────────────────────────────────

class TestSessionExpiry:
    """TTL-based session expiration."""

    def test_not_expired_initially(self):
        session = ConversationSession()
        assert session.is_expired is False

    def test_expires_after_ttl(self):
        config = SessionConfig(ttl_seconds=0.1)
        session = ConversationSession(config=config)

        time.sleep(0.15)
        assert session.is_expired is True

    def test_activity_resets_ttl(self):
        config = SessionConfig(ttl_seconds=0.2)
        session = ConversationSession(config=config)

        time.sleep(0.1)
        session.add_user_message("Keep alive")
        time.sleep(0.1)

        assert session.is_expired is False  # Activity reset the timer


# ── Session Manager ─────────────────────────────────────────────────

class TestSessionManager:
    """SessionManager CRUD and lifecycle."""

    def test_get_or_create_new(self):
        mgr = SessionManager()
        session = mgr.get_or_create("s1", "t1")

        assert session.session_id == "s1"
        assert session.team_id == "t1"
        assert mgr.active_count == 1

    def test_get_or_create_existing(self):
        mgr = SessionManager()
        s1 = mgr.get_or_create("s1", "t1")
        s1.add_user_message("Hello")

        s2 = mgr.get_or_create("s1", "t1")
        assert s2.message_count == 1  # Same session

    def test_get_returns_none_for_missing(self):
        mgr = SessionManager()
        assert mgr.get("nonexistent") is None

    def test_delete_session(self):
        mgr = SessionManager()
        mgr.get_or_create("s1", "t1")
        assert mgr.delete("s1") is True
        assert mgr.delete("s1") is False  # Already deleted

    def test_expired_session_creates_new(self):
        config = SessionConfig(ttl_seconds=0.05)
        mgr = SessionManager(default_config=config)

        s1 = mgr.get_or_create("s1", "t1")
        s1.add_user_message("Old message")

        time.sleep(0.1)

        s2 = mgr.get_or_create("s1", "t1")
        assert s2.message_count == 0  # New session

    def test_cleanup_expired(self):
        config = SessionConfig(ttl_seconds=0.05)
        mgr = SessionManager(default_config=config)

        mgr.get_or_create("s1", "t1")
        mgr.get_or_create("s2", "t1")

        time.sleep(0.1)

        removed = mgr.cleanup_expired()
        assert removed == 2
        assert mgr.active_count == 0
