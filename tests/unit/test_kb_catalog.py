"""知识库目录：发现、命名、子图隔离与边解析（异步 IO）。"""

from __future__ import annotations

from pathlib import Path

import pytest
from anyio import Path as AsyncPath

from memhub.contract import Edge, Kind, Predicate
from memhub.kb import catalog, manage
from memhub.kb.store import KnowledgeStore


@pytest.fixture
async def store(tmp_path: Path) -> KnowledgeStore:
    root = tmp_path / "knowledge"
    await AsyncPath(root).mkdir()
    return KnowledgeStore(root)


async def _node(store: KnowledgeStore, *, project: str, title: str, **overrides: object) -> str:
    draft = manage.NodeDraft(
        kind=Kind.FACT,
        title=title,
        body=f"{title} 的正文。",
        project=project,
        tags=["tag"],
        **overrides,  # type: ignore[arg-type]
    )
    return str((await manage.create_node(store, draft))["id"])


async def test_list_kbs_discovers_directories_and_merges_registry(
    store: KnowledgeStore,
) -> None:
    await _node(store, project="sdp-tag", title="sdp-tag 事实")
    await _node(store, project="memhub", title="memhub 事实")
    await catalog.create_kb(store, kb_id="cloudworld", name="CloudWorld", description="云世界")

    items = (await catalog.list_kbs(store))["items"]
    by_id = {item["id"]: item for item in items}

    assert set(by_id) == {"sdp-tag", "memhub", "cloudworld"}
    assert by_id["cloudworld"]["name"] == "CloudWorld"
    assert by_id["cloudworld"]["description"] == "云世界"
    assert by_id["sdp-tag"]["name"] == "sdp-tag"
    assert by_id["sdp-tag"]["nodes"] == 1
    assert by_id["sdp-tag"]["updated_at"]


async def test_create_kb_validates_id_and_duplicates(store: KnowledgeStore) -> None:
    with pytest.raises(manage.InvalidError):
        await catalog.create_kb(store, kb_id="Bad Id")
    await catalog.create_kb(store, kb_id="sdp-tag")
    with pytest.raises(manage.InvalidError):
        await catalog.create_kb(store, kb_id="sdp-tag")


async def test_update_kb_requires_existing(store: KnowledgeStore) -> None:
    with pytest.raises(manage.NotFoundError):
        await catalog.update_kb(store, "nope", name="x")


async def test_graph_is_scoped_to_one_kb_and_resolves_slug(store: KnowledgeStore) -> None:
    anchor = await _node(store, project="sdp-tag", title="三评架构", slug="three-review")
    other = await _node(store, project="sdp-tag", title="仲裁口径", slug="arbitration")
    foreign = await _node(store, project="memhub", title="别的库", slug="foreign")

    await manage.replace_out_edges(
        store,
        anchor,
        [Edge(source=anchor, predicate=Predicate.ABOUT, target="arbitration")],
    )

    sub = await catalog.graph(store, "sdp-tag")
    ids = {node["id"] for node in sub["nodes"]}

    assert ids == {anchor, other}
    assert foreign not in ids
    assert sub["edges"] == [
        {"source": anchor, "target": other, "predicate": "about"},
    ]
    degrees = {node["id"]: node["degree"] for node in sub["nodes"]}
    assert degrees[anchor] == 1 and degrees[other] == 1
    assert sub["unresolved_edges"] == 0


async def test_graph_counts_unresolved_edges(store: KnowledgeStore) -> None:
    anchor = await _node(store, project="sdp-tag", title="孤立事实", slug="lonely")
    await manage.replace_out_edges(
        store,
        anchor,
        [Edge(source=anchor, predicate=Predicate.RELATED_TO, target="missing-node")],
    )

    sub = await catalog.graph(store, "sdp-tag")
    assert sub["edges"] == []
    assert sub["unresolved_edges"] == 1


async def test_graph_unknown_kb_is_not_found(store: KnowledgeStore) -> None:
    with pytest.raises(manage.NotFoundError):
        await catalog.graph(store, "nope")
