"""知识库生命周期与整库归档在文件存储与 PG 存储下行为等价（规格 §8.7）。

覆盖：登记与改名、整库归档后节点从检索消失、恢复后计数与边一致、归档期间
普通写入被 `busy/pending` 等价错误阻断。文件侧仍按 `_kb_archives/*/active.json`
+ `snapshot.zip` 落盘（迁移工具读取该格式），PG 侧落 `kb_archives` 与
`kb_projects.archived_at`。
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine

from memhub.contract import Edge, Kind, Predicate
from memhub.kb import catalog, manage, query
from memhub.kb.models import Base
from memhub.kb.pgstore import PgKnowledgeStore
from memhub.kb.session import create_sessionmaker
from memhub.kb.store import KnowledgeStore

ARCHIVE_RE = re.compile(r"^[0-9a-f]{32}$")
PROJECT = "demo"
KEEP = "stay"


@pytest_asyncio.fixture(params=["file", "pg"])
async def store(
    request: pytest.FixtureRequest, tmp_path: Path, kb_engine: AsyncEngine
) -> AsyncIterator[KnowledgeStore | PgKnowledgeStore]:
    if request.param == "file":
        kb = KnowledgeStore(tmp_path / "knowledge")
        await catalog.create_kb(kb, kb_id=PROJECT, name="演示库", description="演示说明")
        await catalog.create_kb(kb, kb_id=KEEP, name="保留库")
        yield kb
        return

    async with kb_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    pg = PgKnowledgeStore(create_sessionmaker(kb_engine))
    await pg.register_project(PROJECT, name="演示库", description="演示说明")
    await pg.register_project(KEEP, name="保留库")
    yield pg


def _draft(project: str, *, title: str, slug: str) -> manage.NodeDraft:
    return manage.NodeDraft(
        kind=Kind.FACT, title=title, body=f"{title} 的正文。", project=project, slug=slug
    )


async def _nodes(store: Any, project: str) -> dict[str, str]:
    first = await manage.create_node(store, _draft(project, title="甲", slug="fact-a"))
    second = await manage.create_node(store, _draft(project, title="乙", slug="fact-b"))
    return {"a": str(first["id"]), "b": str(second["id"])}


async def test_list_kbs_exposes_registered_projects(
    store: KnowledgeStore | PgKnowledgeStore,
) -> None:
    items = (await catalog.list_kbs(store))["items"]
    by_id = {item["id"]: item for item in items}
    assert set(by_id) == {PROJECT, KEEP}
    assert by_id[PROJECT]["name"] == "演示库"
    assert by_id[PROJECT]["description"] == "演示说明"
    assert by_id[PROJECT]["nodes"] == 0
    assert by_id[PROJECT]["edges"] == 0


async def test_create_and_update_kb(store: KnowledgeStore | PgKnowledgeStore) -> None:
    created = await catalog.create_kb(store, kb_id="second", name="第二库", description="说明")
    assert created["name"] == "第二库"
    with pytest.raises(manage.ConflictError):
        await catalog.create_kb(store, kb_id="second")
    with pytest.raises(manage.InvalidError):
        await catalog.create_kb(store, kb_id="Bad Id")

    entry = await catalog.update_kb(store, "second", name="改名后", description="新说明")
    assert entry["name"] == "改名后"
    by_id = {item["id"]: item for item in (await catalog.list_kbs(store))["items"]}
    assert by_id["second"]["name"] == "改名后"
    assert by_id["second"]["description"] == "新说明"

    with pytest.raises(manage.NotFoundError):
        await catalog.update_kb(store, "nope", name="x")


async def test_archive_and_restore_round_trip(
    store: KnowledgeStore | PgKnowledgeStore,
) -> None:
    ids = await _nodes(store, PROJECT)
    await manage.replace_out_edges(
        store,
        ids["a"],
        [Edge(source=ids["a"], predicate=Predicate.RELATED_TO, target=ids["b"])],
    )
    by_id = {item["id"]: item for item in (await catalog.list_kbs(store))["items"]}
    assert by_id[PROJECT]["nodes"] == 2
    assert by_id[PROJECT]["edges"] == 1

    result = await catalog.delete_kb(store, PROJECT, actor="fixture")
    assert ARCHIVE_RE.fullmatch(str(result["archive_id"]))
    assert result["archived_count"] == 2
    assert result["removed_edges"] == 1
    assert result["name"] == "演示库"
    assert result["commit"] is None or isinstance(result["commit"], str)

    assert await store.list_ids() == []
    assert (await catalog.list_kbs(store))["total"] == 1
    assert (await manage.list_trash(store))["total"] == 0
    archives = await catalog.list_archives(store)
    assert archives["total"] == 1
    assert archives["items"][0]["archive_id"] == result["archive_id"]
    assert archives["items"][0]["archived_count"] == 2

    restored = await catalog.restore_kb(store, str(result["archive_id"]))
    assert restored["id"] == PROJECT
    assert restored["restored_count"] == 2
    assert restored["restored_edges"] == 1
    assert await store.list_ids() == sorted(ids.values())
    assert (await catalog.list_archives(store))["total"] == 0
    graph = await catalog.graph(store, PROJECT)
    assert graph["edges"] == [{"source": ids["a"], "target": ids["b"], "predicate": "related_to"}]


async def test_archive_keeps_other_projects_and_cross_edges(
    store: KnowledgeStore | PgKnowledgeStore,
) -> None:
    ids = await _nodes(store, PROJECT)
    keep_id = str(
        (await manage.create_node(store, _draft(KEEP, title="保留事实", slug="stay-fact")))["id"]
    )
    await manage.replace_out_edges(
        store, ids["a"], [Edge(source=ids["a"], predicate=Predicate.RELATED_TO, target=keep_id)]
    )
    await manage.replace_out_edges(
        store, keep_id, [Edge(source=keep_id, predicate=Predicate.ABOUT, target=ids["a"])]
    )

    result = await catalog.delete_kb(store, PROJECT)
    # 被删库自身的边 + 别的库指向它的边都算进删除计数。
    assert result["removed_edges"] == 2
    assert await store.exists(keep_id)
    assert (await catalog.graph(store, KEEP))["edges"] == []

    await catalog.restore_kb(store, str(result["archive_id"]))
    assert await store.list_ids() == sorted([*ids.values(), keep_id])
    # 子图只看本库：跨库端点仍按悬空边计，但边本身必须被恢复。
    assert (await catalog.graph(store, KEEP))["unresolved_edges"] == 1
    assert len((await query.edge_index(store)).edges) == 2


async def test_create_kb_after_archive_is_deferred(
    store: KnowledgeStore | PgKnowledgeStore,
) -> None:
    await catalog.create_kb(store, kb_id="empty", name="空库")
    result = await catalog.delete_kb(store, "empty")
    assert result["archived_count"] == 0

    with pytest.raises(manage.WriteDeferred) as deferred:
        await catalog.create_kb(store, kb_id="empty")
    assert deferred.value.reason == "archived"

    await catalog.restore_kb(store, str(result["archive_id"]))
    assert (await catalog.list_kbs(store))["total"] == 3
    with pytest.raises(manage.ConflictError):
        await catalog.create_kb(store, kb_id="empty", name="空库")


async def test_archive_unknown_project_not_found(
    store: KnowledgeStore | PgKnowledgeStore,
) -> None:
    with pytest.raises(manage.NotFoundError):
        await catalog.delete_kb(store, "nope")
    with pytest.raises(manage.NotFoundError):
        await catalog.restore_kb(store, "0" * 32)


async def test_graph_is_scoped_and_resolves_alias(
    store: KnowledgeStore | PgKnowledgeStore,
) -> None:
    ids = await _nodes(store, PROJECT)
    foreign = await manage.create_node(store, _draft(KEEP, title="别的库", slug="foreign"))
    await manage.replace_out_edges(
        store,
        ids["a"],
        [Edge(source=ids["a"], predicate=Predicate.ABOUT, target="fact-b")],
    )

    sub = await catalog.graph(store, PROJECT)
    assert {node["id"] for node in sub["nodes"]} == set(ids.values())
    assert foreign["id"] not in {node["id"] for node in sub["nodes"]}
    assert sub["edges"] == [{"source": ids["a"], "target": ids["b"], "predicate": "about"}]
    assert sub["unresolved_edges"] == 0

    with pytest.raises(manage.NotFoundError):
        await catalog.graph(store, "nope")
