"""长期记忆独立域：四张表与审计列（ADR-0016，规格 §3）。

Revision ID: 0005_long_term_memory
Revises: 0004_mcp_trace_funnel
Create Date: 2026-11-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_long_term_memory"
down_revision: str | None = "0004_mcp_trace_funnel"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MEMORY_SLUG_PATTERN = r"^[a-z0-9][a-z0-9-]{0,99}$"


def upgrade() -> None:
    op.create_table(
        "kb_memory_entries",
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("conclusion", sa.Text(), nullable=False),
        sa.Column("boundary", sa.Text(), server_default="", nullable=False),
        sa.Column("invalidation", sa.Text(), server_default="", nullable=False),
        sa.Column("evidence", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("confidence", sa.Double(), server_default="0.5", nullable=False),
        sa.Column("status", sa.Text(), server_default="active", nullable=False),
        sa.Column("deprecated_reason", sa.Text(), nullable=True),
        sa.Column("superseded_by", sa.Text(), nullable=True),
        sa.Column("contradicts", postgresql.ARRAY(sa.Text()), server_default="{}", nullable=False),
        sa.Column("revision", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(f"slug ~ '{_MEMORY_SLUG_PATTERN}'", name="ck_kb_memory_entries_slug"),
        sa.CheckConstraint(
            "status in ('active', 'deprecated')", name="ck_kb_memory_entries_status"
        ),
        sa.CheckConstraint(
            "confidence >= 0 and confidence <= 1", name="ck_kb_memory_entries_confidence"
        ),
        sa.PrimaryKeyConstraint("slug"),
    )
    op.create_index("ix_kb_memory_entries_status", "kb_memory_entries", ["status", "updated_at"])
    op.create_index("ix_kb_memory_entries_updated", "kb_memory_entries", ["updated_at"])

    op.create_table(
        "kb_memory_revisions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("revision", sa.Text(), nullable=False),
        sa.Column("actor", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("before", postgresql.JSONB(), nullable=False),
        sa.Column("after", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_kb_memory_revisions_slug", "kb_memory_revisions", ["slug", "created_at"])

    op.create_table(
        "kb_memory_snapshots",
        sa.Column("version", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("entries", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=False),
        sa.Column("note", sa.Text(), server_default="", nullable=False),
        sa.Column("actor", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status in ('published', 'superseded', 'disabled')",
            name="ck_kb_memory_snapshots_status",
        ),
        sa.PrimaryKeyConstraint("version"),
    )
    op.create_index(
        "uq_kb_memory_snapshots_published",
        "kb_memory_snapshots",
        ["status"],
        unique=True,
        postgresql_where=sa.column("status") == "published",
    )

    op.create_table(
        "kb_memory_candidates",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("conclusion", sa.Text(), nullable=False),
        sa.Column("boundary", sa.Text(), server_default="", nullable=False),
        sa.Column("invalidation", sa.Text(), server_default="", nullable=False),
        sa.Column("evidence", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("confidence", sa.Double(), server_default="0.5", nullable=False),
        sa.Column("session_count", sa.Integer(), nullable=False),
        sa.Column("project_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("contradicts", postgresql.ARRAY(sa.Text()), server_default="{}", nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status in ('pending', 'conflict', 'promoted')",
            name="ck_kb_memory_candidates_status",
        ),
        sa.CheckConstraint(
            "reason in ('below_threshold', 'conclusion_differs', 'deprecated')",
            name="ck_kb_memory_candidates_reason",
        ),
        sa.CheckConstraint(
            "confidence >= 0 and confidence <= 1", name="ck_kb_memory_candidates_confidence"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_index(
        "ix_kb_memory_candidates_status", "kb_memory_candidates", ["status", "last_seen_at"]
    )

    op.add_column(
        "kb_write_audit",
        sa.Column("memory_snapshot", sa.BigInteger(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("kb_write_audit", "memory_snapshot")
    op.drop_index("ix_kb_memory_candidates_status", table_name="kb_memory_candidates")
    op.drop_table("kb_memory_candidates")
    op.drop_index("uq_kb_memory_snapshots_published", table_name="kb_memory_snapshots")
    op.drop_table("kb_memory_snapshots")
    op.drop_index("ix_kb_memory_revisions_slug", table_name="kb_memory_revisions")
    op.drop_table("kb_memory_revisions")
    op.drop_index("ix_kb_memory_entries_updated", table_name="kb_memory_entries")
    op.drop_index("ix_kb_memory_entries_status", table_name="kb_memory_entries")
    op.drop_table("kb_memory_entries")
