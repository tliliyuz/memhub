"""运行态表的 SQLAlchemy 模型（真源仍是 `migrations.py` 里的前向迁移）。

模型与既有 DDL 一一对应，只用于类型化查询与 upsert 构造；不要用
`Base.metadata.create_all` 建表——迁移历史由 `schema_migrations` 记录，
否则新旧库会出现两套建表路径。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Device(Base):
    __tablename__ = "devices"

    device_id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    platform: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Source(Base):
    __tablename__ = "sources"

    device_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("devices.device_id", ondelete="CASCADE"),
        primary_key=True,
    )
    source_id: Mapped[str] = mapped_column(Text, primary_key=True)
    source_rev: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FileCursor(Base):
    __tablename__ = "file_cursors"
    __table_args__ = (
        ForeignKeyConstraint(
            ["device_id", "source_id"],
            ["sources.device_id", "sources.source_id"],
            ondelete="CASCADE",
        ),
    )

    device_id: Mapped[str] = mapped_column(Text, primary_key=True)
    source_id: Mapped[str] = mapped_column(Text, primary_key=True)
    path: Mapped[str] = mapped_column(Text, primary_key=True)
    offset: Mapped[int] = mapped_column("offset", BigInteger, nullable=False)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mtime: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Batch(Base):
    __tablename__ = "batches"
    __table_args__ = (Index("batches_received_at_idx", "received_at"),)

    device_id: Mapped[str] = mapped_column(Text, primary_key=True)
    batch_id: Mapped[str] = mapped_column(Text, primary_key=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    result: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class SeenSha(Base):
    __tablename__ = "seen_shas"

    source_id: Mapped[str] = mapped_column(Text, primary_key=True)
    sha256: Mapped[str] = mapped_column(Text, primary_key=True)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SeenMessage(Base):
    """已成功抽取的消息 uuid（ADR-0017）。

    键按 `(project, source_id)` 隔离：同一 uuid 在另一个库或源里仍是新消息。
    不建外键——源清理后保留记录，避免重推时重复抽取；清理走 `forget_messages`。
    """

    __tablename__ = "seen_messages"

    project: Mapped[str] = mapped_column(Text, primary_key=True)
    source_id: Mapped[str] = mapped_column(Text, primary_key=True)
    uuid: Mapped[str] = mapped_column(Text, primary_key=True)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


__all__ = ["Base", "Batch", "Device", "FileCursor", "SeenMessage", "SeenSha", "Source"]
