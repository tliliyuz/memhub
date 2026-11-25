"""写库半段与 `--verify-only` 的 PG 契约（规格 §5 第 6–9 步，验收条件 §8.1）。

做法：固定 fixture 目录 → `parse_tree` → `apply_plan` 写进隔离 schema →
`read_stored` + `diff_plan` 比对；再跑一次验证幂等。缺 `MEMHUB_TEST_DB_URL`
时整组 skip，**不计为通过**（规格 §8.10）。
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from memhub.kb import catalog
from memhub.kb.migrate import parse_tree
from memhub.kb.migrate_db import StoredKnowledge, apply_plan, diff_plan, read_stored
from memhub.kb.models import Base, KbArchive, KbEdge, KbNode, KbNodeRevision, KbProject
from memhub.kb.store import KnowledgeStore

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "knowledge_tree"


def _tree(tmp_path: Path, name: str = "knowledge") -> Path:
    root = tmp_path / name
    shutil.copytree(FIXTURE, root)
    return root


async def _count(engine: AsyncEngine, model: type[Base]) -> int:
    async with AsyncSession(engine) as session:
        return int(await session.scalar(select(func.count()).select_from(model.__table__)) or 0)


async def _engine_with_tables(kb_engine: AsyncEngine) -> AsyncEngine:
    async with kb_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return kb_engine


async def test_apply_then_verify_passes(tmp_path: Path, kb_engine: AsyncEngine) -> None:
    engine = await _engine_with_tables(kb_engine)
    plan = await parse_tree(_tree(tmp_path))

    await apply_plan(engine, plan)
    report = diff_plan(plan, await read_stored(engine))

    assert report.ok, report.as_dict()
    assert await _count(engine, KbProject) == len(plan.projects)
    assert await _count(engine, KbNode) == len(plan.nodes)
    assert await _count(engine, KbEdge) == len(plan.edges)


async def test_apply_is_idempotent(tmp_path: Path, kb_engine: AsyncEngine) -> None:
    """重复运行以 id / 三元组 upsert，节点、边、项目计数不变（规格 §5 第 9 步）。"""
    engine = await _engine_with_tables(kb_engine)
    plan = await parse_tree(_tree(tmp_path))

    await apply_plan(engine, plan)
    first = (
        await _count(engine, KbProject),
        await _count(engine, KbNode),
        await _count(engine, KbEdge),
        await _count(engine, KbNodeRevision),
    )
    await apply_plan(engine, plan)
    second = (
        await _count(engine, KbProject),
        await _count(engine, KbNode),
        await _count(engine, KbEdge),
        await _count(engine, KbNodeRevision),
    )

    assert first == second


async def test_dangling_edge_is_written_verbatim(tmp_path: Path, kb_engine: AsyncEngine) -> None:
    """悬空边必须原样进 `kb_edges`，不得因校验丢弃（ADR-0013 §8）。"""
    engine = await _engine_with_tables(kb_engine)
    plan = await parse_tree(_tree(tmp_path))

    await apply_plan(engine, plan)

    async with AsyncSession(engine) as session:
        targets = set((await session.execute(select(KbEdge.target))).scalars())
    assert "nowhere" in targets


async def test_unregistered_project_row_is_written(tmp_path: Path, kb_engine: AsyncEngine) -> None:
    """未登记库要建 `kb_projects` 行，否则节点外键无主（规格 §5 第 4 步）。"""
    engine = await _engine_with_tables(kb_engine)
    plan = await parse_tree(_tree(tmp_path))

    await apply_plan(engine, plan)

    async with AsyncSession(engine) as session:
        ids = set((await session.execute(select(KbProject.id))).scalars())
    assert {"demo", "orphan"} <= ids


async def test_projects_verify_clean_right_after_apply(
    tmp_path: Path, kb_engine: AsyncEngine
) -> None:
    """先写库再校验必须一次通过：项目时间若用扫描时刻，每次解析哈希都变，永远不通过。"""
    engine = await _engine_with_tables(kb_engine)

    await apply_plan(engine, await parse_tree(_tree(tmp_path)))
    report = diff_plan(
        await parse_tree(_tree(tmp_path, "knowledge-again")), await read_stored(engine)
    )

    assert report.ok, report.as_dict()


async def test_trash_delete_fact_is_recorded_in_revisions(
    tmp_path: Path, kb_engine: AsyncEngine
) -> None:
    """回收站的删除时间与 actor/reason 必须留痕；这是替代 git 后唯一的删除审计。"""
    from memhub.kb import manage

    root = _tree(tmp_path)
    store = KnowledgeStore(root)
    revision = await manage.node_revision(store, "demo/fact/alpha")
    assert revision is not None
    await manage.delete_node(
        store, "demo/fact/alpha", expected_revision=revision, reason="合成删除", actor="ui:test"
    )
    engine = await _engine_with_tables(kb_engine)
    plan = await parse_tree(root)

    await apply_plan(engine, plan)

    async with AsyncSession(engine) as session:
        rows = (
            (
                await session.execute(
                    select(KbNodeRevision).where(KbNodeRevision.node_id == "demo/fact/alpha")
                )
            )
            .scalars()
            .all()
        )
    assert [row.actor for row in rows] == ["ui:test"]
    assert [row.reason for row in rows] == ["合成删除"]
    archived = next(node for node in plan.nodes if node["id"] == "demo/fact/alpha")
    assert rows[0].created_at == archived["archived_at"]


async def test_archive_snapshot_is_stored_only_when_requested(
    tmp_path: Path, kb_engine: AsyncEngine
) -> None:
    root = _tree(tmp_path)
    await catalog.delete_kb(KnowledgeStore(root), "demo", actor="ui:test")
    plan = await parse_tree(root)
    assert plan.archives
    engine = await _engine_with_tables(kb_engine)

    await apply_plan(engine, plan, archives="skip")
    assert await _count(engine, KbArchive) == 0

    await apply_plan(engine, plan, archives="migrate")
    assert await _count(engine, KbArchive) == len(plan.archives)
    report = diff_plan(plan, await read_stored(engine), archives="migrate")
    assert report.ok, report.as_dict()


async def test_verify_reports_changed_body(tmp_path: Path, kb_engine: AsyncEngine) -> None:
    """库内被改过正文时，逐节点哈希必须报出来，而不是只比计数。"""
    engine = await _engine_with_tables(kb_engine)
    plan = await parse_tree(_tree(tmp_path))
    await apply_plan(engine, plan)

    stored = await read_stored(engine)
    alpha = dict(stored.nodes["demo/fact/alpha"])
    alpha["body"] = alpha["body"] + "库内被改过。"
    tampered = StoredKnowledge(
        projects=stored.projects,
        nodes={**stored.nodes, alpha["id"]: alpha},
        edges=stored.edges,
        archives=stored.archives,
    )

    report = diff_plan(plan, tampered)

    assert not report.ok
    assert [item["node_id"] for item in report.changed_nodes] == ["demo/fact/alpha"]


async def test_apply_rejects_unknown_archive_mode(tmp_path: Path, kb_engine: AsyncEngine) -> None:
    engine = await _engine_with_tables(kb_engine)
    plan = await parse_tree(_tree(tmp_path))

    with pytest.raises(ValueError):
        await apply_plan(engine, plan, archives="copy")
