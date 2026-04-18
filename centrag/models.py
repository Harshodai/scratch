"""
Database Models — SQLAlchemy async models with Row-Level Security.

SOLID: Single Responsibility — models ONLY define schema. No business logic.

Design Pattern: REPOSITORY PATTERN (models are the "entities")
    - These define WHAT data looks like
    - Repository classes (not in this file) define HOW to access it

Security: ROW-LEVEL SECURITY (RLS)
    - Every table with team data has RLS policies
    - Even if code forgets a WHERE clause, PostgreSQL blocks cross-tenant access
    - FORCE ROW LEVEL SECURITY ensures even table owners are restricted
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from centrag.utils.time import utcnow


class Base(AsyncAttrs, DeclarativeBase):
    """Base class for all models."""

    pass


pass

if TYPE_CHECKING:
    from datetime import datetime

# =============================================================================
# TEAM & AUTH
# =============================================================================


class Team(Base):
    """The root entity for multi-tenant isolation.

    The WHY:
        CentRAG is an enterprise-grade platform where data isolation
        is the #1 requirement. Every resource (Documents, Chunks,
        Memories) must be anchored to a Team. This model manages
        the billing tier and global configuration tokens for the tenant.

    Attributes:
        id: Unique UUID used for Row-Level Security (RLS).
        name: Human-readable identifier for the organization.
        tier: Determines rate limits and access to advanced RAG patterns.
    """

    __tablename__ = "teams"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    tier: Mapped[str] = mapped_column(String(50), nullable=False, default="standard")  # standard | premium | enterprise
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    settings: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    # Relationships
    api_keys: Mapped[list[ApiKey]] = relationship(back_populates="team", lazy="selectin")
    documents: Mapped[list[Document]] = relationship(back_populates="team", lazy="noload")


class ApiKey(Base):
    """Secure access token for programmatic platform interaction.

    The WHY:
        Decouples user authentication from system-to-system integration.
        Each key is hashed (never stored in plain text) and scoped
        directly to a Team for secure API access.
    """

    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    team_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"), nullable=False
    )
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)  # "prod-key-1"
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Relationships
    team: Mapped[Team] = relationship(back_populates="api_keys")

    __table_args__ = (
        Index("ix_api_keys_key_hash", "key_hash"),
        Index("ix_api_keys_team_id", "team_id"),
    )


# =============================================================================
# DOCUMENTS & CHUNKS
# =============================================================================


class Document(Base):
    """Storage-aware representative of a processed source file.

    The WHY:
        Tracks the lifecycle of an ingested file from 'Pending' through
        'Ready'. By persisting MIME types and S3 keys, we can handle
        incremental updates and automatic re-processing when
        chunking strategies change.

    Lifecycle Status:
        - pending: File uploaded but not yet parsed.
        - processing: Extraction or chunking in progress.
        - ready: Indexed and available for retrieval.
        - failed: Terminal error during ingestion (see error_message).
    """

    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    team_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"), nullable=False
    )
    namespace: Mapped[str] = mapped_column(String(255), nullable=False, default="default")
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    s3_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="pending"
    )  # pending | processing | ready | failed
    error_message: Mapped[str | None] = mapped_column(Text)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Relationships
    team: Mapped[Team] = relationship(back_populates="documents")
    chunks: Mapped[list[Chunk]] = relationship(back_populates="document", lazy="noload")

    __table_args__ = (
        Index("ix_documents_team_namespace", "team_id", "namespace"),
        Index("ix_documents_status", "status"),
    )


class Chunk(Base):
    """A searchable segment of a document.

    The WHY:
        Standardizes the connection between relational metadata
        (Postgres) and high-performance vector retrieval (Qdrant).
        The `vector_id` is the glue that allows CentRAG to perform
        Hybrid Search while maintaining strict team filters.
    """

    __tablename__ = "chunks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    team_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"), nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    vector_id: Mapped[str] = mapped_column(String(100), nullable=False)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    # Relationships
    document: Mapped[Document] = relationship(back_populates="chunks")

    __table_args__ = (
        Index("ix_chunks_document_id", "document_id"),
        Index("ix_chunks_team_id", "team_id"),
        Index("ix_chunks_vector_id", "vector_id"),
    )


# =============================================================================
# MEMORY
# =============================================================================


class MemoryEntry(Base):
    """Temporal context memory (Zep/Graphiti-inspired).

    The WHY:
        Implements persistent agentic memory. New facts never
        overwrite the old; instead, we use `valid_from` and `valid_to`
        to create a temporal graph. This allows the RAG system to
        recall past state while avoiding contradiction by filtering
        for only 'currently active' facts.

    Attributes:
        superseded_by: Points to the new version of this fact.
        relevance_score: Used for similarity retrieval prioritization.
    """

    __tablename__ = "memory_entries"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    team_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"), nullable=False
    )
    user_context: Mapped[str | None] = mapped_column(String(255))
    memory_content: Mapped[str] = mapped_column(Text, nullable=False)
    memory_type: Mapped[str] = mapped_column(String(50), nullable=False)  # fact | preference | event | relation
    relevance_score: Mapped[float] = mapped_column(Float, default=1.0)
    vector_id: Mapped[str] = mapped_column(String(100), nullable=False)

    # --- Temporal versioning (Zep/HydraDB pattern) ---
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    superseded_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("memory_entries.id"))
    decay_score: Mapped[float] = mapped_column(Float, default=1.0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_accessed: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_memory_team_valid", "team_id", "valid_to"),
        Index("ix_memory_type", "memory_type"),
    )


# =============================================================================
# FEEDBACK & ACTIVE LEARNING
# =============================================================================


class Feedback(Base):
    """
    User feedback for active learning (thumbs up/down).
    """

    __tablename__ = "feedback"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    team_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"), nullable=False
    )
    request_id: Mapped[str | None] = mapped_column(String(255))
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="SET NULL")
    )
    query: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)  # -1 (down) | 1 (up)
    comments: Mapped[str | None] = mapped_column(Text)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        Index("ix_feedback_team_id", "team_id"),
        Index("ix_feedback_doc_id", "document_id"),
        Index("ix_feedback_score", "score"),
    )


class EvaluationFailure(Base):
    """Persisted evaluation failure case for continuous improvement.

    The WHY:
        When the RAG pipeline fails (low faithfulness, hallucination,
        retrieval miss), we need a queryable record of WHAT failed,
        WHY (category), and in WHICH context (path, difficulty, tags).
        This enables:
        - Failure pattern analysis across teams
        - Regression testing (did the fix resolve known failures?)
        - Golden dataset expansion (failures → new test cases)
        - Retraining signals (retrieval misses → fine-tune reranker)

    Complements the FailureStore (evaluation/failure_store.py) which
    provides the in-memory + JSON-file persistence for CI/CD.
    """

    __tablename__ = "evaluation_failures"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    team_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"), nullable=False
    )
    case_id: Mapped[str] = mapped_column(String(255), nullable=False)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    expected_answer: Mapped[str] = mapped_column(Text, nullable=False)
    generated_answer: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # retrieval_miss | hallucination | off_topic | low_coverage | latency_exceeded | guardrail_block
    composite_score: Mapped[float] = mapped_column(Float, nullable=False)
    retrieval_path: Mapped[str] = mapped_column(String(50), nullable=False)  # pageindex | vector | hybrid
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    judge_scores: Mapped[dict] = mapped_column(JSONB, default=dict)
    retrieval_metrics: Mapped[dict] = mapped_column(JSONB, default=dict)
    difficulty: Mapped[str] = mapped_column(String(50), default="moderate")
    tags: Mapped[list] = mapped_column(JSONB, default=list)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        Index("ix_eval_failures_team_id", "team_id"),
        Index("ix_eval_failures_category", "category"),
        Index("ix_eval_failures_created", "created_at"),
    )


# =============================================================================
# RLS POLICIES — Applied after table creation via Alembic migration
# =============================================================================

RLS_SETUP_SQL = """
-- Enable RLS on all tenant-scoped tables
ALTER TABLE documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE documents FORCE ROW LEVEL SECURITY;
ALTER TABLE chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE chunks FORCE ROW LEVEL SECURITY;
ALTER TABLE memory_entries ENABLE ROW LEVEL SECURITY;
ALTER TABLE memory_entries FORCE ROW LEVEL SECURITY;
ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_logs FORCE ROW LEVEL SECURITY;
ALTER TABLE feedback ENABLE ROW LEVEL SECURITY;
ALTER TABLE feedback FORCE ROW LEVEL SECURITY;

-- Create policies: users can only see rows where team_id matches session variable
CREATE POLICY team_isolation_documents ON documents
    USING (team_id = current_setting('app.current_team_id')::uuid);

CREATE POLICY team_isolation_chunks ON chunks
    USING (team_id = current_setting('app.current_team_id')::uuid);

CREATE POLICY team_isolation_memory ON memory_entries
    USING (team_id = current_setting('app.current_team_id')::uuid);

CREATE POLICY team_isolation_audit ON audit_logs
    USING (team_id = current_setting('app.current_team_id')::uuid);

CREATE POLICY team_isolation_feedback ON feedback
    USING (team_id = current_setting('app.current_team_id')::uuid);

ALTER TABLE evaluation_failures ENABLE ROW LEVEL SECURITY;
ALTER TABLE evaluation_failures FORCE ROW LEVEL SECURITY;
CREATE POLICY team_isolation_eval_failures ON evaluation_failures
    USING (team_id = current_setting('app.current_team_id')::uuid);
"""
