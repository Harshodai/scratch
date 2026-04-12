"""initial schema — teams, api_keys, documents, chunks, memory_entries, audit_logs + RLS

Revision ID: 001_initial_schema
Revises:
Create Date: 2026-04-07

Tables created:
  - teams: Multi-tenant team registry
  - api_keys: Hashed API keys with expiry
  - documents: Uploaded document metadata
  - chunks: Document chunks with vector references
  - memory_entries: Temporal memory with versioning
  - audit_logs: Immutable audit trail

Security:
  - RLS enabled + forced on all tenant-scoped tables
  - team_isolation policies using session variable app.current_team_id
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers
revision = "001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- teams ---
    op.create_table(
        "teams",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(255), unique=True, nullable=False),
        sa.Column("tier", sa.String(50), nullable=False, server_default="standard"),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true")),
        sa.Column("settings", postgresql.JSONB(), server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # --- api_keys ---
    op.create_table(
        "api_keys",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "team_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("teams.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("key_hash", sa.String(64), unique=True, nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true")),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_api_keys_key_hash", "api_keys", ["key_hash"])
    op.create_index("ix_api_keys_team_id", "api_keys", ["team_id"])

    # --- documents ---
    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "team_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("teams.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("namespace", sa.String(255), nullable=False, server_default="default"),
        sa.Column("filename", sa.String(512), nullable=False),
        sa.Column("s3_key", sa.String(1024), nullable=False),
        sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("chunk_count", sa.Integer(), server_default=sa.text("0")),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("error_message", sa.Text()),
        sa.Column("metadata", postgresql.JSONB(), server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_documents_team_namespace", "documents", ["team_id", "namespace"])
    op.create_index("ix_documents_status", "documents", ["status"])

    # --- chunks ---
    op.create_table(
        "chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "team_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("teams.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("vector_id", sa.String(100), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_chunks_document_id", "chunks", ["document_id"])
    op.create_index("ix_chunks_team_id", "chunks", ["team_id"])
    op.create_index("ix_chunks_vector_id", "chunks", ["vector_id"])

    # --- memory_entries ---
    op.create_table(
        "memory_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "team_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("teams.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("user_context", sa.String(255)),
        sa.Column("memory_content", sa.Text(), nullable=False),
        sa.Column("memory_type", sa.String(50), nullable=False),
        sa.Column("relevance_score", sa.Float(), server_default=sa.text("1.0")),
        sa.Column("vector_id", sa.String(100), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("valid_to", sa.DateTime(timezone=True)),
        sa.Column("superseded_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("memory_entries.id")),
        sa.Column("decay_score", sa.Float(), server_default=sa.text("1.0")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_accessed", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_memory_team_valid", "memory_entries", ["team_id", "valid_to"])
    op.create_index("ix_memory_type", "memory_entries", ["memory_type"])

    # --- audit_logs ---
    op.create_table(
        "audit_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("team_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("resource_type", sa.String(100), nullable=False),
        sa.Column("resource_id", sa.String(255)),
        sa.Column("details", postgresql.JSONB(), server_default=sa.text("'{}'")),
        sa.Column("ip_address", sa.String(45)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_audit_team_created", "audit_logs", ["team_id", "created_at"])

    # --- Row-Level Security ---
    rls_tables = ["documents", "chunks", "memory_entries", "audit_logs"]
    for table in rls_tables:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY team_isolation_{table} ON {table} "
            f"USING (team_id = current_setting('app.current_team_id')::uuid)"
        )


def downgrade() -> None:
    # Drop RLS policies first
    rls_tables = ["audit_logs", "memory_entries", "chunks", "documents"]
    for table in rls_tables:
        op.execute(f"DROP POLICY IF EXISTS team_isolation_{table} ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    # Drop tables in reverse dependency order
    op.drop_table("audit_logs")
    op.drop_table("memory_entries")
    op.drop_table("chunks")
    op.drop_table("documents")
    op.drop_table("api_keys")
    op.drop_table("teams")
