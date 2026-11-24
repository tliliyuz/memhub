"""`kb_*` 表的存储层：替代 markdown 文件读写（ADR-0013，规格 §3/§7）。

接口形状与 `store.KnowledgeStore` 平行，调用方（manage/candidates/query）按需切换；
差异只在语义：

- 一次写操作 = 一个事务，并在同一事务内追加 `kb_node_revisions`；
- `revision` 每次写入重新生成（16 位小写 hex），不再是文件 sha256；
- 「库存在」= `kb_projects` 有登记行且 `archived_at is null`，不再看目录；
- 边端点不加外键，悬空边原样保留；去重键 `(source, predicate, target)`。

所有语句由 ORM/Core 构造，不写裸 SQL（ADR-0005）。
"""

from __future__ import annotations

import json
import re
import secrets
from collections.abc import AsyncIterator, Iterable
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import CursorResult, delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from memhub.contract import Edge, NodeFrontmatter, Predicate
from memhub.kb.models import KbEdge, KbNode, KbNodeRevision, KbProject
from memhub.kb.store import ProjectMissing

REVISION_RE = re.compile(r"^[0-9a-f]{16}$")
_PROJECT_SEP = "/"


class NodeMissing(LookupError):
    """节点不存在或已软删（与 `query.NotFound` 区分：这是存储层事实）。"""


class RevisionConflict(RuntimeError):
    """乐观锁失配：调用方提供的 `expected_revision` 已过期。"""

    def __init__(self, node_id: str, *, expected: str, current: str | None) -> None:
        super().__init__(f"节点已被修改：{node_id}（expected={expected} current={current}）")
        self.node_id = node_id
        self.expected = expected
        self.current = current


def new_revision() -> str:
    """16 位小写十六进制；8 字节随机足够，契约只要格式与唯一性。"""
    return secrets.token_hex(8)


def _now() -> datetime:
    return datetime.now(UTC)


def _snapshot(node: NodeFrontmatter, body: str) -> dict[str, Any]:
    """完整快照（含正文），供 `kb_node_revisions` 精确回滚。"""
    data = node.model_dump(mode="json")
    data["body"] = body
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


class PgKnowledgeStore:
    """`kb_*` 的异步存储实现；`sessions` 由 `session.create_sessionmaker` 提供。"""

    resolve_short_aliases = True

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

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
        async with self.sessions() as session, session.begin():
            await session.execute(stmt)
        return revision

    async def project_exists(self, project_id: str) -> bool:
        """已登记且活动；「目录存在」不再是判据。"""
        async with self.sessions() as session:
            stmt = select(KbProject.id).where(
                KbProject.id == project_id, KbProject.archived_at.is_(None)
            )
            return await session.scalar(stmt) is not None

    async def archive_project(self, project_id: str) -> None:
        async with self.sessions() as session, session.begin():
            project = await session.get(KbProject, project_id, with_for_update=True)
            if project is None:
                raise ProjectMissing(f"知识库未登记：{project_id}")
            project.archived_at = _now()
            project.revision = new_revision()
            project.updated_at = _now()

    # -- 节点 -----------------------------------------------------------
    async def exists(self, node_id: str) -> bool:
        async with self.sessions() as session:
            stmt = select(KbNode.id).where(KbNode.id == node_id, KbNode.archived_at.is_(None))
            return await session.scalar(stmt) is not None

    async def revision(self, node_id: str) -> str | None:
        """当前 revision；节点不存在或已软删返回 None（调用方据此报 404）。"""
        async with self.sessions() as session:
            stmt = select(KbNode.revision).where(KbNode.id == node_id, KbNode.archived_at.is_(None))
            return cast("str | None", await session.scalar(stmt))

    async def read(self, node_id: str) -> tuple[NodeFrontmatter, str]:
        async with self.sessions() as session:
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
        async with self.sessions() as session, session.begin():
            _require_active_project = (
                await session.scalar(
                    select(KbProject.id).where(
                        KbProject.id == project, KbProject.archived_at.is_(None)
                    )
                )
                is not None
            )
            if not _require_active_project:
                raise ProjectMissing(f"知识库不存在或已归档：{project}")

            existing = await session.get(KbNode, node_id, with_for_update=True)
            current = None if existing is None or existing.archived_at else existing.revision
            if expected_revision is not None and current != expected_revision:
                # 行锁已拿到，此刻读到的是最新已提交值；不覆盖后来者的写入。
                raise RevisionConflict(node_id, expected=expected_revision, current=current)
            before = (
                _snapshot(_node_from_row(existing), existing.body) if existing is not None else {}
            )
            if existing is None:
                await session.execute(pg_insert(KbNode).values(**values))
            else:
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
        async with self.sessions() as session:
            stmt = select(KbNode.id).where(KbNode.archived_at.is_(None))
            if project is not None:
                stmt = stmt.where(KbNode.project == project)
            ids = list(await session.scalars(stmt))
        return sorted(ids)

    async def archive_node(self, node_id: str, *, actor: str | None = None) -> None:
        """软删：只置 `archived_at`，行与正文保留（永不硬删）。"""
        async with self.sessions() as session, session.begin():
            row = await session.get(KbNode, node_id, with_for_update=True)
            if row is None or row.archived_at is not None:
                raise NodeMissing(f"节点不存在: {node_id}")
            row.archived_at = _now()

    # -- 边 -------------------------------------------------------------
    async def edges(self, project: str | None = None) -> list[dict[str, Any]]:
        async with self.sessions() as session:
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
        if not await self.project_exists(project):
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

        async with self.sessions() as session, session.begin():
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
        async with self.sessions() as session, session.begin():
            result = await session.execute(stmt)
        return int(cast("CursorResult[Any]", result).rowcount or 0)

    async def count(self) -> dict[str, int]:
        """storage 自检用的小计数；治理统计仍走 `manage.stats`。"""
        async with self.sessions() as session:
            nodes = await session.scalar(
                select(func.count()).select_from(KbNode).where(KbNode.archived_at.is_(None))
            )
            edges = await session.scalar(select(func.count()).select_from(KbEdge))
        return {"nodes": int(nodes or 0), "edges": int(edges or 0)}
