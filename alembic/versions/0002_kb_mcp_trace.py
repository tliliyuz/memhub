"""kb_mcp_trace：MCP 调用轨迹（ADR-0015，规格 docs/plans/mcp-trace-spec.md §2.1）。

只记元数据（时间、请求 id、凭据、工具、状态、耗时、参数摘要），不含参数原文、
正文与 token。`trace_id` 唯一实现重试与 spool 补投的幂等；不设外键。

Revision ID: 0002_kb_mcp_trace
Revises: 0001_kb_tables
Create Date: 2026-11-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_kb_mcp_trace"
down_revision: str | None = "0001_kb_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "kb_mcp_trace",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("trace_id", sa.Text(), nullable=False),
        sa.Column("request_id", sa.Text(), nullable=False),
        sa.Column("rpc_id", sa.Text(), nullable=True),
        sa.Column("called_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("credential_id", sa.Text(), nullable=True),
        sa.Column("credential_name", sa.Text(), nullable=True),
        sa.Column("tool", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.Integer(), nullable=True),
        sa.Column("error_kind", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("result_bytes", sa.Integer(), nullable=True),
        sa.Column("args_digest", sa.Text(), nullable=True),
        sa.Column("projects", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("client", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("trace_id", name="uq_kb_mcp_trace_trace_id"),
    )
    op.create_index("ix_kb_mcp_trace_called_at", "kb_mcp_trace", ["called_at"], unique=False)
    op.create_index("ix_kb_mcp_trace_tool", "kb_mcp_trace", ["tool", "called_at"], unique=False)
    op.create_index(
        "ix_kb_mcp_trace_credential",
        "kb_mcp_trace",
        ["credential_id", "called_at"],
        unique=False,
    )
    op.create_index("ix_kb_mcp_trace_status", "kb_mcp_trace", ["status", "called_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_kb_mcp_trace_status", table_name="kb_mcp_trace")
    op.drop_index("ix_kb_mcp_trace_credential", table_name="kb_mcp_trace")
    op.drop_index("ix_kb_mcp_trace_tool", table_name="kb_mcp_trace")
    op.drop_index("ix_kb_mcp_trace_called_at", table_name="kb_mcp_trace")
    op.drop_table("kb_mcp_trace")
