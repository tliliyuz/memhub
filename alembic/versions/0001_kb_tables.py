"""kb_* 基线：建六张表与索引（ADR-0013 §4，规格 §4）。

只写 `op.create_table` / `op.create_index`，不写 SQL 字符串（ADR-0005，门禁扫
`alembic/`）。运行态 5 表不在这里，仍由 `ingest/migrations.py` 的冻结基线负责。

Revision ID: 0001_kb_tables
Revises:
Create Date: 2026-11-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_kb_tables"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# 与 `memhub.kb.models._KB_ID_PATTERN`、`KB_ID_RE` 同口径。
_KB_ID_PATTERN = r"^[a-z0-9][a-z0-9._-]{0,63}$"


def upgrade() -> None:
    op.create_table(
        "kb_projects",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("revision", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(f"id ~ '{_KB_ID_PATTERN}'", name="ck_kb_projects_id"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "kb_nodes",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("project", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("entity_kind", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("tier", sa.Text(), server_default="candidate", nullable=False),
        sa.Column("confidence", sa.Double(), nullable=True),
        sa.Column("tags", postgresql.ARRAY(sa.Text()), server_default="{}", nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("source", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("supersedes", postgresql.ARRAY(sa.Text()), server_default="{}", nullable=False),
        sa.Column("superseded_by", sa.Text(), nullable=True),
        sa.Column("deprecated_reason", sa.Text(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revision", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["project"], ["kb_projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_kb_nodes_project_active",
        "kb_nodes",
        ["project"],
        postgresql_where=sa.column("archived_at").is_(None),
    )
    op.create_index("ix_kb_nodes_project_kind", "kb_nodes", ["project", "kind"])
    op.create_index("ix_kb_nodes_tier", "kb_nodes", ["tier"])

    op.create_table(
        "kb_edges",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("project", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("target", sa.Text(), nullable=False),
        sa.Column("predicate", sa.Text(), nullable=False),
        sa.Column("source_doc", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source", "predicate", "target", name="uq_kb_edges_triple"),
    )

    op.create_table(
        "kb_node_revisions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("node_id", sa.Text(), nullable=False),
        sa.Column("revision", sa.Text(), nullable=False),
        sa.Column("tier", sa.Text(), nullable=False),
        sa.Column("actor", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("before", postgresql.JSONB(), nullable=False),
        sa.Column("after", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_kb_node_revisions_node", "kb_node_revisions", ["node_id", "created_at"])

    op.create_table(
        "kb_archives",
        sa.Column("archive_id", sa.Text(), nullable=False),
        sa.Column("project", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("snapshot", sa.LargeBinary(), nullable=False),
        sa.Column("archived_count", sa.Integer(), nullable=False),
        sa.Column("removed_edges", sa.Integer(), nullable=False),
        sa.Column("actor", sa.Text(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("archive_id"),
    )

    op.create_table(
        "kb_write_audit",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("actor", sa.Text(), nullable=True),
        sa.Column("project", sa.Text(), nullable=True),
        sa.Column("node_id", sa.Text(), nullable=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("result", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("kb_write_audit")
    op.drop_table("kb_archives")
    op.drop_index("ix_kb_node_revisions_node", table_name="kb_node_revisions")
    op.drop_table("kb_node_revisions")
    op.drop_table("kb_edges")
    op.drop_index("ix_kb_nodes_tier", table_name="kb_nodes")
    op.drop_index("ix_kb_nodes_project_kind", table_name="kb_nodes")
    op.drop_index("ix_kb_nodes_project_active", table_name="kb_nodes")
    op.drop_table("kb_nodes")
    op.drop_table("kb_projects")
