"""运行态存储的 PostgreSQL 实现（云上共享实例，独立 database）。

只存「推到哪儿了」这类运行状态；知识与原始增量都不进这里（见 `store.py` 模块注释）。
连接参数由 `MEMHUB_DB_URL` 提供，示例：

    postgresql://memhub_app@127.0.0.1:5432/memhub_prod

实现走 SQLAlchemy 2.0 async（`postgresql+psycopg` 驱动，ADR-0005），连接池异步，
接口全部 `async`。并发语义与旧实现一致：

- 同一 `(device_id, batch_id)` 用事务级 advisory lock 串行化，保证并发重放只应用一次；
- 同一 `(device_id, source_id)` 先 `INSERT ... ON CONFLICT DO NOTHING` 建行，再 `FOR UPDATE`
  锁行，游标推进因此是串行的，不会出现两个请求各写一半；
- 幂等窗口 24 小时，窗口外同 batch_id 视为新批次（契约 0.3），内容 `sha256` 兜底去重。

所有语句由 ORM/Core 构造，不写裸 SQL；唯一例外是 `migrations.py` 里的建表基线。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import CursorResult, delete, func, literal, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from memhub.contract import Cursor, FileCursor, IngestRequest, IngestResult
from memhub.ingest.migrations import ensure_schema
from memhub.ingest.models import (
    Batch,
    Device,
    SeenSha,
    Source,
)
from memhub.ingest.models import (
    FileCursor as FileCursorRow,
)
from memhub.ingest.store import CursorConflict

REPLAY_WINDOW = timedelta(hours=24)


def _async_dsn(dsn: str) -> str:
    """把 `postgresql://` 统一换成 SQLAlchemy 的异步方言前缀。

    已经带方言的 DSN 原样返回；未知格式也原样返回，让 SQLAlchemy 自己报清楚的错。
    """
    if "+" in dsn.split("://", 1)[0]:
        return dsn
    for prefix in ("postgresql://", "postgres://"):
        if dsn.startswith(prefix):
            return "postgresql+psycopg://" + dsn[len(prefix) :]
    return dsn


class PostgresStore:
    """`StateStore` 的生产实现。连接池、会话与事务由 SQLAlchemy async engine 管理。

    `schema` 只给隔离场景用（测试、联调各占一个 schema）；生产不传，落在库的默认 schema。
    """

    def __init__(
        self,
        dsn: str,
        *,
        min_size: int = 1,
        max_size: int = 5,
        schema: str | None = None,
    ) -> None:
        connect_args: dict[str, Any] = {}
        if schema:
            # libpq options：连接建立时就设好 search_path，不需要额外一轮查询。
            connect_args["options"] = f"-csearch_path={schema}"
        self.engine = create_async_engine(
            _async_dsn(dsn),
            pool_size=min_size,
            max_overflow=max(0, max_size - min_size),
            pool_pre_ping=True,
            connect_args=connect_args,
        )
        self.sessions: async_sessionmaker[AsyncSession] = async_sessionmaker(
            self.engine, expire_on_commit=False
        )

    async def close(self) -> None:
        await self.engine.dispose()

    async def migrate(self) -> list[str]:
        """建表/补迁移；返回本次应用的版本。启动时调用一次。"""
        async with self.engine.begin() as conn:
            applied = await conn.run_sync(ensure_schema)
        return applied

    # -- devices ---------------------------------------------------------
    async def register_device(self, device_id: str, *, name: str = "", platform: str = "") -> None:
        stmt = (
            pg_insert(Device)
            .values(device_id=device_id, name=name, platform=platform)
            .on_conflict_do_update(
                index_elements=[Device.device_id],
                set_={
                    "name": name,
                    "platform": platform,
                    "last_seen_at": func.now(),
                    "revoked_at": None,
                },
            )
        )
        async with self.sessions() as session, session.begin():
            await session.execute(stmt)

    async def is_registered(self, device_id: str) -> bool:
        stmt = select(Device.device_id).where(
            Device.device_id == device_id, Device.revoked_at.is_(None)
        )
        async with self.sessions() as session:
            return (await session.scalar(stmt)) is not None

    # -- cursors ---------------------------------------------------------
    async def get_cursor(self, device_id: str, source_id: str) -> tuple[int, list[FileCursor]]:
        async with self.sessions() as session:
            source_rev = await session.scalar(
                select(Source.source_rev).where(
                    Source.device_id == device_id, Source.source_id == source_id
                )
            )
            rows = (
                await session.scalars(
                    select(FileCursorRow)
                    .where(
                        FileCursorRow.device_id == device_id,
                        FileCursorRow.source_id == source_id,
                    )
                    .order_by(FileCursorRow.path)
                )
            ).all()
        files = [
            FileCursor(path=row.path, offset=row.offset, size=row.size, mtime=row.mtime)
            for row in rows
        ]
        return (int(source_rev) if source_rev is not None else 0), files

    async def cursor_summary(self, device_id: str, source_id: str) -> Cursor:
        async with self.sessions() as session:
            return await self._cursor_summary(session, device_id, source_id)

    @staticmethod
    async def _cursor_summary(session: AsyncSession, device_id: str, source_id: str) -> Cursor:
        row = (
            await session.execute(
                select(
                    func.count(),
                    func.coalesce(func.sum(FileCursorRow.offset), 0),
                ).where(
                    FileCursorRow.device_id == device_id,
                    FileCursorRow.source_id == source_id,
                )
            )
        ).one()
        last_at = await session.scalar(
            select(Source.last_at).where(
                Source.device_id == device_id, Source.source_id == source_id
            )
        )
        return Cursor(files=int(row[0]), bytes=int(row[1]), last_at=last_at)

    # -- ingest ----------------------------------------------------------
    async def apply(self, request: IngestRequest) -> IngestResult:
        now = datetime.now(UTC)
        async with self.sessions() as session, session.begin():
            await session.execute(
                select(
                    func.pg_advisory_xact_lock(
                        func.hashtextextended(f"{request.device_id}:{request.batch_id}", 0)
                    )
                )
            )
            previous = (
                await session.execute(
                    select(Batch.received_at, Batch.result).where(
                        Batch.device_id == request.device_id,
                        Batch.batch_id == request.batch_id,
                    )
                )
            ).first()
            if previous is not None and now - previous.received_at < REPLAY_WINDOW:
                replayed = IngestResult.model_validate(previous.result)
                return replayed.model_copy(update={"replayed": True})

            await session.execute(
                pg_insert(Source)
                .values(device_id=request.device_id, source_id=request.source_id)
                .on_conflict_do_nothing(index_elements=[Source.device_id, Source.source_id])
            )
            current_raw = await session.scalar(
                select(Source.source_rev)
                .where(
                    Source.device_id == request.device_id,
                    Source.source_id == request.source_id,
                )
                .with_for_update()
            )
            current_rev = int(current_raw) if current_raw is not None else 0
            reset_allowed = request.source_rev > current_rev

            accepted = 0
            duplicates = 0
            for batch_file in request.files:
                known = None
                if not reset_allowed:
                    known = await session.scalar(
                        select(FileCursorRow.offset).where(
                            FileCursorRow.device_id == request.device_id,
                            FileCursorRow.source_id == request.source_id,
                            FileCursorRow.path == batch_file.path,
                        )
                    )
                expected = int(known) if known is not None else 0
                if batch_file.from_offset < expected:
                    raise CursorConflict(batch_file.path, expected)

                marker = (
                    await session.execute(
                        pg_insert(SeenSha)
                        .values(source_id=request.source_id, sha256=batch_file.sha256)
                        .on_conflict_do_nothing(index_elements=[SeenSha.source_id, SeenSha.sha256])
                        .returning(literal(1))
                    )
                ).scalar_one_or_none()
                if marker is None:
                    duplicates += 1
                else:
                    accepted += 1

                # rescan（更高的 source_rev）时以客户端为准重置游标；
                # 常规追加时 expected 已保证 to_offset >= known offset。
                next_offset = (
                    batch_file.to_offset if reset_allowed else max(expected, batch_file.to_offset)
                )
                await session.execute(
                    pg_insert(FileCursorRow)
                    .values(
                        device_id=request.device_id,
                        source_id=request.source_id,
                        path=batch_file.path,
                        offset=next_offset,
                        size=batch_file.to_offset,
                        mtime=batch_file.mtime,
                    )
                    .on_conflict_do_update(
                        index_elements=[
                            FileCursorRow.device_id,
                            FileCursorRow.source_id,
                            FileCursorRow.path,
                        ],
                        set_={
                            "offset": next_offset,
                            "size": batch_file.to_offset,
                            "mtime": batch_file.mtime,
                        },
                    )
                )

            await session.execute(
                update(Source)
                .where(
                    Source.device_id == request.device_id,
                    Source.source_id == request.source_id,
                )
                .values(
                    source_rev=func.greatest(Source.source_rev, request.source_rev),
                    last_at=now,
                )
            )
            result = IngestResult(
                batch_id=request.batch_id,
                accepted=accepted,
                duplicates=duplicates,
                cursor=await self._cursor_summary(session, request.device_id, request.source_id),
            )
            payload = result.model_dump(mode="json")
            await session.execute(
                pg_insert(Batch)
                .values(
                    device_id=request.device_id,
                    batch_id=request.batch_id,
                    result=payload,
                )
                .on_conflict_do_update(
                    index_elements=[Batch.device_id, Batch.batch_id],
                    set_={"received_at": func.now(), "result": payload},
                )
            )
            return result

    # -- maintenance -----------------------------------------------------
    async def purge_expired(self, *, keep: timedelta = timedelta(hours=25)) -> int:
        """删掉重放窗口外的批次记录（窗口 24h，留 1h 余量给边界）。"""
        cutoff = datetime.now(UTC) - keep
        async with self.sessions() as session, session.begin():
            outcome = await session.execute(delete(Batch).where(Batch.received_at < cutoff))
        return int(cast(CursorResult[Any], outcome).rowcount)


__all__ = ["PostgresStore"]
