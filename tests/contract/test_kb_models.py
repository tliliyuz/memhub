"""`kb_*` 表的结构契约（规格 §3，验收条件 §8.2/§8.7 的存储侧；`kb_mcp_trace` 见 ADR-0015）。

每个用例在独立 schema 内用 `Base.metadata.create_all` 建表；Alembic 迁移与模型的一致性
由单独的迁移测试负责。
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from memhub.kb.models import (
    Base,
    KbArchive,
    KbEdge,
    KbNode,
    KbNodeRevision,
    KbProject,
    KbWriteAudit,
)

NOW = datetime(2026, 11, 24, 8, 0, tzinfo=UTC)
REV = "0123456789abcdef"
BODY = "第一行：中文与 English 混排。\n\n- 要点 1\n- 要点 2\n\n```python\nprint('多行代码')\n```\n"


@pytest.fixture
async def engine(kb_engine: AsyncEngine) -> AsyncEngine:
    async with kb_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return kb_engine


async def _add_project_and_node(engine: AsyncEngine, node: KbNode) -> None:
    """无 relationship 时 UOW 不排 FK 依赖：先 flush 登记行，再写节点。"""
    async with AsyncSession(engine) as session, session.begin():
        session.add(_project())
        await session.flush()
        session.add(node)


def _project(project_id: str = "demo") -> KbProject:
    return KbProject(id=project_id, name="", revision=REV, created_at=NOW, updated_at=NOW)


def _node(node_id: str = "demo/fact/alpha", project: str = "demo") -> KbNode:
    return KbNode(
        id=node_id,
        project=project,
        kind="fact",
        title="节点标题",
        body=BODY,
        revision=REV,
        created_at=NOW,
        updated_at=NOW,
    )


def test_exactly_the_kb_tables() -> None:
    """知识表自成一套 metadata：不得夹带运行态 5 表，否则 Alembic 会接管它们。"""
    assert sorted(Base.metadata.tables) == [
        "kb_archives",
        "kb_edges",
        "kb_mcp_trace",
        "kb_node_revisions",
        "kb_nodes",
        "kb_projects",
        "kb_write_audit",
    ]


async def test_node_round_trip_keeps_every_field(engine: AsyncEngine) -> None:
    node = _node()
    node.entity_kind = None
    node.tier = "canonical"
    node.confidence = 0.75
    node.tags = ["中文标签", "tag-b"]
    node.source = [{"type": "session", "ref": "s/1", "device": None, "captured_at": None}]
    node.supersedes = ["demo/fact/old-1", "demo/fact/old-2"]
    node.superseded_by = "demo/fact/newer"
    node.deprecated_reason = "被证伪"
    node.valid_from = NOW
    node.valid_until = NOW.replace(year=2027)
    node.occurred_at = NOW
    node.decided_at = NOW
    node.status = "open"
    await _add_project_and_node(engine, node)

    async with AsyncSession(engine) as session:
        got = await session.get(KbNode, "demo/fact/alpha")
    assert got is not None
    assert got.body == BODY
    assert got.tags == ["中文标签", "tag-b"]
    assert got.source == [{"type": "session", "ref": "s/1", "device": None, "captured_at": None}]
    assert got.supersedes == ["demo/fact/old-1", "demo/fact/old-2"]
    assert got.superseded_by == "demo/fact/newer"
    assert got.confidence == 0.75
    assert got.valid_until == NOW.replace(year=2027)
    assert got.created_at == NOW
    assert got.archived_at is None
    assert got.revision == REV


async def test_column_defaults(engine: AsyncEngine) -> None:
    await _add_project_and_node(engine, _node())
    async with AsyncSession(engine) as session:
        node = await session.get(KbNode, "demo/fact/alpha")
        project = await session.get(KbProject, "demo")
    assert node is not None and project is not None
    assert node.tier == "candidate"
    assert node.tags == []
    assert node.source == []
    assert node.supersedes == []
    assert project.description == ""
    assert project.archived_at is None


@pytest.mark.parametrize("bad_id", ["Demo", "-lead", "a" * 65, "has space", ""])
async def test_project_id_must_match_kb_id_pattern(engine: AsyncEngine, bad_id: str) -> None:
    with pytest.raises(IntegrityError):
        async with AsyncSession(engine) as session, session.begin():
            session.add(_project(bad_id))


async def test_node_requires_registered_project(engine: AsyncEngine) -> None:
    with pytest.raises(IntegrityError):
        async with AsyncSession(engine) as session, session.begin():
            session.add(_node(project="ghost"))


async def test_edges_keep_dangling_endpoints_and_dedupe_on_triple(engine: AsyncEngine) -> None:
    """端点不加外键（保悬空边）；`(source, predicate, target)` 唯一。"""
    edge = {"project": "demo", "source": "demo/fact/ghost", "predicate": "related_to"}
    async with AsyncSession(engine) as session, session.begin():
        session.add(KbEdge(**edge, target="demo/fact/missing", source_doc="doc", created_at=NOW))
    async with AsyncSession(engine) as session:
        rows = (await session.scalars(select(KbEdge))).all()
    assert [(r.source, r.target, r.source_doc) for r in rows] == [
        ("demo/fact/ghost", "demo/fact/missing", "doc")
    ]

    with pytest.raises(IntegrityError):
        async with AsyncSession(engine) as session, session.begin():
            session.add(KbEdge(**edge, target="demo/fact/missing", created_at=NOW))


async def test_node_revisions_survive_without_node(engine: AsyncEngine) -> None:
    """修订历史不设外键：节点软删甚至被清理后，历史仍可回滚。"""
    after = {"id": "demo/fact/gone", "body": BODY, "title": "标题"}
    async with AsyncSession(engine) as session, session.begin():
        session.add(
            KbNodeRevision(
                node_id="demo/fact/gone",
                revision=REV,
                tier="candidate",
                actor="ui:alice",
                reason="create",
                before={},
                after=after,
                created_at=NOW,
            )
        )
    async with AsyncSession(engine) as session:
        row = (await session.scalars(select(KbNodeRevision))).one()
    assert row.after == after
    assert row.after["body"] == BODY


async def test_archive_snapshot_is_binary_safe(engine: AsyncEngine) -> None:
    snapshot = bytes(range(256)) * 4
    async with AsyncSession(engine) as session, session.begin():
        session.add(
            KbArchive(
                archive_id="a" * 32,
                project="demo",
                status="pending",
                snapshot=snapshot,
                archived_count=3,
                removed_edges=1,
                created_at=NOW,
            )
        )
    async with AsyncSession(engine) as session:
        row = await session.get(KbArchive, "a" * 32)
    assert row is not None
    assert row.snapshot == snapshot
    assert (row.archived_count, row.removed_edges, row.status) == (3, 1, "pending")
    assert row.deleted_at is None


async def test_write_audit_allows_missing_actor_and_node(engine: AsyncEngine) -> None:
    async with AsyncSession(engine) as session, session.begin():
        session.add(KbWriteAudit(action="ingest", result="ok", created_at=NOW))
    async with AsyncSession(engine) as session:
        row = (await session.scalars(select(KbWriteAudit))).one()
    assert (row.actor, row.project, row.node_id) == (None, None, None)
    assert (row.action, row.result) == ("ingest", "ok")
