"""PG 存储与文件存储的只读行为等价（规格 §8.2/§8.4：调用方无感切换）。

`query` 只依赖 `KnowledgeReader` 协议，这里用同一份场景分别喂给
`KnowledgeStore`（文件）与 `PgKnowledgeStore`（库），断言检索、读取、邻接、
治理清单给出的结论一致——不一致即为行为变更，必须回到规格裁决。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from anyio import Path as AsyncPath
from sqlalchemy.ext.asyncio import AsyncEngine

from memhub.contract import Edge, Kind, NodeFrontmatter, Predicate, Tier
from memhub.kb.models import Base
from memhub.kb.pgstore import PgKnowledgeStore
from memhub.kb.query import audit_list, read_node, related, search
from memhub.kb.session import create_sessionmaker
from memhub.kb.store import KnowledgeStore

NOW = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)


def _node(
    node_id: str,
    *,
    title: str,
    kind: Kind = Kind.FACT,
    tags: list[str] | None = None,
    tier: Tier = Tier.CANDIDATE,
) -> NodeFrontmatter:
    return NodeFrontmatter(
        id=node_id,
        project=node_id.split("/")[0],
        kind=kind,
        title=title,
        tier=tier,
        tags=tags or [],
        created_at=NOW,
        updated_at=NOW,
    )


# 同一场景：跨库同名、标签命中、出边、悬空边。
SCENARIO = [
    (
        _node("demo/fact/proxy-502", title="HTTPX trust_env 导致代理 502", tags=["httpx", "proxy"]),
        "代理失败时先看 trust_env 是否被环境代理污染。",
    ),
    (
        _node(
            "demo/pitfall/no-proxy",
            title="不要在请求路径上放 Proxy",
            kind=Kind.PITFALL,
            tags=["proxy"],
        ),
        "Proxy 站会放大故障。",
    ),
    (
        _node("other/fact/same-word", title="代理在另一个项目里的用法"),
        "这个节点只属于 other 项目。",
    ),
]
EDGES = [
    Edge(
        source="demo/fact/proxy-502",
        predicate=Predicate.ABOUT,
        target="demo/pitfall/no-proxy",
    ),
    Edge(source="demo/fact/proxy-502", predicate=Predicate.RELATED_TO, target="demo/missing/x"),
]


@pytest_asyncio.fixture(params=["file", "pg"])
async def reader(
    request: pytest.FixtureRequest, tmp_path: Path, kb_engine: AsyncEngine
) -> AsyncIterator[KnowledgeStore | PgKnowledgeStore]:
    if request.param == "file":
        file_store = KnowledgeStore(tmp_path)
        for project in ("demo", "other"):
            await AsyncPath(tmp_path / project).mkdir(exist_ok=True)
        for node, body in SCENARIO:
            await file_store.write(node.id, node, body)
        await file_store.append_edges("demo", EDGES, source_doc="demo/fact/proxy-502")
        yield file_store
        return

    async with kb_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    pg = PgKnowledgeStore(create_sessionmaker(kb_engine))
    for project in ("demo", "other"):
        await pg.register_project(project, name=project)
    for node, body in SCENARIO:
        await pg.write(node.id, node, body)
    await pg.append_edges("demo", EDGES, source_doc="demo/fact/proxy-502")
    yield pg


async def test_search_conclusions_match(reader: KnowledgeStore | PgKnowledgeStore) -> None:
    cases = [
        await search(reader, "代理", tier="all"),
        await search(reader, "proxy", tier="all"),
        await search(reader, "代理", tier="all", project="other"),
        await search(reader, "proxy", tier="all", kinds=["pitfall"]),
        await search(reader, "httpx trust_env", tier="all"),
    ]
    for got in cases:
        if not got["results"]:
            assert "hint" in got
            continue
        assert got["results"][0]["matched"] == "bm25"
        assert all(0.0 <= item["score"] <= 1.0 for item in got["results"])
        ordered = [item["score"] for item in got["results"]]
        assert ordered == sorted(ordered, reverse=True)


async def test_read_node_shape_matches(reader: KnowledgeStore | PgKnowledgeStore) -> None:
    detail = await read_node(reader, "demo/fact/proxy-502")
    assert detail["frontmatter"]["id"] == "demo/fact/proxy-502"
    assert detail["frontmatter"]["title"] == "HTTPX trust_env 导致代理 502"
    assert "trust_env" in detail["body"]
    # 出边只列已解析的边；悬空边归 audit 的 broken_link，不进邻接。
    assert [edge["predicate"] for edge in detail["edges"]["out"]] == ["about"]
    target = await read_node(reader, "demo/pitfall/no-proxy")
    assert target["edges"]["in"] == [{"predicate": "about", "source": "demo/fact/proxy-502"}]


async def test_related_subgraph_matches(reader: KnowledgeStore | PgKnowledgeStore) -> None:
    graph = await related(reader, "demo/pitfall/no-proxy")
    assert {node["id"] for node in graph["nodes"]} == {
        "demo/pitfall/no-proxy",
        "demo/fact/proxy-502",
    }
    filtered = await related(reader, "demo/pitfall/no-proxy", predicates=["depends_on"])
    assert [node["id"] for node in filtered["nodes"]] == ["demo/pitfall/no-proxy"]


async def test_audit_lists_dangling_edge_as_broken_link(
    reader: KnowledgeStore | PgKnowledgeStore,
) -> None:
    """悬空边在两种存储下都必须被识别为断链，不能被静默丢弃（ADR-0013 §8）。"""
    report = await audit_list(reader, limit=50)
    broken = [issue for issue in report["issues"] if issue["type"] == "broken_link"]
    assert broken, report
    assert any("demo/missing/x" in str(issue.get("target", "")) for issue in broken)


async def test_recently_updated_nodes_do_not_look_stale(
    reader: KnowledgeStore | PgKnowledgeStore,
) -> None:
    """`stale` 以 `updated_at` 为判据；迁移后时间列口径不变。"""
    report = await audit_list(reader, limit=50)
    stale = [issue for issue in report["issues"] if issue["type"] == "stale"]
    assert stale == []
    assert datetime.now(UTC) - NOW < timedelta(days=30)
