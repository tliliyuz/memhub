"""`kb_*` 存储层的验收条件（规格 §8.2/§8.3/§8.5/§8.7 的存储侧）。

每个用例在独立 schema 内建表；调用方（manage/candidates/query）的接入另片验证。
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from memhub.contract import Kind, NodeFrontmatter, Predicate, SourceKind, SourceRef, Tier
from memhub.kb.errors import TargetUnavailable
from memhub.kb.models import Base, KbArchive, KbEdge, KbNode, KbNodeRevision
from memhub.kb.pgstore import NodeMissing, PgKnowledgeStore, RevisionConflict, WriteDeferred
from memhub.kb.session import create_sessionmaker
from memhub.kb.store import ProjectMissing

REVISION_RE = re.compile(r"^[0-9a-f]{16}$")
NOW = datetime(2026, 11, 24, 9, 30, tzinfo=UTC)
BODY = "第一段：中文与 English 混排。\n\n- 要点 1\n- 要点 2\n\n```python\nprint('多行代码')\n```\n"

PROJECT = "demo"


def _node(
    node_id: str = "demo/fact/alpha", project: str = PROJECT, *, title: str = "节点标题"
) -> NodeFrontmatter:
    return NodeFrontmatter(
        id=node_id,
        project=project,
        kind=Kind.FACT,
        title=title,
        created_at=NOW,
        updated_at=NOW,
        tags=["中文标签", "tag-b"],
        source=[SourceRef(type=SourceKind.SESSION, ref="sessions/a.jsonl")],
        tier=Tier.CANDIDATE,
    )


@pytest.fixture
async def engine(kb_engine: AsyncEngine) -> AsyncEngine:
    async with kb_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return kb_engine


@pytest.fixture
async def store(engine: AsyncEngine) -> PgKnowledgeStore:
    return PgKnowledgeStore(create_sessionmaker(engine))


async def test_write_requires_registered_active_project(store: PgKnowledgeStore) -> None:
    with pytest.raises(ProjectMissing):
        await store.write("demo/fact/alpha", _node(), BODY)

    await store.register_project(PROJECT, name="演示库")
    await store.write("demo/fact/alpha", _node(), BODY)

    await store.archive_project(PROJECT)
    with pytest.raises(ProjectMissing):
        await store.write("demo/fact/beta", _node("demo/fact/beta"), BODY)


async def test_runtime_write_normalizes_naive_time_to_utc(kb_schema: str, test_dsn: str) -> None:
    """API/MCP 传入裸日期时，运行态写入也必须落 UTC 零点。

    会话时区钉成 +08 复现生产库；模型边界不归一就会存成前一天 16:00Z。
    """
    engine = create_async_engine(
        test_dsn.replace("postgresql://", "postgresql+psycopg://", 1),
        connect_args={"options": f"-csearch_path={kb_schema} -ctimezone=Asia/Shanghai"},
    )
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        store = PgKnowledgeStore(create_sessionmaker(engine))
        await store.register_project(PROJECT, name="演示库")
        node = NodeFrontmatter.model_validate(
            {
                "id": "demo/fact/date-only",
                "project": PROJECT,
                "kind": "fact",
                "title": "裸日期",
                "created_at": NOW,
                "updated_at": NOW,
                "valid_until": "2026-11-21",
            }
        )

        await store.write("demo/fact/date-only", node, BODY)

        async with AsyncSession(engine) as session:
            stored = (
                await session.execute(
                    select(KbNode.valid_until).where(KbNode.id == "demo/fact/date-only")
                )
            ).scalar_one()
        assert stored is not None
        assert stored.astimezone(UTC) == datetime(2026, 11, 21, tzinfo=UTC)
    finally:
        await engine.dispose()


async def test_node_round_trip_keeps_body_and_fields(store: PgKnowledgeStore) -> None:
    await store.register_project(PROJECT, name="演示库")
    revision = await store.write("demo/fact/alpha", _node(), BODY)

    assert REVISION_RE.fullmatch(revision)
    node, body = await store.read("demo/fact/alpha")
    assert body == BODY
    assert node.id == "demo/fact/alpha"
    assert node.project == PROJECT
    assert node.title == "节点标题"
    assert node.tags == ["中文标签", "tag-b"]
    assert node.kind is Kind.FACT
    assert node.tier is Tier.CANDIDATE
    assert node.source == [SourceRef(type=SourceKind.SESSION, ref="sessions/a.jsonl")]
    assert node.created_at == NOW


async def test_every_write_regenerates_revision_even_with_same_content(
    store: PgKnowledgeStore,
) -> None:
    """契约 §3：同一内容重写也产生新 revision。"""
    await store.register_project(PROJECT, name="演示库")
    first = await store.write("demo/fact/alpha", _node(), BODY)
    second = await store.write("demo/fact/alpha", _node(), BODY)

    assert REVISION_RE.fullmatch(first) and REVISION_RE.fullmatch(second)
    assert first != second
    assert await store.revision("demo/fact/alpha") == second


async def test_write_appends_full_snapshot_history(
    engine: AsyncEngine, store: PgKnowledgeStore
) -> None:
    """规格 §3.4：每次写入同一事务内追加一条，`before/after` 含正文。"""
    await store.register_project(PROJECT, name="演示库")
    await store.write("demo/fact/alpha", _node(), BODY)
    await store.write(
        "demo/fact/alpha", _node(), BODY + "\n追加一行。\n", actor="ui:alice", reason="update"
    )

    async with AsyncSession(engine) as session:
        rows = (
            await session.scalars(
                select(KbNodeRevision)
                .where(KbNodeRevision.node_id == "demo/fact/alpha")
                .order_by(KbNodeRevision.id)
            )
        ).all()
    assert len(rows) == 2
    assert rows[0].before == {}
    assert rows[0].after["body"] == BODY
    assert rows[0].after["title"] == "节点标题"
    assert rows[1].before["body"] == BODY
    assert rows[1].after["body"] == BODY + "\n追加一行。\n"
    assert (rows[1].actor, rows[1].reason) == ("ui:alice", "update")
    assert rows[1].tier == "candidate"


async def test_list_ids_skips_archived_and_filters_by_project(store: PgKnowledgeStore) -> None:
    await store.register_project(PROJECT, name="演示库")
    await store.register_project("other", name="另一个")
    await store.write("demo/fact/alpha", _node(), BODY)
    await store.write("demo/fact/beta", _node("demo/fact/beta"), BODY)
    await store.write("other/fact/gamma", _node("other/fact/gamma", "other"), BODY)
    await store.archive_node("demo/fact/beta")

    assert await store.list_ids() == ["demo/fact/alpha", "other/fact/gamma"]
    assert await store.list_ids("demo") == ["demo/fact/alpha"]
    assert await store.exists("demo/fact/beta") is False
    assert await store.exists("demo/fact/alpha") is True


async def test_archived_node_row_is_kept(engine: AsyncEngine, store: PgKnowledgeStore) -> None:
    """软删只置 `archived_at`，行与正文不丢（永不硬删）。"""
    await store.register_project(PROJECT, name="演示库")
    await store.write("demo/fact/alpha", _node(), BODY)
    await store.archive_node("demo/fact/alpha")

    async with AsyncSession(engine) as session:
        row = await session.get(KbNode, "demo/fact/alpha")
    assert row is not None
    assert row.archived_at is not None
    assert row.body == BODY


async def test_edges_dedupe_on_triple_and_keep_dangling(
    engine: AsyncEngine, store: PgKnowledgeStore
) -> None:
    """悬空边原样保留；同一三元组重复追加只算一次。"""
    await store.register_project(PROJECT, name="演示库")
    await store.write("demo/fact/alpha", _node(), BODY)
    edges = [
        {
            "source": "demo/fact/alpha",
            "predicate": Predicate.RELATED_TO,
            "target": "demo/missing/x",
        },
        {
            "source": "demo/fact/alpha",
            "predicate": Predicate.RELATED_TO,
            "target": "demo/missing/x",
        },
        {"source": "demo/fact/alpha", "predicate": Predicate.ABOUT, "target": "alpha"},
    ]
    added = await store.append_edges(PROJECT, edges, source_doc="demo/fact/alpha")
    again = await store.append_edges(PROJECT, edges, source_doc="demo/fact/alpha")

    assert (added, again) == (2, 0)
    records = await store.edges()
    assert sorted((r["source"], r["predicate"], r["target"]) for r in records) == [
        ("demo/fact/alpha", "about", "alpha"),
        ("demo/fact/alpha", "related_to", "demo/missing/x"),
    ]
    async with AsyncSession(engine) as session:
        count = await session.scalar(select(func.count()).select_from(KbEdge))
    assert count == 2


async def test_read_and_revision_missing_node(store: PgKnowledgeStore) -> None:
    await store.register_project(PROJECT, name="演示库")
    assert await store.revision("demo/fact/none") is None
    with pytest.raises(NodeMissing):
        await store.read("demo/fact/none")


async def test_stale_expected_revision_is_rejected_and_data_unchanged(
    store: PgKnowledgeStore,
) -> None:
    """规格 §8.3：旧 revision 更新返回冲突，库里仍是后来者的内容。"""
    await store.register_project(PROJECT, name="演示库")
    stale = await store.write("demo/fact/alpha", _node(), BODY)
    fresh = await store.write("demo/fact/alpha", _node(title="较新标题"), BODY)

    with pytest.raises(RevisionConflict) as err:
        await store.write("demo/fact/alpha", _node(title="陈旧写入"), BODY, expected_revision=stale)
    assert err.value.current == fresh
    node, _ = await store.read("demo/fact/alpha")
    assert node.title == "较新标题"


async def test_pending_archive_blocks_writes_and_status(
    engine: AsyncEngine, store: PgKnowledgeStore
) -> None:
    """规格 §8.7：归档事务未完成时普通写入拿 `pending`，恢复流程不受阻。"""
    await store.register_project(PROJECT, name="演示库")
    async with AsyncSession(engine) as session:
        session.add(
            KbArchive(
                archive_id="0" * 32,
                project=PROJECT,
                status="pending",
                snapshot=b"",
                archived_count=0,
                removed_edges=0,
                created_at=NOW,
            )
        )
        await session.commit()

    with pytest.raises(WriteDeferred) as err:
        async with store.write_scope(timeout=0):
            pass
    assert err.value.reason == "pending"

    with pytest.raises(TargetUnavailable):
        await store.project_status(PROJECT)

    async with store.write_scope(timeout=0, recovery=True):
        pass


async def test_concurrent_writes_only_one_wins(store: PgKnowledgeStore) -> None:
    """规格 §7：并发写同一节点靠 revision 比较串行化，失败方拿冲突而不是覆盖。"""
    import asyncio

    await store.register_project(PROJECT, name="演示库")
    base = await store.write("demo/fact/alpha", _node(), BODY)

    async def attempt(title: str) -> str:
        try:
            return await store.write(
                "demo/fact/alpha", _node(title=title), BODY, expected_revision=base
            )
        except RevisionConflict:
            return "conflict"

    results = await asyncio.gather(attempt("写入 A"), attempt("写入 B"))
    assert results.count("conflict") == 1
    winner = next(item for item in results if item != "conflict")
    assert REVISION_RE.fullmatch(winner)
    node, _ = await store.read("demo/fact/alpha")
    assert node.title in {"写入 A", "写入 B"}
