"""`kb_*` 表的存储层：替代 markdown 文件读写（ADR-0013，规格 §3/§7）。

接口形状与 `store.KnowledgeStore` 平行（`write_scope` / `guard_write` / `write` /
`archive_node` / `list_trash` / `restore_node` / `replace_out_edges` / `remove_nodes_edges`
/ `commit`），调用方（manage/candidates/query）按需切换；差异只在语义：

- 一次写操作 = 一个事务（`write_scope` 用 ContextVar 复用同一 session），并在
  同一事务内追加 `kb_node_revisions`；
- `revision` 每次写入重新生成（16 位小写 hex），不再是文件 sha256；
- 「库存在」= `kb_projects` 有登记行且 `archived_at is null`，不再看目录；
- 回收站 = `kb_nodes.archived_at` + `kb_node_revisions` 的删除快照（规格 §3.2）；
- 边端点不加外键，悬空边原样保留；去重键 `(source, predicate, target)`；
- 跨进程写锁由 PG 事务级 advisory lock 承担，`busy` / `pending` 语义与文件版对齐。

所有语句由 ORM/Core 构造，不写裸 SQL（ADR-0005）。
"""

from __future__ import annotations

import json
import re
import secrets
import uuid
from collections.abc import AsyncIterator, Callable, Iterable, Mapping
from contextlib import asynccontextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import CursorResult, delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from memhub.contract import Edge, NodeFrontmatter, Predicate, valid_project
from memhub.kb.errors import (
    ConflictError,
    InvalidError,
    NodeMissing,
    NotFoundError,
    ProjectMissing,
    RevisionConflict,
    TargetUnavailable,
    WriteDeferred,
)
from memhub.kb.memory import (
    CandidateReason,
    CandidateWrite,
    EvidenceRef,
    MemoryPlan,
    normalize_memory_slug,
)
from memhub.kb.models import (
    KbArchive,
    KbEdge,
    KbMcpTrace,
    KbMemoryCandidate,
    KbMemoryEntry,
    KbMemoryRevision,
    KbMemorySnapshot,
    KbNode,
    KbNodeRevision,
    KbProject,
    KbWriteAudit,
)
from memhub.kb.store import TrashEntry
from memhub.mcp.trace import TraceEntry

REVISION_RE = re.compile(r"^[0-9a-f]{16}$")
_PROJECT_SEP = "/"
_TRASH_STAMP = "%Y%m%dT%H%M%S%f"
# 写锁的 advisory 键：全局单写者，与文件版一把锁的语义一致。
_WRITE_LOCK_KEY = 0x6B62_5F77_7269_7465


def new_revision() -> str:
    """16 位小写十六进制；8 字节随机足够，契约只要格式与唯一性。"""
    return secrets.token_hex(8)


def _now() -> datetime:
    return datetime.now(UTC)


def _snapshot(
    node: NodeFrontmatter, body: str, *, archived_at: datetime | None = None
) -> dict[str, Any]:
    """完整快照（含正文），供 `kb_node_revisions` 精确回滚与回收站取元数据。"""
    data = node.model_dump(mode="json")
    data["body"] = body
    data["archived_at"] = archived_at.isoformat() if archived_at else None
    return data


def _row_from(node: NodeFrontmatter, node_id: str, body: str, revision: str) -> dict[str, Any]:
    data = node.model_dump(mode="json")
    return {
        "id": node_id,
        "project": data["project"],
        "kind": data["kind"],
        "entity_kind": data.get("entity_kind"),
        "title": data["title"],
        "tier": data["tier"],
        "confidence": data.get("confidence"),
        "tags": data.get("tags") or [],
        "body": body,
        "source": data.get("source") or [],
        "valid_from": data.get("valid_from"),
        "valid_until": data.get("valid_until"),
        "supersedes": data.get("supersedes") or [],
        "superseded_by": data.get("superseded_by"),
        "deprecated_reason": data.get("deprecated_reason"),
        "occurred_at": data.get("occurred_at"),
        "decided_at": data.get("decided_at"),
        "status": data.get("status"),
        "created_at": data["created_at"],
        "updated_at": data["updated_at"],
        "revision": revision,
    }


def _node_from_row(row: KbNode) -> NodeFrontmatter:
    return NodeFrontmatter.model_validate(
        {
            "id": row.id,
            "project": row.project,
            "kind": row.kind,
            "entity_kind": row.entity_kind,
            "title": row.title,
            "tier": row.tier,
            "confidence": row.confidence,
            "tags": list(row.tags),
            "source": list(row.source),
            "created_at": row.created_at,
            "updated_at": row.updated_at,
            "valid_from": row.valid_from,
            "valid_until": row.valid_until,
            "supersedes": list(row.supersedes),
            "superseded_by": row.superseded_by,
            "deprecated_reason": row.deprecated_reason,
            "occurred_at": row.occurred_at,
            "decided_at": row.decided_at,
            "status": row.status,
        }
    )


