"""知识真源的 ORM 表定义（ADR-0013，规格 `docs/plans/kb-pg-migration-spec.md` §3）。

自成一套 `Base`：与 `ingest/models.py` 的运行态 5 表分属两套迁移（规格 §4），
共用 metadata 会让 Alembic 误接管运行态表。

约束口径：
- `revision` 的 16 位小写 hex 格式由应用层生成并硬校验，库内不重复设 CHECK。
- `kb_edges` 与 `kb_node_revisions` 对节点 id **故意不设外键**（悬空边、软删后历史保留）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Double,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# 与 `KB_ID_RE` 同口径；改动时两处一起改。
_KB_ID_PATTERN = "^[a-z0-9][a-z0-9._-]{0,63}$"


class Base(DeclarativeBase):
    """知识表专用声明基类；Alembic 的 `target_metadata` 指向它。"""


def _timestamp(*, nullable: bool = False) -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), nullable=nullable)


class KbProject(Base):
    """知识库登记；`archived_at` 非空即整库归档。"""

    __tablename__ = "kb_projects"
    __table_args__ = (CheckConstraint(f"id ~ '{_KB_ID_PATTERN}'", name="ck_kb_projects_id"),)

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    revision: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _timestamp()
    updated_at: Mapped[datetime] = _timestamp()
    archived_at: Mapped[datetime | None] = _timestamp(nullable=True)


class KbNode(Base):
    """节点；`archived_at` 非空即软删。"""

    __tablename__ = "kb_nodes"
    __table_args__ = (
        Index("ix_kb_nodes_project_active", "project", postgresql_where="archived_at is null"),
        Index("ix_kb_nodes_project_kind", "project", "kind"),
        Index("ix_kb_nodes_tier", "tier"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    project: Mapped[str] = mapped_column(Text, ForeignKey("kb_projects.id"), nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    entity_kind: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    tier: Mapped[str] = mapped_column(Text, nullable=False, server_default="candidate")
    confidence: Mapped[float | None] = mapped_column(Double, nullable=True)
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default="{}")
    body: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, server_default="[]")
    valid_from: Mapped[datetime | None] = _timestamp(nullable=True)
    valid_until: Mapped[datetime | None] = _timestamp(nullable=True)
    supersedes: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default="{}")
    superseded_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    deprecated_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    occurred_at: Mapped[datetime | None] = _timestamp(nullable=True)
    decided_at: Mapped[datetime | None] = _timestamp(nullable=True)
    status: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = _timestamp()
    updated_at: Mapped[datetime] = _timestamp()
    archived_at: Mapped[datetime | None] = _timestamp(nullable=True)
    revision: Mapped[str] = mapped_column(Text, nullable=False)


class KbEdge(Base):
    """边；端点允许悬空，不加外键。"""

    __tablename__ = "kb_edges"
    __table_args__ = (UniqueConstraint("source", "predicate", "target", name="uq_kb_edges_triple"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    target: Mapped[str] = mapped_column(Text, nullable=False)
    predicate: Mapped[str] = mapped_column(Text, nullable=False)
    source_doc: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = _timestamp()


class KbNodeRevision(Base):
    """节点每次写入的不可变历史；`before`/`after` 是含正文的完整快照。"""

    __tablename__ = "kb_node_revisions"
    __table_args__ = (Index("ix_kb_node_revisions_node", "node_id", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    node_id: Mapped[str] = mapped_column(Text, nullable=False)
    revision: Mapped[str] = mapped_column(Text, nullable=False)
    tier: Mapped[str] = mapped_column(Text, nullable=False)
    actor: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    before: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    after: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = _timestamp()


class KbArchive(Base):
    """整库归档快照与状态；`snapshot` 直接入库。"""

    __tablename__ = "kb_archives"

    archive_id: Mapped[str] = mapped_column(Text, primary_key=True)
    project: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    snapshot: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    archived_count: Mapped[int] = mapped_column(Integer, nullable=False)
    removed_edges: Mapped[int] = mapped_column(Integer, nullable=False)
    actor: Mapped[str | None] = mapped_column(Text, nullable=True)
    deleted_at: Mapped[datetime | None] = _timestamp(nullable=True)
    created_at: Mapped[datetime] = _timestamp()


class KbWriteAudit(Base):
    """写入审计日志；不含正文与 token。"""

    __tablename__ = "kb_write_audit"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    actor: Mapped[str | None] = mapped_column(Text, nullable=True)
    project: Mapped[str | None] = mapped_column(Text, nullable=True)
    node_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    result: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _timestamp()
