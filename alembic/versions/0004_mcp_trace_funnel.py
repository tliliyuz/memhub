"""kb_mcp_trace 增加发现层事件与工具数，支撑连接漏斗（ADR-0018）。

`event` 区分 `call` / `list_tools` / `initialize`；存量行一律回填 `call`，
保持旧数据的调用语义。`tool_count` 只在 `tools/list` 成功时非空。
索引 `(event, called_at)` 服务按事件过滤的列表与漏斗计数。

Revision ID: 0004_mcp_trace_funnel
Revises: 0003_canonical_tier
Create Date: 2026-11-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_mcp_trace_funnel"
down_revision: str | None = "0003_canonical_tier"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 先带列默认值加列以回填存量行，再移除默认值：模型侧只保留 Python 默认。
    op.add_column(
        "kb_mcp_trace",
        sa.Column("event", sa.Text(), nullable=False, server_default="call"),
    )
    op.alter_column("kb_mcp_trace", "event", existing_type=sa.Text(), server_default=None)
    op.add_column("kb_mcp_trace", sa.Column("tool_count", sa.Integer(), nullable=True))
    op.create_index("ix_kb_mcp_trace_event", "kb_mcp_trace", ["event", "called_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_kb_mcp_trace_event", table_name="kb_mcp_trace")
    op.drop_column("kb_mcp_trace", "tool_count")
    op.drop_column("kb_mcp_trace", "event")
