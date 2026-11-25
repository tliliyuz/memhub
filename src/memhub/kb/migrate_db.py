"""一次性迁移（markdown → PG）的写库与校验半段：规格 §5 第 6–9 步。

解析侧（`memhub.kb.migrate.parse_tree`）只读磁盘、给出目标表行；本模块负责把
这些行写进 `kb_*` 表，并把库内实际内容读回来做逐节点、逐边比对。

约定：

- 全部写入在一个事务里完成，任何一步失败整体回滚（规格 §5 第 6 步）。
- 幂等：项目按 `id`、节点按 `id`、归档按 `archive_id` upsert；边按唯一三元组
  冲突更新，重复运行不产生重复行（规格 §5 第 9 步）。
- `kb_projects` 必须先落，`kb_nodes.project` 才有外键可指（模型层没有
  relationship，UOW 不会自动排依赖）。
- 回收站的删除事实（时间戳、actor、reason）写进 `kb_node_revisions`：这是替代
  git 之后唯一能保留「谁在何时删除」的位置。
- 悬空边原样写入 `kb_edges`，不加端点外键（规格 §3.3、ADR-0013 §8）。
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from memhub.kb.migrate import MigrationPlan, node_revision
from memhub.kb.models import KbArchive, KbEdge, KbNode, KbNodeRevision, KbProject

ARCHIVE_MODES = ("skip", "migrate")


@dataclass(frozen=True)
class StoredKnowledge:
    """从库里读回的知识（形状与解析结果同级，便于直接比对）。"""

    projects: dict[str, dict[str, Any]]
    nodes: dict[str, dict[str, Any]]
    edges: set[tuple[str, str, str]]
    archives: dict[str, str]


@dataclass
class VerifyDiff:
    """`--verify-only` 的差异清单；全部为空时 `ok` 为真。"""

    missing_projects: tuple[str, ...] = ()
    extra_projects: tuple[str, ...] = ()
    changed_projects: tuple[dict[str, str], ...] = ()
    missing_nodes: tuple[str, ...] = ()
    extra_nodes: tuple[str, ...] = ()
    changed_nodes: tuple[dict[str, str], ...] = ()
    missing_edges: tuple[dict[str, str], ...] = ()
    extra_edges: tuple[dict[str, str], ...] = ()
    archive_mismatches: tuple[dict[str, str], ...] = ()

    @property
    def ok(self) -> bool:
        return not any(
            (
                self.missing_projects,
                self.extra_projects,
                self.changed_projects,
                self.missing_nodes,
                self.extra_nodes,
                self.changed_nodes,
                self.missing_edges,
                self.extra_edges,
                self.archive_mismatches,
            )
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "missing_projects": list(self.missing_projects),
            "extra_projects": list(self.extra_projects),
            "changed_projects": [dict(item) for item in self.changed_projects],
            "missing_nodes": list(self.missing_nodes),
            "extra_nodes": list(self.extra_nodes),
            "changed_nodes": [dict(item) for item in self.changed_nodes],
            "missing_edges": [dict(item) for item in self.missing_edges],
            "extra_edges": [dict(item) for item in self.extra_edges],
            "archive_mismatches": [dict(item) for item in self.archive_mismatches],
        }


def _snapshot(row: dict[str, Any]) -> dict[str, Any]:
    """行 → JSONB 可存的快照：时间统一成 UTC ISO 文本，其余原样。"""
    snapshot: dict[str, Any] = {}
    for key, value in row.items():
        if isinstance(value, datetime):
            moment = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
            snapshot[key] = moment.astimezone(UTC).isoformat()
        else:
            snapshot[key] = value
    return snapshot


async def _upsert(
    session: AsyncSession,
    model: Any,
    rows: Sequence[dict[str, Any]],
    conflict_columns: Sequence[str],
    mutable_columns: Sequence[str],
) -> None:
    """按冲突列 upsert；重复运行更新可变列，不新增行。

    解析侧会带 `snapshot_sha256` 这类校验用辅助键，这里按表的真实列过滤，
    避免伪列被当成 SQL 列名。
    """
    if not rows:
        return
    columns = set(model.__table__.columns.keys())
    payload = [{key: value for key, value in row.items() if key in columns} for row in rows]
    statement = pg_insert(model).values(payload)
    excluded = statement.excluded
    statement = statement.on_conflict_do_update(
        index_elements=list(conflict_columns),
        set_={column: getattr(excluded, column) for column in mutable_columns},
    )
    await session.execute(statement)


async def apply_plan(engine: AsyncEngine, plan: MigrationPlan, *, archives: str = "skip") -> None:
    """把解析结果写进 `kb_*` 表：单事务、幂等、先项目后节点。"""
    if archives not in ARCHIVE_MODES:
        raise ValueError(f"archives 只接受 {ARCHIVE_MODES}")
    async with AsyncSession(engine) as session, session.begin():
        # 外键靠应用层排序：项目行先落，节点才能指过去。
        await _upsert(
            session,
            KbProject,
            plan.projects,
            ("id",),
            ("name", "description", "revision", "created_at", "updated_at", "archived_at"),
        )
        await _upsert(
            session,
            KbNode,
            plan.nodes,
            ("id",),
            (
                "project",
                "kind",
                "entity_kind",
                "title",
                "tier",
                "confidence",
                "tags",
                "body",
                "source",
                "valid_from",
                "valid_until",
                "supersedes",
                "superseded_by",
                "deprecated_reason",
                "occurred_at",
                "decided_at",
                "status",
                "created_at",
                "updated_at",
                "archived_at",
                "revision",
            ),
        )
        await _upsert(
            session,
            KbEdge,
            plan.edges,
            ("source", "predicate", "target"),
            ("project", "source_doc", "created_at"),
        )
        if archives == "migrate":
            await _upsert(
                session,
                KbArchive,
                plan.archives,
                ("archive_id",),
                (
                    "project",
                    "status",
                    "snapshot",
                    "archived_count",
                    "removed_edges",
                    "actor",
                    "deleted_at",
                    "created_at",
                ),
            )
        await _record_trash_history(session, plan)


async def _record_trash_history(session: AsyncSession, plan: MigrationPlan) -> None:
    """回收站的删除事实写进修订历史；已记录过的节点跳过，保证重复运行幂等。"""
    nodes = {row["id"]: row for row in plan.nodes if row["archived_at"] is not None}
    pending = [event for event in plan.trash_events if event["node_id"] in nodes]
    if not pending:
        return
    existing = set(
        (
            await session.execute(
                select(KbNodeRevision.node_id).where(
                    KbNodeRevision.node_id.in_([event["node_id"] for event in pending])
                )
            )
        ).scalars()
    )
    rows: list[dict[str, Any]] = []
    for event in pending:
        node = nodes[event["node_id"]]
        if node["id"] in existing:
            continue
        after = _snapshot(node)
        # 唯一已知的差异就是删除时刻：before 取删除前的状态，after 带 archived_at。
        before = {**after, "archived_at": None}
        rows.append(
            {
                "node_id": node["id"],
                "revision": node["revision"],
                "tier": node["tier"],
                "actor": event["actor"] or None,
                "reason": event["reason"] or None,
                "before": before,
                "after": after,
                "created_at": node["archived_at"],
            }
        )
    if rows:
        await session.execute(insert(KbNodeRevision), rows)


async def read_stored(engine: AsyncEngine) -> StoredKnowledge:
    """读出库内现状：整表扫描。知识表量级是数百到数千行，迁移校验一次全读更稳。"""
    async with AsyncSession(engine) as session:
        project_rows = (await session.execute(select(KbProject.__table__))).mappings().all()
        node_rows = (await session.execute(select(KbNode.__table__))).mappings().all()
        edge_rows = (
            await session.execute(select(KbEdge.source, KbEdge.predicate, KbEdge.target))
        ).all()
        archive_rows = (
            await session.execute(select(KbArchive.archive_id, KbArchive.snapshot))
        ).all()
    return StoredKnowledge(
        projects={row["id"]: dict(row) for row in project_rows},
        nodes={row["id"]: dict(row) for row in node_rows},
        edges={(row[0], row[1], row[2]) for row in edge_rows},
        archives={row[0]: _sha256_hex(bytes(row[1])) for row in archive_rows},
    )


def _sha256_hex(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def diff_plan(
    plan: MigrationPlan, stored: StoredKnowledge, *, archives: str = "skip"
) -> VerifyDiff:
    """逐项目、逐节点、逐边比对；`archives=migrate` 时再比归档快照哈希。"""
    disk_projects = {row["id"]: row for row in plan.projects}
    disk_nodes = {row["id"]: row for row in plan.nodes}
    diff = VerifyDiff(
        missing_projects=tuple(sorted(set(disk_projects) - set(stored.projects))),
        extra_projects=tuple(sorted(set(stored.projects) - set(disk_projects))),
        changed_projects=_changed(disk_projects, stored.projects, "project_id"),
        missing_nodes=tuple(sorted(set(disk_nodes) - set(stored.nodes))),
        extra_nodes=tuple(sorted(set(stored.nodes) - set(disk_nodes))),
        changed_nodes=_changed(disk_nodes, stored.nodes, "node_id"),
    )
    disk_edges = {(row["source"], row["predicate"], row["target"]) for row in plan.edges}
    diff.missing_edges = tuple(_edge_dict(edge) for edge in sorted(disk_edges - stored.edges))
    diff.extra_edges = tuple(_edge_dict(edge) for edge in sorted(stored.edges - disk_edges))
    if archives == "migrate":
        diff.archive_mismatches = tuple(
            {
                "archive_id": row["archive_id"],
                "disk_sha256": row["snapshot_sha256"],
                "db_sha256": stored.archives.get(row["archive_id"], ""),
            }
            for row in plan.archives
            if stored.archives.get(row["archive_id"]) != row["snapshot_sha256"]
        )
    return diff


def _edge_dict(edge: tuple[str, str, str]) -> dict[str, str]:
    return {"source": edge[0], "predicate": edge[1], "target": edge[2]}


def _changed(
    disk: dict[str, dict[str, Any]], stored: dict[str, dict[str, Any]], id_key: str
) -> tuple[dict[str, str], ...]:
    """同 id 的内容哈希不一致；哈希由库内实际内容重算，不信 `revision` 列。"""
    return tuple(
        {
            id_key: row_id,
            "disk_revision": node_revision(disk[row_id]),
            "db_revision": node_revision(stored[row_id]),
        }
        for row_id in sorted(set(disk) & set(stored))
        if node_revision(disk[row_id]) != node_revision(stored[row_id])
    )
