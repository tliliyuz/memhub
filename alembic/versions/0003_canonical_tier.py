"""存量 candidate 节点转 canonical，并把列默认值改为 canonical（ADR-0014）。

`upgrade` 做两件事：
1. `kb_nodes.tier='candidate'` 的存量行改为 `canonical`，生成新 `revision`，
   并追加一条 `actor='system'`、`reason='ADR-0014'` 的修订（before/after 为完整行快照）。
2. `kb_nodes.tier` 的列默认值从 `candidate` 改为 `canonical`。

`downgrade` 按修订行恢复 `tier` 与迁移前 `revision`（仅当节点自迁移后未被再写过），
删除这批修订行，并把列默认值改回 `candidate`。

`--sql` 离线模式只输出 DDL：离线无法读取存量行，数据迁移在离线时跳过。

Revision ID: 0003_canonical_tier
Revises: 0002_kb_mcp_trace
Create Date: 2026-11-26
"""

from __future__ import annotations

import secrets
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from alembic import context, op

revision: str = "0003_canonical_tier"
down_revision: str | None = "0002_kb_mcp_trace"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MIGRATED_TIER = "canonical"
_LEGACY_TIER = "candidate"
_REASON = "ADR-0014"
_ACTOR = "system"


def _new_revision() -> str:
    """16 位小写十六进制，与 `pgstore.new_revision` 同形。"""
    return secrets.token_hex(8)


def _snapshot(row: dict[str, Any]) -> dict[str, Any]:
    """整行 → JSONB 快照：时间统一成 UTC ISO 文本，其余原样。"""
    snapshot: dict[str, Any] = {}
    for key, value in row.items():
        if isinstance(value, datetime):
            moment = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
            snapshot[key] = moment.astimezone(UTC).isoformat()
        else:
            snapshot[key] = value
    return snapshot


def _tables(bind: sa.engine.Connection) -> tuple[sa.Table, sa.Table]:
    metadata = sa.MetaData()
    nodes = sa.Table("kb_nodes", metadata, autoload_with=bind)
    revisions = sa.Table("kb_node_revisions", metadata, autoload_with=bind)
    return nodes, revisions


def upgrade() -> None:
    op.alter_column("kb_nodes", "tier", existing_type=sa.Text(), server_default=_MIGRATED_TIER)
    if context.is_offline_mode():
        return

    bind = op.get_bind()
    nodes, revisions = _tables(bind)
    rows = bind.execute(sa.select(nodes).where(nodes.c.tier == _LEGACY_TIER)).mappings().all()
    for row in rows:
        before = _snapshot(dict(row))
        new_revision = _new_revision()
        after = {**before, "tier": _MIGRATED_TIER, "revision": new_revision}
        bind.execute(
            sa.update(nodes)
            .where(nodes.c.id == row["id"])
            .values(tier=_MIGRATED_TIER, revision=new_revision)
        )
        bind.execute(
            sa.insert(revisions).values(
                node_id=row["id"],
                revision=new_revision,
                tier=_MIGRATED_TIER,
                actor=_ACTOR,
                reason=_REASON,
                before=before,
                after=after,
                created_at=datetime.now(UTC),
            )
        )


def downgrade() -> None:
    op.alter_column("kb_nodes", "tier", existing_type=sa.Text(), server_default=_LEGACY_TIER)
    if context.is_offline_mode():
        return

    bind = op.get_bind()
    nodes, revisions = _tables(bind)
    marks = bind.execute(sa.select(revisions).where(revisions.c.reason == _REASON)).mappings().all()
    for mark in marks:
        before = mark["before"] or {}
        values: dict[str, Any] = {"tier": before.get("tier", _LEGACY_TIER)}
        if before.get("revision"):
            values["revision"] = before["revision"]
        # 迁移后又被写过的节点保留当前内容，不把后续 canonical 写入降回 candidate。
        bind.execute(
            sa.update(nodes)
            .where(nodes.c.id == mark["node_id"], nodes.c.revision == mark["revision"])
            .values(**values)
        )
        bind.execute(sa.delete(revisions).where(revisions.c.id == mark["id"]))
