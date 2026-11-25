"""投影与 PG 真源的接线契约（规格 §9.2.4：kb-api 只跑 PG 存储）。"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from memhub.contract import Kind, NodeFrontmatter, SourceKind, SourceRef, Tier
from memhub.kb.models import Base
from memhub.kb.pgstore import PgKnowledgeStore
from memhub.kb.projection import build_graph
from memhub.kb.session import create_sessionmaker

NOW = datetime(2026, 11, 25, 9, 30, tzinfo=UTC)
PROJECT = "demo"


def _node(node_id: str, title: str) -> NodeFrontmatter:
    return NodeFrontmatter(
        id=node_id,
        project=PROJECT,
        kind=Kind.FACT,
        title=title,
        created_at=NOW,
        updated_at=NOW,
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


async def test_build_graph_reads_nodes_and_edges_from_store(store: PgKnowledgeStore) -> None:
    """投影不再扫 `_edges.jsonl`：节点与边都从 `kb_*` 表读。"""
    await store.register_project(PROJECT, name="演示库")
    await store.write("demo/fact/alpha", _node("demo/fact/alpha", "甲甲"), "正文甲")
    await store.write("demo/fact/beta", _node("demo/fact/beta", "乙乙"), "正文乙")
    await store.append_edges(
        PROJECT,
        [
            {"source": "demo/fact/alpha", "predicate": "supports", "target": "beta"},
            {"source": "demo/fact/alpha", "predicate": "supports", "target": "missing"},
        ],
    )

    graph, report = await build_graph(store)

    assert graph is not None
    assert report.nodes == 2
    assert report.edges == 1
    assert report.unresolved == ["demo/fact/alpha -supports-> missing"]


async def test_latest_write_tracks_revisions_and_edges(store: PgKnowledgeStore) -> None:
    """投影过期判断需要真源的最近写入时间；文件版靠 mtime，PG 版靠表内时间。"""
    await store.register_project(PROJECT, name="演示库")
    assert await store.latest_write() is None

    await store.write("demo/fact/alpha", _node("demo/fact/alpha", "甲甲"), "正文甲")
    first = await store.latest_write()
    assert first is not None

    await store.append_edges(
        PROJECT, [{"source": "demo/fact/alpha", "predicate": "supports", "target": "beta"}]
    )
    second = await store.latest_write()
    assert second is not None and second >= first
