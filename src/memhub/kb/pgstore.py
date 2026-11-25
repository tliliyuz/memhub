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
from collections.abc import AsyncIterator, Callable, Iterable
from contextlib import asynccontextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import CursorResult, delete, func, select
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
from memhub.kb.models import KbArchive, KbEdge, KbNode, KbNodeRevision, KbProject, KbWriteAudit
from memhub.kb.store import TrashEntry

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

    async def latest_write(self) -> datetime | None:
        """真源最近一次写入时间；投影过期判断的文件 mtime 替代品。

        取修订流与边表的最大时间：每次写节点（含软删、归档、恢复）都会追加修订，
        普通写入也会更新节点，两者都落在这两条时间线上。
        """
        async with self._session() as session:
            revision_at = await session.scalar(select(func.max(KbNodeRevision.created_at)))
            edge_at = await session.scalar(select(func.max(KbEdge.created_at)))
        moments = [moment for moment in (revision_at, edge_at) if moment is not None]
        return max(moments) if moments else None

    # -- 写入审计（规格 §3.6） --------------------------------------------

    async def record_write_audit(
        self,
        *,
        actor: str | None,
        project: str | None,
        node_id: str | None,
        action: str,
        result: str,
    ) -> None:
        """一条不含正文与 token 的写入审计；自成事务，写路径失败也不能吞掉它。

        审计写入失败按原样上抛：审计缺失必须显式失败，不能静默丢记录。
        """
        async with self._session() as session:
            session.add(
                KbWriteAudit(
                    actor=actor,
                    project=project,
                    node_id=node_id,
                    action=action,
                    result=result,
                    created_at=_now(),
                )
            )


__all__ = [
    "REVISION_RE",
    "NodeMissing",
    "PgKnowledgeStore",
    "RevisionConflict",
    "WriteDeferred",
    "new_revision",
]