def _stamp(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime(_TRASH_STAMP)


def _memory_entry_snapshot(row: KbMemoryEntry) -> dict[str, Any]:
    """条目对外形状；时间转 ISO 字符串，供 API 与 JSONB 快照共用。"""
    return {
        "slug": row.slug,
        "title": row.title,
        "conclusion": row.conclusion,
        "boundary": row.boundary,
        "invalidation": row.invalidation,
        "evidence": list(row.evidence or []),
        "confidence": row.confidence,
        "status": row.status,
        "deprecated_reason": row.deprecated_reason,
        "superseded_by": row.superseded_by,
        "contradicts": list(row.contradicts or []),
        "revision": row.revision,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def _memory_snapshot_snapshot(row: KbMemorySnapshot) -> dict[str, Any]:
    return {
        "version": row.version,
        "status": row.status,
        "entries": list(row.entries or []),
        "item_count": row.item_count,
        "note": row.note,
        "actor": row.actor,
        "created_at": row.created_at.isoformat(),
        "published_at": row.published_at.isoformat() if row.published_at else None,
    }


def _candidate_snapshot(row: KbMemoryCandidate) -> dict[str, Any]:
    return {
        "id": row.id,
        "slug": row.slug,
        "title": row.title,
        "conclusion": row.conclusion,
        "boundary": row.boundary,
        "invalidation": row.invalidation,
        "evidence": list(row.evidence or []),
        "confidence": row.confidence,
        "session_count": row.session_count,
        "project_count": row.project_count,
        "status": row.status,
        "reason": row.reason,
        "contradicts": list(row.contradicts or []),
        "first_seen_at": row.first_seen_at.isoformat(),
        "last_seen_at": row.last_seen_at.isoformat(),
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def _evidence_keys(value: object) -> frozenset[tuple[str, str | None]]:
    """证据去重键集合；聚合计划重校验用它确认条目证据没有被别人改过。"""
    if not isinstance(value, list):
        return frozenset()
    keys: set[tuple[str, str | None]] = set()
    for item in value:
        if not isinstance(item, Mapping):
            continue
        node_id = item.get("node_id")
        if not isinstance(node_id, str):
            continue
        session = item.get("session")
        keys.add((node_id, session if isinstance(session, str) else None))
    return frozenset(keys)


class PgKnowledgeStore:
    """`kb_*` 的异步存储实现；`sessions` 由 `session.create_sessionmaker` 提供。"""

    resolve_short_aliases = True

    def __init__(
        self, sessions: async_sessionmaker[AsyncSession], *, engine: AsyncEngine | None = None
    ) -> None:
        self.sessions = sessions
        self._engine = engine
        self._scope: ContextVar[AsyncSession | None] = ContextVar(
            f"kb_pg_scope_{id(self)}", default=None
        )

    @property
    def engine(self) -> AsyncEngine | None:
        """运行入口持有的引擎；测试注入的 store 没有所有权。"""
        return self._engine

    async def aclose(self) -> None:
        """释放连接池；幂等，供入口停机与测试收尾共用。"""
        engine, self._engine = self._engine, None
        if engine is not None:
            await engine.dispose()

    # -- 事务作用域 ------------------------------------------------------

    @asynccontextmanager
    async def _session(self) -> AsyncIterator[AsyncSession]:
        """在作用域内复用同一事务；否则自开事务并提交。"""
        scoped = self._scope.get()
        if scoped is not None:
            yield scoped
            return
        async with self.sessions() as session, session.begin():
            yield session

    @asynccontextmanager
    async def write_scope(
        self, *, timeout: float = 10.0, recovery: bool = False
    ) -> AsyncIterator[None]:
        """一次写操作 = 一个事务；用事务级 advisory lock 表达单写者。

        `recovery=True` 用于归档恢复：跳过 `pending` 阻断，与文件版一致。
        """
        scoped = self._scope.get()
        if scoped is not None:
            yield
            return

        async with self.sessions() as session:
            token = self._scope.set(session)
            try:
                async with session.begin():
                    await self._acquire_write_lock(session, timeout=timeout)
                    if not recovery:
                        pending = await session.scalar(
                            select(KbArchive.archive_id).where(KbArchive.status == "pending")
                        )
                        if pending is not None:
                            raise WriteDeferred(
                                "有未恢复的知识库归档事务，暂不能写入真源", reason="pending"
                            )
                    yield
            finally:
                self._scope.reset(token)

    async def _acquire_write_lock(self, session: AsyncSession, *, timeout: float) -> None:
        import anyio

        deadline = None if timeout is None else timeout
        waited = 0.0
        while True:
            acquired = await session.scalar(select(func.pg_try_advisory_xact_lock(_WRITE_LOCK_KEY)))
            if acquired:
                return
            if deadline is not None and waited >= deadline:
                raise WriteDeferred(
                    "真源正被其他进程写入（worker 或另一个管理端请求），稍后重试",
                    reason="busy",
                )
            step = 0.05
            if deadline is not None:
                step = min(step, max(deadline - waited, 0))
            await anyio.sleep(step)
            waited += step

    # -- 知识库登记 ------------------------------------------------------
    async def register_project(
        self, project_id: str, *, name: str = "", description: str = ""
    ) -> str:
        """登记或更新知识库；返回新的元数据 revision。"""
        revision = new_revision()
        now = _now()
        stmt = (
            pg_insert(KbProject)
            .values(
                id=project_id,
                name=name or project_id,
                description=description,
                revision=revision,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_update(
                index_elements=[KbProject.id],
                set_={
                    "name": name or project_id,
                    "description": description,
                    "revision": revision,
                    "updated_at": now,
                    "archived_at": None,
                },
            )
        )
        async with self._session() as session:
            await session.execute(stmt)
        return revision

    async def project_exists(self, project_id: str) -> bool:
        """已登记且活动；「目录存在」不再是判据。"""
        async with self._session() as session:
            stmt = select(KbProject.id).where(
                KbProject.id == project_id, KbProject.archived_at.is_(None)
            )
            return await session.scalar(stmt) is not None

    async def require_project(self, project_id: str) -> None:
        """未登记或已归档 → `ProjectMissing`；与文件版「不隐式建库」同义。"""
        if not await self.project_exists(project_id):
            raise ProjectMissing(f"知识库不存在或已归档：{project_id}")

    async def guard_write(self, project: str) -> None:
        """项目可写：已登记；已归档则抛 `WriteDeferred(reason="archived")`。"""
        if not valid_project(project):
            raise InvalidError(f"project 不合法: {project!r}")
        async with self._session() as session:
            row = await session.get(KbProject, project)
        if row is None:
            raise ProjectMissing(f"知识库不存在或已归档：{project}")
        if row.archived_at is not None:
            raise WriteDeferred(f"知识库 {project} 已归档，恢复后才能写入", reason="archived")

    async def project_status(self, project: str) -> str:
        """登记状态：`active` / `unregistered` / `inactive`（与文件版同口径）。

        归档事务未完成（`kb_archives.status == "pending"`）时抛 `TargetUnavailable`。
        """
        if not valid_project(project):
            return "invalid"
        async with self._session() as session:
            pending = await session.scalar(
                select(KbArchive.archive_id).where(KbArchive.status == "pending")
            )
            if pending is not None:
                raise TargetUnavailable("有未恢复的知识库归档事务，无法确认目标状态")
            row = await session.get(KbProject, project)
        if row is None:
            return "unregistered"
        return "inactive" if row.archived_at is not None else "active"

    def scoped_reader(self, projects: frozenset[str] | None) -> Any:
        """按授权范围读取的视图；活动性来自 `kb_projects`。"""
        from memhub.kb.reader import ScopedReader

        return ScopedReader(self, projects)

    async def archive_project(self, project_id: str) -> None:
        async with self._session() as session:
            project = await session.get(KbProject, project_id, with_for_update=True)
            if project is None:
                raise ProjectMissing(f"知识库未登记：{project_id}")
            project.archived_at = _now()
            project.revision = new_revision()
            project.updated_at = _now()

    # -- 节点 -----------------------------------------------------------
    async def exists(self, node_id: str) -> bool:
        async with self._session() as session:
            stmt = select(KbNode.id).where(KbNode.id == node_id, KbNode.archived_at.is_(None))
            return await session.scalar(stmt) is not None

    async def revision(self, node_id: str) -> str | None:
        """当前 revision；节点不存在或已软删返回 None（调用方据此报 404）。"""
        async with self._session() as session:
            stmt = select(KbNode.revision).where(KbNode.id == node_id, KbNode.archived_at.is_(None))
            return cast("str | None", await session.scalar(stmt))

    async def creating_actor(self, node_id: str) -> str | None:
        """创建者标记：`kb_node_revisions` 最早一条修订的 actor（ADR-0014）。

        没有修订历史（历史直写行）返回 None，视为不可归属。
        """
        async with self._session() as session:
            stmt = (
                select(KbNodeRevision.actor)
                .where(KbNodeRevision.node_id == node_id)
                .order_by(KbNodeRevision.created_at.asc(), KbNodeRevision.id.asc())
                .limit(1)
            )
            return cast("str | None", await session.scalar(stmt))

    async def read(self, node_id: str) -> tuple[NodeFrontmatter, str]:
        async with self._session() as session:
            row = await session.get(KbNode, node_id)
            if row is None or row.archived_at is not None:
                raise NodeMissing(f"节点不存在: {node_id}")
            return _node_from_row(row), row.body

    async def write(
        self,
        node_id: str,
        node: NodeFrontmatter,
        body: str,
        *,
        actor: str | None = None,
        reason: str | None = None,
        expected_revision: str | None = None,
    ) -> str:
        """写入节点并追加修订历史；返回新 revision。

        `node.id` 与 `node_id` 必须一致，项目段必须已登记且活动——与文件版
        「不隐式建库」一致，不做兜底创建。

        `expected_revision` 非空时走乐观锁（规格 §7）：行锁内比对当前 revision，
        不一致抛 `RevisionConflict`，不覆盖后来者的写入。
        """
        project = node_id.split(_PROJECT_SEP, 1)[0]
        if node_id != node.id:
            raise ValueError(f"node.id 与目标 id 不一致：{node.id} != {node_id}")
        if not project or project == node_id:
            raise ProjectMissing(f"节点 id 缺少项目段：{node_id}")

        revision = new_revision()
        values = _row_from(node, node_id, body, revision)
        async with self._session() as session:
            active = await session.scalar(
                select(KbProject.id).where(KbProject.id == project, KbProject.archived_at.is_(None))
            )
            if active is None:
                raise ProjectMissing(f"知识库不存在或已归档：{project}")

            existing = await session.get(KbNode, node_id, with_for_update=True)
            current = None if existing is None or existing.archived_at else existing.revision
            if expected_revision is not None and current != expected_revision:
                # 行锁已拿到，此刻读到的是最新已提交值；不覆盖后来者的写入。
                raise RevisionConflict(node_id, expected=expected_revision, current=current)
            before = (
                _snapshot(_node_from_row(existing), existing.body, archived_at=existing.archived_at)
                if existing is not None
                else {}
            )
            await session.execute(
                pg_insert(KbNode)
                .values(**values)
                .on_conflict_do_update(
                    index_elements=[KbNode.id],
                    set_={k: v for k, v in values.items() if k != "id"} | {"archived_at": None},
                )
            )
            session.add(
                KbNodeRevision(
                    node_id=node_id,
                    revision=revision,
                    tier=str(node.tier),
                    actor=actor,
                    reason=reason,
                    before=before,
                    after=_snapshot(node, body),
                    created_at=_now(),
                )
            )
        return revision

    async def list_ids(self, project: str | None = None) -> list[str]:
        async with self._session() as session:
            stmt = select(KbNode.id).where(KbNode.archived_at.is_(None))
            if project is not None:
                stmt = stmt.where(KbNode.project == project)
            ids = list(await session.scalars(stmt))
        return sorted(ids)

    # -- 软删与回收站 ----------------------------------------------------

    async def archive_node(
        self,
        node_id: str,
        *,
        expected_revision: str | None = None,
        reason: str = "",
        actor: str = "ui",
    ) -> dict[str, Any]:
        """软删：置 `archived_at`，写一条带正文的删除快照，并摘掉相连的边。"""
        async with self._session() as session:
            row = await session.get(KbNode, node_id, with_for_update=True)
            if row is None or row.archived_at is not None:
                raise NodeMissing(f"节点不存在: {node_id}")
            if expected_revision is not None and row.revision != expected_revision:
                raise RevisionConflict(node_id, expected=expected_revision, current=row.revision)
            node = _node_from_row(row)
            body = row.body
            moment = _now()
            row.archived_at = moment
            removed = await self._remove_incident_edges(session, node_id)
            session.add(
                KbNodeRevision(
                    node_id=node_id,
                    revision=row.revision,
                    tier=row.tier,
                    actor=actor,
                    reason=reason,
                    before=_snapshot(node, body),
                    after=_snapshot(node, body, archived_at=moment),
                    created_at=moment,
                )
            )
        return {"trash": f"{_stamp(moment)}/{node_id}", "removed_edges": removed}

    async def list_trash(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        project: str | None = None,
        q: str | None = None,
    ) -> dict[str, Any]:
        """回收站：`archived_at` 非空的节点 + 最近一条删除快照的 reason/actor。

        整库归档一并软删的节点不属于回收站条目（文件版归档时整个目录被移出活跃树），
        归档前就单独软删的节点仍保留，恢复整库后照旧可见。
        """
        async with self._session() as session:
            rows = list(
                (await session.scalars(select(KbNode).where(KbNode.archived_at.is_not(None)))).all()
            )
            archived_projects = {
                row.id: row.archived_at
                for row in (
                    await session.scalars(
                        select(KbProject).where(KbProject.archived_at.is_not(None))
                    )
                ).all()
            }
            rows = [
                row
                for row in rows
                if (archived_at := archived_projects.get(row.project)) is None
                or row.archived_at is None
                or row.archived_at < archived_at
            ]
            deletions: dict[str, KbNodeRevision] = {}
            if rows:
                revisions = (
                    await session.scalars(
                        select(KbNodeRevision)
                        .where(KbNodeRevision.node_id.in_([row.id for row in rows]))
                        .order_by(KbNodeRevision.id)
                    )
                ).all()
                for revision in revisions:
                    if revision.after.get("archived_at"):
                        deletions[revision.node_id] = revision
            items: list[TrashEntry] = []
            for row in rows:
                deleted = deletions.get(row.id)
                moment = row.archived_at or _now()
                items.append(
                    TrashEntry(
                        id=row.id,
                        title=row.title,
                        kind=row.kind,
                        project=row.project,
                        deleted_at=moment.isoformat(),
                        reason=(deleted.reason if deleted else "") or "",
                        actor=(deleted.actor if deleted else "") or "",
                        trash=f"{_stamp(moment)}/{row.id}",
                    )
                )
        items.sort(key=lambda item: (item.deleted_at, item.id), reverse=True)
        total_all = len(items)
        if project:
            items = [item for item in items if item.project == project]
        if q:
            needle = q.casefold()
            items = [
                item
                for item in items
                if needle in item.title.casefold() or needle in item.id.casefold()
            ]
        offset = max(0, offset)
        page = [item.as_dict() for item in items[offset : offset + max(1, min(limit, 500))]]
        return {"items": page, "total": len(items), "offset": offset, "total_all": total_all}

    async def restore_node(self, trash: str) -> dict[str, Any]:
        """按 `stamp/node_id` 恢复软删节点；节点已被重建则抛 `FileExistsError`。"""
        parts = trash.split("/")
        if len(parts) < 2 or any(part in {"", ".", ".."} or "\\" in part for part in parts):
            raise ValueError(f"trash 路径不合法: {trash!r}")
        stamp = parts[0]
        node_id = "/".join(parts[1:])
        async with self._session() as session:
            row = await session.get(KbNode, node_id, with_for_update=True)
            if row is None:
                raise NodeMissing(f"回收站里没有: {trash}")
            if row.archived_at is None:
                raise FileExistsError(f"节点已重新存在，无法恢复: {node_id}")
            if _stamp(row.archived_at) != stamp:
                raise NodeMissing(f"回收站里没有: {trash}")
            if not await session.scalar(
                select(KbProject.id).where(
                    KbProject.id == row.project, KbProject.archived_at.is_(None)
                )
            ):
                raise ProjectMissing(f"知识库不存在或已归档：{row.project}")
            node = _node_from_row(row)
            body = row.body
            before = _snapshot(node, body, archived_at=row.archived_at)
            revision = new_revision()
            row.archived_at = None
            row.revision = revision
            row.updated_at = _now()
            session.add(
                KbNodeRevision(
                    node_id=node_id,
                    revision=revision,
                    tier=row.tier,
                    actor=None,
                    reason="restore",
                    before=before,
                    after=_snapshot(node, body),
                    created_at=_now(),
                )
            )
        return {"id": node_id, "revision": revision}

    # -- 边 -------------------------------------------------------------
    async def edges(self, project: str | None = None) -> list[dict[str, Any]]:
        async with self._session() as session:
            stmt = select(KbEdge).order_by(KbEdge.id)
            if project is not None:
                stmt = stmt.where(KbEdge.project == project)
            rows = (await session.scalars(stmt)).all()
            return [
                {
                    "source": row.source,
                    "predicate": row.predicate,
                    "target": row.target,
                    "source_doc": row.source_doc,
                }
                for row in rows
            ]

    async def edge_lines(self) -> AsyncIterator[str]:
        """与文件版同形：一行一个 JSON 对象，供 `query.edge_index` 直接消费。"""
        for record in await self.edges():
            yield json.dumps(record, ensure_ascii=False)

    async def append_edges(
        self,
        project: str,
        edges: Iterable[Edge | dict[str, Any]],
        source_doc: str | None = None,
    ) -> int:
        """按 `(source, predicate, target)` 去重追加；返回新增条数。"""
        async with self._session() as session:
            if (
                await session.scalar(
                    select(KbProject.id).where(
                        KbProject.id == project, KbProject.archived_at.is_(None)
                    )
                )
                is None
            ):
                raise ProjectMissing(f"知识库不存在或已归档：{project}")

            now = _now()
            rows: list[dict[str, Any]] = []
            for edge in edges:
                if isinstance(edge, Edge):
                    record = {
                        "source": edge.source,
                        "predicate": edge.predicate.value,
                        "target": edge.target,
                        "source_doc": edge.source_doc or source_doc,
                    }
                else:
                    record = {
                        "source": str(edge["source"]),
                        "predicate": str(
                            edge["predicate"].value
                            if isinstance(edge["predicate"], Predicate)
                            else edge["predicate"]
                        ),
                        "target": str(edge["target"]),
                        "source_doc": edge.get("source_doc") or source_doc,
                    }
                rows.append({**record, "project": project, "created_at": now})

            inserted = 0
            for values in rows:
                stmt = (
                    pg_insert(KbEdge)
                    .values(**values)
                    .on_conflict_do_nothing(
                        index_elements=[KbEdge.source, KbEdge.predicate, KbEdge.target]
                    )
                    .returning(KbEdge.id)
                )
                if await session.scalar(stmt) is not None:
                    inserted += 1
        return inserted

    async def remove_edges(self, project: str, *, source: str | None = None) -> int:
        """删除库内边；给 `source` 则只删该节点的出边（替换出边用）。"""
        stmt = delete(KbEdge).where(KbEdge.project == project)
        if source is not None:
            stmt = stmt.where(KbEdge.source == source)
        async with self._session() as session:
            result = await session.execute(stmt)
        return int(cast("CursorResult[Any]", result).rowcount or 0)

    async def replace_out_edges(self, node_id: str, edges: list[Edge]) -> int:
        """替换 node_id 的出边（按完整 id 或库内唯一 slug 解析）；入边不动。"""
        node, _ = await self.read(node_id)
        async with self._session() as session:
            await self._drop_out_edges(session, node_id)
        if not edges:
            return 0
        return await self.append_edges(node.project, edges, node_id)

    async def remove_nodes_edges(self, node_ids: set[str], *, drop_file: Any = None) -> int:
        """清理与给定节点相连的边；`drop_file` 只为与文件版同签名，PG 版忽略。"""
        async with self._session() as session:
            return await self._remove_nodes_edges(session, node_ids)

    async def _resolver(
        self,
        session: AsyncSession,
        *,
        include: str | set[str] | None = None,
        exclude: set[str] | None = None,
    ) -> Callable[[str], str | None]:
        ids = set(await session.scalars(select(KbNode.id).where(KbNode.archived_at.is_(None))))
        if exclude:
            ids -= exclude
        if include is not None:
            ids.update({include} if isinstance(include, str) else include)
        slug_index: dict[str, list[str]] = {}
        for node_id in ids:
            slug_index.setdefault(node_id.rsplit("/", 1)[-1], []).append(node_id)

        def resolve(reference: str) -> str | None:
            if reference in ids:
                return reference
            candidates = slug_index.get(reference, [])
            return candidates[0] if len(candidates) == 1 else None

        return resolve

    async def _remove_incident_edges(self, session: AsyncSession, node_id: str) -> int:
        resolve = await self._resolver(session, include=node_id)
        rows = (await session.scalars(select(KbEdge))).all()
        doomed = [
            row.id
            for row in rows
            if resolve(row.source) == node_id or resolve(row.target) == node_id
        ]
        if not doomed:
            return 0
        await session.execute(delete(KbEdge).where(KbEdge.id.in_(doomed)))
        return len(doomed)

    async def _drop_out_edges(self, session: AsyncSession, node_id: str) -> int:
        resolve = await self._resolver(session)
        rows = (await session.scalars(select(KbEdge))).all()
        doomed = [row.id for row in rows if resolve(row.source) == node_id]
        if not doomed:
            return 0
        await session.execute(delete(KbEdge).where(KbEdge.id.in_(doomed)))
        return len(doomed)

    async def _remove_nodes_edges(self, session: AsyncSession, node_ids: set[str]) -> int:
        resolve = await self._resolver(session, include=node_ids)
        rows = (await session.scalars(select(KbEdge))).all()
        doomed = [
            row.id
            for row in rows
            if resolve(row.source) in node_ids or resolve(row.target) in node_ids
        ]
        if not doomed:
            return 0
        await session.execute(delete(KbEdge).where(KbEdge.id.in_(doomed)))
        return len(doomed)

    # -- 知识库目录（catalog 的 PG 实现） --------------------------------

    async def _project_entry(self, session: AsyncSession, row: KbProject) -> dict[str, Any]:
        nodes = await session.scalar(
            select(func.count())
            .select_from(KbNode)
            .where(KbNode.project == row.id, KbNode.archived_at.is_(None))
        )
        edges = await session.scalar(
            select(func.count()).select_from(KbEdge).where(KbEdge.project == row.id)
        )
        updated = await session.scalar(
            select(func.max(KbNode.updated_at)).where(
                KbNode.project == row.id, KbNode.archived_at.is_(None)
            )
        )
        return {
            "id": row.id,
            "name": row.name,
            "description": row.description,
            "nodes": int(nodes or 0),
            "edges": int(edges or 0),
            "updated_at": updated.isoformat() if updated else None,
            "created_at": row.created_at.isoformat(),
        }

    async def list_projects(self) -> dict[str, Any]:
        """活动知识库清单；与文件版 `catalog.list_kbs` 同形。"""
        async with self._session() as session:
            rows = (
                await session.scalars(
                    select(KbProject).where(KbProject.archived_at.is_(None)).order_by(KbProject.id)
                )
            ).all()
            items = [await self._project_entry(session, row) for row in rows]
        return {"items": items, "total": len(items)}

    async def create_project(
        self, project_id: str, *, name: str = "", description: str = ""
    ) -> dict[str, Any]:
        """登记新库；已登记即冲突，已归档需先恢复（与文件版同口径）。"""
        async with self.write_scope():
            async with self._session() as session:
                row = await session.get(KbProject, project_id, with_for_update=True)
                if row is not None and row.archived_at is not None:
                    raise WriteDeferred(
                        f"知识库 {project_id} 已归档，恢复后才能写入", reason="archived"
                    )
                if row is not None:
                    raise ConflictError("知识库已存在", {"id": project_id})
                now = _now()
                row = KbProject(
                    id=project_id,
                    name=name.strip() or project_id,
                    description=description.strip(),
                    revision=new_revision(),
                    created_at=now,
                    updated_at=now,
                )
                session.add(row)
            return {
                "id": project_id,
                "name": row.name,
                "description": row.description,
                "created_at": row.created_at.isoformat(),
            }

    async def update_project(
        self,
        project_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        async with self.write_scope(), self._session() as session:
            row = await session.get(KbProject, project_id, with_for_update=True)
            if row is None or row.archived_at is not None:
                raise NotFoundError(f"知识库不存在: {project_id}")
            if name is not None:
                row.name = name.strip() or project_id
            if description is not None:
                row.description = description.strip()
            row.revision = new_revision()
            row.updated_at = _now()
            return {
                "id": row.id,
                "name": row.name,
                "description": row.description,
                "created_at": row.created_at.isoformat(),
            }

    async def list_archives(self) -> dict[str, Any]:
        """未恢复的整库归档；与文件版 `catalog.list_archives` 同形。"""
        from memhub.kb import archive

        async with self._session() as session:
            rows = (
                await session.scalars(
                    select(KbArchive)
                    .where(KbArchive.status == "active")
                    .order_by(KbArchive.created_at.desc())
                )
            ).all()
            items = []
            for row in rows:
                payload, _ = await archive.unpack_bundle(row.snapshot)
                try:
                    header = dict(payload["header"])
                    if header["archive_id"] != row.archive_id:
                        raise ValueError("archive_id")
                except (KeyError, TypeError, ValueError) as exc:
                    raise ConflictError(
                        "知识库归档快照损坏", {"archive_id": row.archive_id}
                    ) from exc
                items.append(header)
        return {"items": items, "total": len(items)}

    async def archive_project_kb(self, project_id: str, *, actor: str = "ui") -> dict[str, Any]:
        """整库归档：快照入库、节点软删、相连边删除、登记置归档（规格 §8.7）。

        一次事务完成，不产生 `pending` 中间态；`write_scope` 的 pending 检查保留，
        用于人工修复时识别残留行。
        """
        from memhub.kb import archive

        async with self.write_scope(), self._session() as session:
            project = await session.get(KbProject, project_id, with_for_update=True)
            if project is None or project.archived_at is not None:
                raise NotFoundError(f"知识库不存在: {project_id}")
            nodes = (
                await session.scalars(
                    select(KbNode)
                    .where(KbNode.project == project_id, KbNode.archived_at.is_(None))
                    .order_by(KbNode.id)
                )
            ).all()
            node_ids = {row.id for row in nodes}
            before = await self._resolver(session, include=node_ids)
            after = await self._resolver(session, exclude=node_ids)

            rows = (await session.scalars(select(KbEdge).order_by(KbEdge.id))).all()
            doomed: list[KbEdge] = []
            for row in rows:
                if row.project == project_id:
                    doomed.append(row)
                    continue
                endpoints = (before(row.source), before(row.target))
                if endpoints[0] in node_ids or endpoints[1] in node_ids:
                    doomed.append(row)
                    continue
                if endpoints != (after(row.source), after(row.target)):
                    raise ConflictError(
                        "归档会改变现有关系的短别名",
                        {"path": f"{row.project}/_edges.jsonl"},
                    )

            now = _now()
            archive_id = uuid.uuid4().hex
            header: dict[str, Any] = {
                "id": project_id,
                "archive_id": archive_id,
                "deleted_at": now.isoformat(),
                "name": project.name,
                "actor": actor,
                "archived_count": len(nodes),
                "removed_edges": len(doomed),
            }
            payload = {
                "header": header,
                "entry": {
                    "id": project.id,
                    "name": project.name,
                    "description": project.description,
                    "created_at": project.created_at.isoformat(),
                },
                "nodes": [
                    {
                        "node": _node_from_row(row).model_dump(mode="json"),
                        "body": row.body,
                    }
                    for row in nodes
                ],
                "edges": [
                    {
                        "project": row.project,
                        "source": row.source,
                        "predicate": row.predicate,
                        "target": row.target,
                        "source_doc": row.source_doc,
                    }
                    for row in doomed
                ],
            }
            snapshot = await archive.pack_bundle(payload, {})
            if doomed:
                await session.execute(
                    delete(KbEdge).where(KbEdge.id.in_([row.id for row in doomed]))
                )
            for node_row in nodes:
                node_row.archived_at = now
                node_row.revision = new_revision()
                node_row.updated_at = now
            project.archived_at = now
            project.revision = new_revision()
            project.updated_at = now
            session.add(
                KbArchive(
                    archive_id=archive_id,
                    project=project_id,
                    status="active",
                    snapshot=snapshot,
                    archived_count=len(nodes),
                    removed_edges=len(doomed),
                    actor=actor,
                    deleted_at=now,
                    created_at=now,
                )
            )
        return {**header, "commit": None}

    async def restore_project_kb(self, archive_id: str) -> dict[str, Any]:
        """恢复整库归档：节点取消软删、边补回、登记取消归档。

        只取消本次归档软删的节点；归档前已单独软删的节点保持软删。
        已被恢复过的归档（`status="restored"`）不再可恢复。
        """
        from memhub.kb import archive

        if not re.fullmatch(r"[0-9a-f]{32}", archive_id):
            raise NotFoundError("知识库归档不存在")
        async with self.write_scope(recovery=True), self._session() as session:
            row = await session.get(KbArchive, archive_id, with_for_update=True)
            if row is None or row.status != "active":
                raise NotFoundError("知识库归档不存在")
            payload, _ = await archive.unpack_bundle(row.snapshot)
            try:
                header = payload["header"]
                entry = payload["entry"]
                saved_nodes = payload["nodes"]
                saved_edges = payload["edges"]
                project_id = header["id"]
                if not isinstance(header, dict) or header["archive_id"] != archive_id:
                    raise ValueError("header")
                if not valid_project(project_id) or entry["id"] != project_id:
                    raise ValueError("entry")
            except (KeyError, TypeError, ValueError) as exc:
                raise ConflictError("知识库归档快照损坏") from exc

            restored_ids = {str(item["node"]["id"]) for item in saved_nodes}
            conflict = set(
                await session.scalars(
                    select(KbNode.id).where(
                        KbNode.id.in_(restored_ids), KbNode.archived_at.is_(None)
                    )
                )
            )
            if conflict:
                raise ConflictError("恢复目标已存在", {"ids": sorted(conflict)})

            project = await session.get(KbProject, project_id, with_for_update=True)
            if project is not None and project.archived_at is None:
                raise ConflictError("已存在同名库登记", {"id": project_id})

            before = await self._resolver(session)
            after = await self._resolver(session, include=restored_ids)
            saved_triples = {
                (edge["source"], edge["predicate"], edge["target"]) for edge in saved_edges
            }
            for edge in (await session.scalars(select(KbEdge))).all():
                if (edge.source, edge.predicate, edge.target) in saved_triples:
                    continue
                if (before(edge.source), before(edge.target)) != (
                    after(edge.source),
                    after(edge.target),
                ):
                    raise ConflictError(
                        "恢复会改变现有关系的短别名",
                        {"path": f"{edge.project}/_edges.jsonl"},
                    )

            now = _now()
            if project is None:
                project = KbProject(
                    id=project_id,
                    name=str(entry["name"]) or project_id,
                    description=str(entry["description"]),
                    revision=new_revision(),
                    created_at=now,
                    updated_at=now,
                )
                session.add(project)
            else:
                project.name = str(entry["name"]) or project_id
                project.description = str(entry["description"])
                project.archived_at = None
                project.revision = new_revision()
                project.updated_at = now

            for item in saved_nodes:
                node = NodeFrontmatter.model_validate(item["node"])
                values = _row_from(node, node.id, str(item["body"]), new_revision())
                values["archived_at"] = None
                await session.execute(
                    pg_insert(KbNode)
                    .values(**values)
                    .on_conflict_do_update(
                        index_elements=[KbNode.id],
                        set_={key: value for key, value in values.items() if key != "id"},
                    )
                )
                session.add(
                    KbNodeRevision(
                        node_id=node.id,
                        revision=values["revision"],
                        tier=str(node.tier),
                        actor="archive-restore",
                        reason="restore",
                        before={},
                        after=_snapshot(node, str(item["body"])),
                        created_at=now,
                    )
                )
            for edge in saved_edges:
                await session.execute(
                    pg_insert(KbEdge)
                    .values(
                        project=str(edge["project"]),
                        source=str(edge["source"]),
                        predicate=str(edge["predicate"]),
                        target=str(edge["target"]),
                        source_doc=edge.get("source_doc"),
                        created_at=now,
                    )
                    .on_conflict_do_nothing(
                        index_elements=[KbEdge.source, KbEdge.predicate, KbEdge.target]
                    )
                )
            row.status = "restored"
        return {
            "id": str(header["id"]),
            "archive_id": archive_id,
            "restored_count": int(header["archived_count"]),
            "restored_edges": int(header["removed_edges"]),
            "commit": None,
        }

    # -- 历史 ------------------------------------------------------------

    async def commit(self, message: str, *, node_path: str | None = None) -> None:
        """PG 版没有 git 提交：历史由 `kb_node_revisions` 承担（规格 §3.4）。"""
        return

    async def count(self) -> dict[str, int]:
        """storage 自检用的小计数；治理统计仍走 `manage.stats`。"""
        async with self._session() as session:
            nodes = await session.scalar(
                select(func.count()).select_from(KbNode).where(KbNode.archived_at.is_(None))
            )
            edges = await session.scalar(select(func.count()).select_from(KbEdge))
        return {"nodes": int(nodes or 0), "edges": int(edges or 0)}

    # -- 写入审计（规格 §3.6） --------------------------------------------

    async def record_write_audit(
        self,
        *,
        actor: str | None,
        project: str | None,
        node_id: str | None,
        action: str,
        result: str,
        memory_snapshot: int | None = None,
    ) -> None:
        """一条不含正文与 token 的写入审计；自成事务，写路径失败也不能吞掉它。

        审计写入失败按原样上抛：审计缺失必须显式失败，不能静默丢记录。
        `memory_snapshot` 记录本次会话抽取使用的记忆版本，不记录记忆正文。
        """
        async with self._session() as session:
            session.add(
                KbWriteAudit(
                    actor=actor,
                    project=project,
                    node_id=node_id,
                    action=action,
                    result=result,
                    memory_snapshot=memory_snapshot,
                    created_at=_now(),
                )
            )

    # -- 长期记忆（ADR-0016，规格 §3–§6） ----------------------------------

    async def create_memory(
        self,
        *,
        slug: str,
        title: str,
        conclusion: str,
        boundary: str = "",
        invalidation: str = "",
        confidence: float = 0.5,
        evidence: Iterable[EvidenceRef] = (),
        contradicts: Iterable[str] = (),
        actor: str | None = None,
        reason: str | None = None,
    ) -> dict[str, Any]:
        """新建 active 条目；slug 已存在即冲突，不覆盖人工或聚合结果。"""
        clean = normalize_memory_slug(slug)
        if not clean or clean != slug:
            raise InvalidError(f"记忆 slug 不合法：{slug!r}")
        now = _now()
        revision = new_revision()
        async with self.write_scope(), self._session() as session:
            if await session.get(KbMemoryEntry, clean) is not None:
                raise ConflictError("记忆条目已存在", {"slug": clean})
            row = KbMemoryEntry(
                slug=clean,
                title=title.strip(),
                conclusion=conclusion.strip(),
                boundary=boundary.strip(),
                invalidation=invalidation.strip(),
                evidence=[item.as_dict() for item in evidence],
                confidence=min(1.0, max(0.0, float(confidence))),
                status="active",
                contradicts=list(dict.fromkeys(contradicts)),
                revision=revision,
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            session.add(
                KbMemoryRevision(
                    slug=clean,
                    revision=revision,
                    actor=actor,
                    reason=reason,
                    before={},
                    after=_memory_entry_snapshot(row),
                    created_at=now,
                )
            )
            await session.flush()
            return _memory_entry_snapshot(row)

    async def update_memory(
        self,
        slug: str,
        *,
        expected_revision: str,
        patch: dict[str, Any],
        actor: str | None = None,
        reason: str | None = None,
    ) -> dict[str, Any]:
        """按乐观锁更新条目；只允许改内容字段，不改 status/deprecated_reason。"""
        allowed = {"title", "conclusion", "boundary", "invalidation", "confidence", "contradicts"}
        unknown = set(patch) - allowed
        if unknown:
            raise InvalidError("不允许更新这些字段", {"fields": sorted(unknown)})
        async with self.write_scope(), self._session() as session:
            row = await session.get(KbMemoryEntry, slug, with_for_update=True)
            if row is None:
                raise NotFoundError(f"记忆不存在: {slug}")
            if expected_revision != row.revision:
                raise RevisionConflict(slug, expected=expected_revision, current=row.revision)
            before = _memory_entry_snapshot(row)
            for key, value in patch.items():
                if key == "confidence":
                    row.confidence = min(1.0, max(0.0, float(value)))
                elif key == "contradicts":
                    row.contradicts = list(dict.fromkeys(str(item) for item in value))
                elif key in {"title", "conclusion"}:
                    setattr(row, key, str(value).strip())
                else:
                    setattr(row, key, str(value).strip())
            row.revision = new_revision()
            row.updated_at = _now()
            session.add(
                KbMemoryRevision(
                    slug=slug,
                    revision=row.revision,
                    actor=actor,
                    reason=reason,
                    before=before,
                    after=_memory_entry_snapshot(row),
                    created_at=row.updated_at,
                )
            )
            await session.flush()
            return _memory_entry_snapshot(row)

    async def deprecate_memory(
        self,
        slug: str,
        *,
        expected_revision: str,
        reason: str,
        superseded_by: str | None = None,
        actor: str | None = None,
    ) -> dict[str, Any]:
        """废弃条目：保留证据与修订，不物理删除，也不允许被聚合任务复活。"""
        async with self.write_scope(), self._session() as session:
            row = await session.get(KbMemoryEntry, slug, with_for_update=True)
            if row is None:
                raise NotFoundError(f"记忆不存在: {slug}")
            if expected_revision != row.revision:
                raise RevisionConflict(slug, expected=expected_revision, current=row.revision)
            if row.status != "active":
                raise ConflictError("记忆已废弃", {"slug": slug, "status": row.status})
            if superseded_by is not None:
                target = await session.get(KbMemoryEntry, superseded_by, with_for_update=True)
                if target is None or target.status != "active" or superseded_by == slug:
                    raise ConflictError(
                        "替代条目不存在或不是 active", {"superseded_by": superseded_by}
                    )
            before = _memory_entry_snapshot(row)
            row.status = "deprecated"
            row.deprecated_reason = reason.strip()
            row.superseded_by = superseded_by
            row.revision = new_revision()
            row.updated_at = _now()
            session.add(
                KbMemoryRevision(
                    slug=slug,
                    revision=row.revision,
                    actor=actor,
                    reason=reason,
                    before=before,
                    after=_memory_entry_snapshot(row),
                    created_at=row.updated_at,
                )
            )
            await session.flush()
            return _memory_entry_snapshot(row)

    async def get_memory(self, slug: str) -> dict[str, Any]:
        async with self._session() as session:
            row = await session.get(KbMemoryEntry, slug)
            if row is None:
                raise NotFoundError(f"记忆不存在: {slug}")
            return _memory_entry_snapshot(row)

    async def list_memories(
        self,
        *,
        status: str | None = None,
        q: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """条目列表；`status=all` 等价于不过滤。"""
        stmt = select(KbMemoryEntry)
        count = select(func.count()).select_from(KbMemoryEntry)
        if status and status != "all":
            stmt = stmt.where(KbMemoryEntry.status == status)
            count = count.where(KbMemoryEntry.status == status)
        if q:
            needle = f"%{q}%"
            condition = or_(
                KbMemoryEntry.title.ilike(needle), KbMemoryEntry.conclusion.ilike(needle)
            )
            stmt = stmt.where(condition)
            count = count.where(condition)
        limit = max(1, min(limit, 500))
        offset = max(0, offset)
        async with self._session() as session:
            total = int(await session.scalar(count) or 0)
            rows = (
                await session.scalars(
                    stmt.order_by(KbMemoryEntry.updated_at.desc(), KbMemoryEntry.slug)
                    .limit(limit)
                    .offset(offset)
                )
            ).all()
        return {
            "items": [_memory_entry_snapshot(row) for row in rows],
            "total": total,
            "offset": offset,
            "limit": limit,
        }

    async def memory_revisions(self, slug: str, *, limit: int = 20) -> list[dict[str, Any]]:
        """最近 `limit` 条修订，按时间正序返回（最早在前，便于比对前后值）。"""
        async with self._session() as session:
            rows = (
                await session.scalars(
                    select(KbMemoryRevision)
                    .where(KbMemoryRevision.slug == slug)
                    .order_by(KbMemoryRevision.created_at.desc(), KbMemoryRevision.id.desc())
                    .limit(max(1, min(limit, 100)))
                )
            ).all()
        return [
            {
                "id": row.id,
                "slug": row.slug,
                "revision": row.revision,
                "actor": row.actor,
                "reason": row.reason,
                "before": row.before,
                "after": row.after,
                "created_at": row.created_at.isoformat(),
            }
            for row in reversed(rows)
        ]

    async def upsert_memory_candidate(
        self, candidate: CandidateWrite, *, now: datetime | None = None
    ) -> None:
        """写入该 slug 的最新候选；`first_seen_at` 保留首次观察时间。"""
        moment = now or _now()
        values = {
            "slug": candidate.slug,
            "title": candidate.title,
            "conclusion": candidate.conclusion,
            "boundary": candidate.boundary,
            "invalidation": candidate.invalidation,
            "evidence": [item.as_dict() for item in candidate.evidence],
            "confidence": candidate.confidence,
            "session_count": candidate.session_count,
            "project_count": candidate.project_count,
            "status": candidate.status,
            "reason": candidate.reason,
            "contradicts": list(candidate.contradicts),
            "first_seen_at": moment,
            "last_seen_at": moment,
            "created_at": moment,
            "updated_at": moment,
        }
        stmt = (
            pg_insert(KbMemoryCandidate)
            .values(**values)
            .on_conflict_do_update(
                index_elements=[KbMemoryCandidate.slug],
                set_={
                    key: value
                    for key, value in values.items()
                    if key not in {"slug", "created_at", "first_seen_at"}
                },
            )
        )
        async with self.write_scope(), self._session() as session:
            await session.execute(stmt)

    async def list_memory_candidates(
        self, *, status: str | None = None, limit: int = 100
    ) -> dict[str, Any]:
        stmt = select(KbMemoryCandidate)
        if status and status != "all":
            stmt = stmt.where(KbMemoryCandidate.status == status)
        async with self._session() as session:
            rows = (
                await session.scalars(
                    stmt.order_by(
                        KbMemoryCandidate.last_seen_at.desc(), KbMemoryCandidate.slug
                    ).limit(max(1, min(limit, 500)))
                )
            ).all()
        return {"items": [_candidate_snapshot(row) for row in rows], "total": len(rows)}

    async def memory_states(self, slugs: Iterable[str]) -> dict[str, dict[str, Any]]:
        """聚合规划用的现有条目状态；只取 status/conclusion/evidence。"""
        wanted = list(dict.fromkeys(slugs))
        if not wanted:
            return {}
        async with self._session() as session:
            rows = (
                await session.scalars(select(KbMemoryEntry).where(KbMemoryEntry.slug.in_(wanted)))
            ).all()
        return {
            row.slug: {
                "status": row.status,
                "conclusion": row.conclusion,
                "evidence": list(row.evidence),
            }
            for row in rows
        }

    async def apply_memory_plan(
        self,
        plan: MemoryPlan,
        *,
        expected_states: Mapping[str, Mapping[str, Any]],
        actor: str | None = None,
        reason: str | None = None,
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """把聚合计划原子落库；规划后状态漂移则整批冲突、一条不写。

        调用方在模型响应后读取 `memory_states` 再规划；这里在同一写锁事务内重读并
        比对 status/conclusion/证据键，避免覆盖规划期间的人工修改。
        """
        moment = now or _now()
        slugs = list(
            dict.fromkeys(
                [write.slug for write in plan.writes] + [item.slug for item in plan.candidates]
            )
        )
        async with self.write_scope(), self._session() as session:
            rows: dict[str, KbMemoryEntry] = {}
            candidates: dict[str, KbMemoryCandidate] = {}
            if slugs:
                entries = (
                    await session.scalars(
                        select(KbMemoryEntry).where(KbMemoryEntry.slug.in_(slugs)).with_for_update()
                    )
                ).all()
                rows = {row.slug: row for row in entries}
                existing_candidates = (
                    await session.scalars(
                        select(KbMemoryCandidate)
                        .where(KbMemoryCandidate.slug.in_(slugs))
                        .with_for_update()
                    )
                ).all()
                candidates = {row.slug: row for row in existing_candidates}

            for write in plan.writes:
                current = rows.get(write.slug)
                expected = expected_states.get(write.slug)
                if write.action == "create":
                    drifted = current is not None or expected is not None
                else:
                    drifted = (
                        current is None
                        or current.status != "active"
                        or expected is None
                        or str(expected.get("status")) != "active"
                        or current.conclusion != expected.get("conclusion")
                        or _evidence_keys(current.evidence)
                        != _evidence_keys(expected.get("evidence"))
                    )
                if drifted:
                    raise ConflictError("记忆状态已变化，请重新聚合", {"slug": write.slug})

            written: list[dict[str, Any]] = []
            for write in plan.writes:
                current = rows.get(write.slug)
                if write.action == "create":
                    row = KbMemoryEntry(
                        slug=write.slug,
                        title=write.title.strip(),
                        conclusion=write.conclusion.strip(),
                        boundary=write.boundary.strip(),
                        invalidation=write.invalidation.strip(),
                        evidence=[item.as_dict() for item in write.evidence],
                        confidence=min(1.0, max(0.0, float(write.confidence))),
                        status="active",
                        contradicts=list(dict.fromkeys(write.contradicts)),
                        revision=new_revision(),
                        created_at=moment,
                        updated_at=moment,
                    )
                    session.add(row)
                    session.add(
                        KbMemoryRevision(
                            slug=write.slug,
                            revision=row.revision,
                            actor=actor,
                            reason=reason,
                            before={},
                            after=_memory_entry_snapshot(row),
                            created_at=moment,
                        )
                    )
                    written.append(_memory_entry_snapshot(row))
                    existing = candidates.get(write.slug)
                    await self.upsert_memory_candidate(
                        CandidateWrite(
                            slug=write.slug,
                            title=write.title,
                            conclusion=write.conclusion,
                            boundary=write.boundary,
                            invalidation=write.invalidation,
                            confidence=write.confidence,
                            evidence=write.evidence,
                            contradicts=write.contradicts,
                            session_count=write.session_count,
                            project_count=write.project_count,
                            status="promoted",
                            # 候选表只允许三种 reason；转正保留它原先为何停在候选。
                            reason=cast(
                                CandidateReason,
                                existing.reason if existing is not None else "below_threshold",
                            ),
                        ),
                        now=moment,
                    )
                    continue

                assert current is not None  # 已在上面的重校验里确认存在
                before = _memory_entry_snapshot(current)
                current.title = write.title.strip()
                current.conclusion = write.conclusion.strip()
                current.boundary = write.boundary.strip()
                current.invalidation = write.invalidation.strip()
                current.evidence = [item.as_dict() for item in write.evidence]
                current.confidence = min(1.0, max(0.0, float(write.confidence)))
                current.contradicts = list(dict.fromkeys(write.contradicts))
                current.revision = new_revision()
                current.updated_at = moment
                session.add(
                    KbMemoryRevision(
                        slug=write.slug,
                        revision=current.revision,
                        actor=actor,
                        reason=reason,
                        before=before,
                        after=_memory_entry_snapshot(current),
                        created_at=moment,
                    )
                )
                written.append(_memory_entry_snapshot(current))

            promoted = {write.slug for write in plan.writes}
            for candidate in plan.candidates:
                if candidate.slug in promoted:
                    continue
                await self.upsert_memory_candidate(candidate, now=moment)
            await session.flush()
            return written

    async def recent_memory_inputs(self, *, since: datetime, limit: int) -> list[dict[str, Any]]:
        """聚合输入：最近更新的 canonical 活动节点（不读记忆表）。"""
        kinds = ("fact", "decision", "procedure", "pitfall")
        async with self._session() as session:
            rows = (
                await session.scalars(
                    select(KbNode)
                    .where(
                        KbNode.archived_at.is_(None),
                        KbNode.tier == "canonical",
                        KbNode.kind.in_(kinds),
                        KbNode.updated_at >= since,
                    )
                    .order_by(KbNode.updated_at.desc(), KbNode.id)
                    .limit(max(1, min(limit, 1000)))
                )
            ).all()
        return [
            {
                "id": row.id,
                "project": row.project,
                "kind": row.kind,
                "title": row.title,
                "body": row.body,
                "source": list(row.source),
                "updated_at": row.updated_at,
            }
            for row in rows
        ]

    async def publish_memory_snapshot(
        self, *, actor: str | None = None, note: str = ""
    ) -> dict[str, Any]:
        """把当前全部 active 条目冻结成新快照并发布；旧 published 置 superseded。"""
        now = _now()
        async with self.write_scope(), self._session() as session:
            rows = (
                await session.scalars(
                    select(KbMemoryEntry)
                    .where(KbMemoryEntry.status == "active")
                    .order_by(KbMemoryEntry.slug)
                )
            ).all()
            current = await session.scalar(
                select(KbMemorySnapshot)
                .where(KbMemorySnapshot.status == "published")
                .with_for_update()
            )
            if current is not None:
                current.status = "superseded"
                await session.flush()
            snapshot = KbMemorySnapshot(
                status="published",
                entries=[_memory_entry_snapshot(row) for row in rows],
                item_count=len(rows),
                note=note.strip(),
                actor=actor,
                created_at=now,
                published_at=now,
            )
            session.add(snapshot)
            await session.flush()
            session.add(
                KbWriteAudit(
                    actor=actor,
                    project=None,
                    node_id=None,
                    action="memory_snapshot_publish",
                    result="ok",
                    memory_snapshot=snapshot.version,
                    created_at=now,
                )
            )
            return _memory_snapshot_snapshot(snapshot)

    async def activate_memory_snapshot(
        self, version: int, *, actor: str | None = None
    ) -> dict[str, Any]:
        """回滚到旧快照；disabled 不能重新激活。"""
        now = _now()
        async with self.write_scope(), self._session() as session:
            target = await session.get(KbMemorySnapshot, version, with_for_update=True)
            if target is None:
                raise NotFoundError(f"记忆快照不存在: {version}")
            if target.status == "published":
                return _memory_snapshot_snapshot(target)
            if target.status == "disabled":
                raise ConflictError("已停用的快照不能重新激活", {"version": version})
            current = await session.scalar(
                select(KbMemorySnapshot)
                .where(KbMemorySnapshot.status == "published")
                .with_for_update()
            )
            if current is not None:
                current.status = "superseded"
                await session.flush()
            target.status = "published"
            target.published_at = now
            session.add(
                KbWriteAudit(
                    actor=actor,
                    project=None,
                    node_id=None,
                    action="memory_snapshot_activate",
                    result="ok",
                    memory_snapshot=version,
                    created_at=now,
                )
            )
            await session.flush()
            return _memory_snapshot_snapshot(target)

    async def disable_memory_snapshot(
        self, version: int, *, actor: str | None = None
    ) -> dict[str, Any]:
        """整体停用当前快照；停用后没有 published，抽取不再注入。"""
        now = _now()
        async with self.write_scope(), self._session() as session:
            target = await session.get(KbMemorySnapshot, version, with_for_update=True)
            if target is None:
                raise NotFoundError(f"记忆快照不存在: {version}")
            if target.status != "published":
                raise ConflictError("只能停用当前已发布的快照", {"version": version})
            target.status = "disabled"
            session.add(
                KbWriteAudit(
                    actor=actor,
                    project=None,
                    node_id=None,
                    action="memory_snapshot_disable",
                    result="ok",
                    memory_snapshot=version,
                    created_at=now,
                )
            )
            await session.flush()
            return _memory_snapshot_snapshot(target)

    async def list_memory_snapshots(self, *, limit: int = 50) -> list[dict[str, Any]]:
        async with self._session() as session:
            rows = (
                await session.scalars(
                    select(KbMemorySnapshot)
                    .order_by(KbMemorySnapshot.version.desc())
                    .limit(max(1, min(limit, 200)))
                )
            ).all()
        return [_memory_snapshot_snapshot(row) for row in rows]

    async def published_memory_snapshot(self) -> dict[str, Any] | None:
        """worker 启动时读一次并固定；不提供热切换入口。"""
        async with self._session() as session:
            row = await session.scalar(
                select(KbMemorySnapshot).where(KbMemorySnapshot.status == "published")
            )
        return _memory_snapshot_snapshot(row) if row is not None else None

    # -- MCP 调用轨迹（ADR-0015） ------------------------------------------

    async def record_mcp_trace(self, entry: TraceEntry) -> None:
        """一行调用轨迹；`trace_id` 冲突视为重放，直接忽略保证幂等。"""
        statement = pg_insert(KbMcpTrace).values(
            trace_id=entry.trace_id,
            request_id=entry.request_id,
            rpc_id=entry.rpc_id,
            called_at=entry.called_at,
            credential_id=entry.credential_id,
            credential_name=entry.credential_name,
            tool=entry.tool,
            status=entry.status,
            http_status=entry.http_status,
            error_code=entry.error_code,
            error_kind=entry.error_kind,
            duration_ms=entry.duration_ms,
            result_bytes=entry.result_bytes,
            args_digest=entry.args_digest,
            projects=entry.projects,
            client=entry.client,
        )
        statement = statement.on_conflict_do_nothing(index_elements=["trace_id"])
        async with self._session() as session:
            await session.execute(statement)

    async def cleanup_mcp_traces(self, cutoff: datetime) -> int:
        """删除 `cutoff` 之前的轨迹明细，返回删除行数。"""
        async with self._session() as session:
            result = await session.execute(delete(KbMcpTrace).where(KbMcpTrace.called_at < cutoff))
            rowcount = getattr(result, "rowcount", 0)
            return int(rowcount or 0)


__all__ = [
    "REVISION_RE",
    "NodeMissing",
    "PgKnowledgeStore",
    "RevisionConflict",
    "WriteDeferred",
    "new_revision",
]
