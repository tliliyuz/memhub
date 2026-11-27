"""提炼队列：待提炼条目的真源（ADR-0020）。

正文在 ClickHouse（`content.py`），这里只存「哪条内容、属于哪个库、轮到谁处理」。
生产实现是 PG 表 `ingest_queue`，主键 `(project, sha256)`：

- ingest 在正文写入成功后插入 `queued` 行；同一 `(project, sha256)` 只插一次，
  因此接受判重不再依赖 `seen_shas`；
- worker 用 `SELECT ... FOR UPDATE SKIP LOCKED` 领取，领取即写 `processing/claimed_at`；
- 成功 → `processed`；临时不可用 → 退回 `queued`（不消耗失败次数）；
  连续失败到上限或永久拒绝 → `pending_review`；
- 超过租约仍处于 `processing` 的行由下一轮领取自动回收成 `queued`。

`MemoryQueue` 只给 dev / 测试用，进程重启即丢。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Protocol, cast

from sqlalchemy import CursorResult, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from memhub.contract import IngestRequest, explicit_project
from memhub.ingest.models import IngestQueue
from memhub.queue.content import ContentEntry
from memhub.queue.identity import (
    CONSOLE_DEVICE,
    BatchTargetConflict,
    collector_device_reserved,
)

TaskStatus = Literal["queued", "processing", "processed", "pending_review"]
Producer = Literal["collector", "console"]

DEFAULT_LEASE = timedelta(minutes=15)
DEFAULT_MAX_ATTEMPTS = 3
# 失败原因落库时截断，避免模型返回整段文本把行撑大。
ERROR_LIMIT = 2000


class QuotaExceeded(Exception):
    """待提炼内容已到上限：拒绝该批，客户端按 1008 降级重试。"""

    def __init__(self, used: int, limit: int, incoming: int) -> None:
        super().__init__(f"queue quota exceeded: {used}+{incoming} > {limit}")
        self.used = used
        self.limit = limit
        self.incoming = incoming


@dataclass(frozen=True)
class QueueTask:
    """领取到的一条待提炼内容。正文需再按 `(project, sha256)` 从正文存储取。"""

    project: str
    sha256: str
    device_id: str
    source_id: str
    source_type: str
    batch_id: str
    path: str
    from_offset: int
    to_offset: int
    mtime: datetime
    producer: str
    bytes: int
    attempts: int
    claimed_at: datetime | None


@dataclass(frozen=True)
class EnqueuePlan:
    """写入前的检查结果：真正要新写的条目、字节数与重复文件数。"""

    project: str
    entries: tuple[ContentEntry, ...]
    new_bytes: int
    duplicates: int

    @property
    def accepted(self) -> int:
        return len(self.entries)


@dataclass(frozen=True)
class EnqueueOutcome:
    accepted: int
    duplicates: int
    queued: int


@dataclass(frozen=True)
class BatchProgress:
    """一个批次的提炼进度；`status` 是给管理台看的汇总状态。"""

    batch_id: str
    total: int
    queued: int = 0
    processing: int = 0
    processed: int = 0
    pending_review: int = 0
    errors: tuple[str, ...] = ()
    created_at: datetime | None = None

    @property
    def status(self) -> TaskStatus:
        if self.pending_review:
            return "pending_review"
        if self.processing:
            return "processing"
        if self.queued:
            return "queued"
        return "processed"


@dataclass(frozen=True)
class BatchItem:
    """批次里的单条内容；kb 状态接口据此还原文件列表。"""

    name: str
    sha256: str
    status: TaskStatus
    attempts: int


class QueueStore(Protocol):
    """队列契约。所有方法 async；实现可被多个 worker 并发调用。"""

    async def check(self, request: IngestRequest, *, producer: Producer, limit: int) -> EnqueuePlan:
        """校验目标/配额并返回待写条目；不落任何状态。"""
        ...

    async def enqueue(
        self, request: IngestRequest, *, producer: Producer, limit: int
    ) -> EnqueueOutcome:
        """在事务里重新校验并插入队列行；与 `check` 的结论不一致时以事务内为准。"""
        ...

    async def claim(self, *, limit: int = 20, lease: timedelta = DEFAULT_LEASE) -> list[QueueTask]:
        """领取至多 `limit` 条；顺带回收租约过期的 processing 行。"""
        ...

    async def complete(self, task: QueueTask) -> None: ...

    async def retry(
        self,
        task: QueueTask,
        error: str,
        *,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    ) -> TaskStatus:
        """失败一次：未到上限退回 queued，到上限转 pending_review。返回新状态。"""
        ...

    async def review(self, task: QueueTask, error: str) -> None:
        """永久拒绝（内容不可解析等）：直接转 pending_review，不再重试。"""
        ...

    async def release(self, task: QueueTask) -> None:
        """临时不可用：退回 queued，且不消耗失败次数。"""
        ...

    async def pending_bytes(self) -> int:
        """`queued + processing` 的正文字节数，用于 `MEMHUB_QUEUE_MAX_BYTES`。"""
        ...

    async def batch_progress(self, project: str, batch_id: str) -> BatchProgress | None: ...

    async def batch_project(self, batch_id: str) -> str | None:
        """批次唯一对应的库；找不到或有歧义返回 None。"""
        ...

    async def batch_items(self, project: str, batch_id: str) -> list[BatchItem]: ...

    async def purge_source(self, device_id: str, source_id: str) -> dict[str, int]:
        """按状态删除一个设备源的队列行；返回各状态删除数。"""
        ...

    async def trim(self, *, before: datetime) -> int:
        """删除 `processed_at < before` 的 processed 行；返回删除行数。"""
        ...

    async def close(self) -> None: ...


def project_for(request: IngestRequest, producer: Producer) -> str:
    """目标/身份校验；不合法一律按目标冲突处理（对外 400 target_conflict）。"""
    project = explicit_project(request.project)
    if project is None:
        raise BatchTargetConflict()
    if producer == "console":
        # 管理台上传的身份是固定的：设备 kb-console、类型 docs、源就是目标库。
        if (request.device_id, request.source_type, request.source_id) != (
            CONSOLE_DEVICE,
            "docs",
            project,
        ):
            raise BatchTargetConflict()
    elif collector_device_reserved(request.device_id):
        raise BatchTargetConflict()
    return project


def _plan(
    request: IngestRequest,
    *,
    project: str,
    producer: Producer,
    known_projects: Mapping[str, set[str]],
    used: int,
    limit: int,
) -> EnqueuePlan:
    """按「同一 sha 不得换目标」与「只计新增」两条规则算出待写条目。"""
    for projects in known_projects.values():
        if any(other != project for other in projects):
            raise BatchTargetConflict()

    entries: list[ContentEntry] = []
    seen: set[str] = {sha for sha, projects in known_projects.items() if project in projects}
    duplicates = 0
    new_bytes = 0
    for batch_file in request.files:
        if batch_file.sha256 in seen:
            duplicates += 1
            continue
        seen.add(batch_file.sha256)
        size = len(batch_file.content.encode("utf-8"))
        new_bytes += size
        entries.append(
            ContentEntry(
                project=project,
                sha256=batch_file.sha256,
                device_id=request.device_id,
                source_id=request.source_id,
                source_type=request.source_type,
                batch_id=request.batch_id,
                path=batch_file.path,
                from_offset=batch_file.from_offset,
                to_offset=batch_file.to_offset,
                mtime=batch_file.mtime,
                producer=producer,
                content=batch_file.content,
            )
        )
    if used + new_bytes > limit:
        raise QuotaExceeded(used=used, limit=limit, incoming=new_bytes)
    return EnqueuePlan(
        project=project, entries=tuple(entries), new_bytes=new_bytes, duplicates=duplicates
    )


def _task_from_columns(
    *,
    project: str,
    sha256: str,
    device_id: str,
    source_id: str,
    source_type: str,
    batch_id: str,
    path: str,
    from_offset: int,
    to_offset: int,
    mtime: datetime,
    producer: str,
    size: int,
    attempts: int,
    claimed_at: datetime | None,
) -> QueueTask:
    return QueueTask(
        project=project,
        sha256=sha256,
        device_id=device_id,
        source_id=source_id,
        source_type=source_type,
        batch_id=batch_id,
        path=path,
        from_offset=from_offset,
        to_offset=to_offset,
        mtime=mtime,
        producer=producer,
        bytes=size,
        attempts=attempts,
        claimed_at=claimed_at,
    )


# -- 内存实现（dev / 测试） ----------------------------------------------


@dataclass
class _MemoryRow:
    project: str
    sha256: str
    device_id: str
    source_id: str
    source_type: str
    batch_id: str
    path: str
    from_offset: int
    to_offset: int
    mtime: datetime
    producer: str
    size: int
    status: TaskStatus = "queued"
    attempts: int = 0
    claimed_at: datetime | None = None
    error: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    processed_at: datetime | None = None

    def task(self) -> QueueTask:
        return _task_from_columns(
            project=self.project,
            sha256=self.sha256,
            device_id=self.device_id,
            source_id=self.source_id,
            source_type=self.source_type,
            batch_id=self.batch_id,
            path=self.path,
            from_offset=self.from_offset,
            to_offset=self.to_offset,
            mtime=self.mtime,
            producer=self.producer,
            size=self.size,
            attempts=self.attempts,
            claimed_at=self.claimed_at,
        )


class MemoryQueue:
    """进程内队列：单进程 dev 联调与测试用，不保证跨进程领取。"""

    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], _MemoryRow] = {}

    def _known(self, shas: Sequence[str]) -> dict[str, set[str]]:
        known: dict[str, set[str]] = {}
        wanted = set(shas)
        for project, sha in self.rows:
            if sha in wanted:
                known.setdefault(sha, set()).add(project)
        return known

    async def check(self, request: IngestRequest, *, producer: Producer, limit: int) -> EnqueuePlan:
        project = project_for(request, producer)
        known = self._known([f.sha256 for f in request.files])
        return _plan(
            request,
            project=project,
            producer=producer,
            known_projects=known,
            used=await self.pending_bytes(),
            limit=limit,
        )

    async def enqueue(
        self, request: IngestRequest, *, producer: Producer, limit: int
    ) -> EnqueueOutcome:
        project = project_for(request, producer)
        plan = _plan(
            request,
            project=project,
            producer=producer,
            known_projects=self._known([f.sha256 for f in request.files]),
            used=await self.pending_bytes(),
            limit=limit,
        )
        queued = 0
        for entry in plan.entries:
            key = (entry.project, entry.sha256)
            if key in self.rows:
                continue
            self.rows[key] = _MemoryRow(
                project=entry.project,
                sha256=entry.sha256,
                device_id=entry.device_id,
                source_id=entry.source_id,
                source_type=entry.source_type,
                batch_id=entry.batch_id,
                path=entry.path,
                from_offset=entry.from_offset,
                to_offset=entry.to_offset,
                mtime=entry.mtime,
                producer=entry.producer,
                size=len(entry.content.encode("utf-8")),
            )
            queued += 1
        accepted = queued
        return EnqueueOutcome(
            accepted=accepted, duplicates=len(request.files) - accepted, queued=queued
        )

    async def claim(self, *, limit: int = 20, lease: timedelta = DEFAULT_LEASE) -> list[QueueTask]:
        now = datetime.now(UTC)
        for row in self.rows.values():
            if row.status == "processing" and (
                row.claimed_at is None or row.claimed_at < now - lease
            ):
                row.status = "queued"
                row.claimed_at = None
        ready = sorted(
            (row for row in self.rows.values() if row.status == "queued"),
            key=lambda row: (row.created_at, row.sha256),
        )[:limit]
        for row in ready:
            row.status = "processing"
            row.claimed_at = now
            row.attempts += 1
        return [row.task() for row in ready]

    def _row(self, task: QueueTask) -> _MemoryRow | None:
        row = self.rows.get((task.project, task.sha256))
        if row is None or row.status != "processing":
            return None
        return row

    async def complete(self, task: QueueTask) -> None:
        row = self._row(task)
        if row is None:
            return
        row.status = "processed"
        row.processed_at = datetime.now(UTC)
        row.claimed_at = None
        row.error = None

    async def retry(
        self,
        task: QueueTask,
        error: str,
        *,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    ) -> TaskStatus:
        row = self._row(task)
        if row is None:
            return "queued"
        row.error = error[:ERROR_LIMIT]
        row.claimed_at = None
        row.status = "pending_review" if row.attempts >= max_attempts else "queued"
        return row.status

    async def review(self, task: QueueTask, error: str) -> None:
        row = self._row(task)
        if row is None:
            return
        row.status = "pending_review"
        row.claimed_at = None
        row.error = error[:ERROR_LIMIT]

    async def release(self, task: QueueTask) -> None:
        row = self._row(task)
        if row is None:
            return
        row.status = "queued"
        row.claimed_at = None
        row.attempts = max(row.attempts - 1, 0)

    async def pending_bytes(self) -> int:
        return sum(row.size for row in self.rows.values() if row.status in {"queued", "processing"})

    async def batch_progress(self, project: str, batch_id: str) -> BatchProgress | None:
        rows = [
            row for row in self.rows.values() if row.project == project and row.batch_id == batch_id
        ]
        if not rows:
            return None
        counts: dict[str, int] = {}
        errors: list[str] = []
        for row in rows:
            counts[row.status] = counts.get(row.status, 0) + 1
            if row.error:
                errors.append(row.error)
        return BatchProgress(
            batch_id=batch_id,
            total=len(rows),
            queued=counts.get("queued", 0),
            processing=counts.get("processing", 0),
            processed=counts.get("processed", 0),
            pending_review=counts.get("pending_review", 0),
            errors=tuple(sorted(set(errors))),
            created_at=min(row.created_at for row in rows),
        )

    async def batch_project(self, batch_id: str) -> str | None:
        projects = {row.project for row in self.rows.values() if row.batch_id == batch_id}
        return projects.pop() if len(projects) == 1 else None

    async def batch_items(self, project: str, batch_id: str) -> list[BatchItem]:
        return [
            BatchItem(name=row.path, sha256=row.sha256, status=row.status, attempts=row.attempts)
            for row in sorted(
                (
                    row
                    for row in self.rows.values()
                    if row.project == project and row.batch_id == batch_id
                ),
                key=lambda row: (row.path, row.sha256),
            )
        ]

    async def purge_source(self, device_id: str, source_id: str) -> dict[str, int]:
        doomed = [
            key
            for key, row in self.rows.items()
            if (row.device_id, row.source_id) == (device_id, source_id)
        ]
        counts: dict[str, int] = {}
        for key in doomed:
            status = self.rows[key].status
            counts[status] = counts.get(status, 0) + 1
            del self.rows[key]
        return counts

    async def trim(self, *, before: datetime) -> int:
        doomed = [
            key
            for key, row in self.rows.items()
            if row.status == "processed"
            and row.processed_at is not None
            and row.processed_at < before
        ]
        for key in doomed:
            del self.rows[key]
        return len(doomed)

    async def close(self) -> None:
        return None


# -- PostgreSQL 实现 ------------------------------------------------------


class PostgresQueue:
    """表 `ingest_queue` 的实现；复用 `PostgresStore` 的 engine 与会话工厂。

    迁移由 `PostgresStore.migrate()` 统一执行（同一张运行态库），这里不再单独建表。
    """

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def _known(self, session: AsyncSession, shas: Sequence[str]) -> dict[str, set[str]]:
        if not shas:
            return {}
        rows = await session.execute(
            select(IngestQueue.sha256, IngestQueue.project).where(
                IngestQueue.sha256.in_(list(set(shas)))
            )
        )
        known: dict[str, set[str]] = {}
        for sha, project in rows.all():
            known.setdefault(str(sha), set()).add(str(project))
        return known

    async def check(self, request: IngestRequest, *, producer: Producer, limit: int) -> EnqueuePlan:
        project = project_for(request, producer)
        async with self.sessions() as session:
            known = await self._known(session, [f.sha256 for f in request.files])
            used = await self._pending_bytes(session)
        return _plan(
            request,
            project=project,
            producer=producer,
            known_projects=known,
            used=used,
            limit=limit,
        )

    async def enqueue(
        self, request: IngestRequest, *, producer: Producer, limit: int
    ) -> EnqueueOutcome:
        project = project_for(request, producer)
        async with self.sessions() as session, session.begin():
            # 同一目标的入队串行化：配额判断与插入之间不能插入另一笔写入。
            await session.execute(
                select(
                    func.pg_advisory_xact_lock(func.hashtextextended(f"ingest_queue:{project}", 0))
                )
            )
            known = await self._known(session, [f.sha256 for f in request.files])
            used = await self._pending_bytes(session)
            plan = _plan(
                request,
                project=project,
                producer=producer,
                known_projects=known,
                used=used,
                limit=limit,
            )
            if not plan.entries:
                return EnqueueOutcome(accepted=0, duplicates=len(request.files), queued=0)
            inserted = (
                await session.scalars(
                    pg_insert(IngestQueue)
                    .values(
                        [
                            {
                                "project": entry.project,
                                "sha256": entry.sha256,
                                "device_id": entry.device_id,
                                "source_id": entry.source_id,
                                "source_type": entry.source_type,
                                "batch_id": entry.batch_id,
                                "path": entry.path,
                                "from_offset": entry.from_offset,
                                "to_offset": entry.to_offset,
                                "mtime": entry.mtime,
                                "producer": entry.producer,
                                "bytes": len(entry.content.encode("utf-8")),
                                "status": "queued",
                            }
                            for entry in plan.entries
                        ]
                    )
                    .on_conflict_do_nothing(
                        index_elements=[IngestQueue.project, IngestQueue.sha256]
                    )
                    .returning(IngestQueue.sha256)
                )
            ).all()
        queued = len(inserted)
        return EnqueueOutcome(
            accepted=queued, duplicates=len(request.files) - queued, queued=queued
        )

    async def claim(self, *, limit: int = 20, lease: timedelta = DEFAULT_LEASE) -> list[QueueTask]:
        now = datetime.now(UTC)
        cutoff = now - lease
        async with self.sessions() as session, session.begin():
            # 崩溃/被杀掉的 worker 留下的 processing 行，租约过后自动回到队列。
            await session.execute(
                update(IngestQueue)
                .where(
                    IngestQueue.status == "processing",
                    or_(
                        IngestQueue.claimed_at.is_(None),
                        IngestQueue.claimed_at < cutoff,
                    ),
                )
                .values(status="queued", claimed_at=None)
                .execution_options(synchronize_session=False)
            )
            rows = (
                await session.scalars(
                    select(IngestQueue)
                    .where(IngestQueue.status == "queued")
                    .order_by(IngestQueue.created_at, IngestQueue.sha256)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            ).all()
            for row in rows:
                row.status = "processing"
                row.claimed_at = now
                row.attempts += 1
        return [
            _task_from_columns(
                project=row.project,
                sha256=row.sha256,
                device_id=row.device_id,
                source_id=row.source_id,
                source_type=row.source_type,
                batch_id=row.batch_id,
                path=row.path,
                from_offset=row.from_offset,
                to_offset=row.to_offset,
                mtime=row.mtime,
                producer=row.producer,
                size=row.bytes,
                attempts=row.attempts,
                claimed_at=row.claimed_at,
            )
            for row in rows
        ]

    async def _finish(
        self,
        task: QueueTask,
        values: dict[str, Any],
        *,
        expect_processing: bool = True,
    ) -> int:
        stmt = (
            update(IngestQueue)
            .where(
                IngestQueue.project == task.project,
                IngestQueue.sha256 == task.sha256,
            )
            .values(**values)
            .execution_options(synchronize_session=False)
        )
        if expect_processing:
            stmt = stmt.where(IngestQueue.status == "processing")
        async with self.sessions() as session, session.begin():
            outcome = await session.execute(stmt)
        return int(cast(CursorResult[Any], outcome).rowcount)

    async def complete(self, task: QueueTask) -> None:
        await self._finish(
            task,
            {
                "status": "processed",
                "processed_at": datetime.now(UTC),
                "claimed_at": None,
                "error": None,
            },
        )

    async def retry(
        self,
        task: QueueTask,
        error: str,
        *,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    ) -> TaskStatus:
        status: TaskStatus = "pending_review" if task.attempts >= max_attempts else "queued"
        await self._finish(
            task,
            {"status": status, "claimed_at": None, "error": error[:ERROR_LIMIT]},
        )
        return status

    async def review(self, task: QueueTask, error: str) -> None:
        await self._finish(
            task,
            {
                "status": "pending_review",
                "claimed_at": None,
                "error": error[:ERROR_LIMIT],
            },
        )

    async def release(self, task: QueueTask) -> None:
        await self._finish(
            task,
            {
                "status": "queued",
                "claimed_at": None,
                "attempts": func.greatest(IngestQueue.attempts - 1, 0),
            },
        )

    async def _pending_bytes(self, session: AsyncSession) -> int:
        value = await session.scalar(
            select(func.coalesce(func.sum(IngestQueue.bytes), 0)).where(
                IngestQueue.status.in_(["queued", "processing"])
            )
        )
        return int(value or 0)

    async def pending_bytes(self) -> int:
        async with self.sessions() as session:
            return await self._pending_bytes(session)

    async def batch_progress(self, project: str, batch_id: str) -> BatchProgress | None:
        async with self.sessions() as session:
            rows = (
                await session.execute(
                    select(
                        IngestQueue.status,
                        func.count(),
                        func.min(IngestQueue.error),
                        func.min(IngestQueue.created_at),
                    )
                    .where(
                        IngestQueue.project == project,
                        IngestQueue.batch_id == batch_id,
                    )
                    .group_by(IngestQueue.status)
                )
            ).all()
        if not rows:
            return None
        counts = {str(status): int(count) for status, count, _, _ in rows}
        errors = sorted({str(error) for _, _, error, _ in rows if error})
        created = [stamp for _, _, _, stamp in rows if stamp is not None]
        return BatchProgress(
            batch_id=batch_id,
            total=sum(counts.values()),
            queued=counts.get("queued", 0),
            processing=counts.get("processing", 0),
            processed=counts.get("processed", 0),
            pending_review=counts.get("pending_review", 0),
            errors=tuple(errors),
            created_at=min(created) if created else None,
        )

    async def batch_project(self, batch_id: str) -> str | None:
        async with self.sessions() as session:
            rows = (
                await session.scalars(
                    select(IngestQueue.project)
                    .where(IngestQueue.batch_id == batch_id)
                    .distinct()
                    .limit(2)
                )
            ).all()
        return str(rows[0]) if len(rows) == 1 else None

    async def batch_items(self, project: str, batch_id: str) -> list[BatchItem]:
        async with self.sessions() as session:
            rows = (
                await session.execute(
                    select(
                        IngestQueue.path,
                        IngestQueue.sha256,
                        IngestQueue.status,
                        IngestQueue.attempts,
                    )
                    .where(
                        IngestQueue.project == project,
                        IngestQueue.batch_id == batch_id,
                    )
                    .order_by(IngestQueue.path, IngestQueue.sha256)
                )
            ).all()
        return [
            BatchItem(
                name=str(path),
                sha256=str(sha),
                status=cast(TaskStatus, str(status)),
                attempts=int(attempts),
            )
            for path, sha, status, attempts in rows
        ]

    async def purge_source(self, device_id: str, source_id: str) -> dict[str, int]:
        async with self.sessions() as session, session.begin():
            rows = (
                await session.execute(
                    select(IngestQueue.status, func.count())
                    .where(
                        IngestQueue.device_id == device_id,
                        IngestQueue.source_id == source_id,
                    )
                    .group_by(IngestQueue.status)
                )
            ).all()
            await session.execute(
                delete(IngestQueue).where(
                    IngestQueue.device_id == device_id,
                    IngestQueue.source_id == source_id,
                )
            )
        return {str(status): int(count) for status, count in rows}

    async def trim(self, *, before: datetime) -> int:
        async with self.sessions() as session, session.begin():
            outcome = await session.execute(
                delete(IngestQueue).where(
                    IngestQueue.status == "processed",
                    IngestQueue.processed_at.is_not(None),
                    IngestQueue.processed_at < before,
                )
            )
        return int(cast(CursorResult[Any], outcome).rowcount)

    async def close(self) -> None:
        # engine 归 PostgresStore 所有，避免两处 dispose 同一个连接池。
        return None


__all__ = [
    "DEFAULT_LEASE",
    "DEFAULT_MAX_ATTEMPTS",
    "BatchItem",
    "BatchProgress",
    "EnqueueOutcome",
    "EnqueuePlan",
    "MemoryQueue",
    "PostgresQueue",
    "QueueStore",
    "QueueTask",
    "QuotaExceeded",
    "TaskStatus",
    "project_for",
]
