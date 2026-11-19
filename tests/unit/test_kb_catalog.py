"""知识库目录：发现、命名、子图隔离与边解析。"""

from __future__ import annotations

from pathlib import Path

import pytest

from memhub.contract import Edge, Kind, Predicate
from memhub.kb import catalog, manage
from memhub.kb.store import KnowledgeStore


@pytest.fixture
def store(tmp_path: Path) -> KnowledgeStore:
    root = tmp_path / "knowledge"
    root.mkdir()
    return KnowledgeStore(root)


def _node(store: KnowledgeStore, *, project: str, title: str, **overrides: object) -> str:
    draft = manage.NodeDraft(
        kind=Kind.FACT,
        title=title,
        body=f"{title} 的正文。",
        project=project,
        tags=["tag"],
        **overrides,  # type: ignore[arg-type]
    )
    return str(manage.create_node(store, draft)["id"])


def test_list_kbs_discovers_directories_and_merges_registry(store: KnowledgeStore) -> None:
    _node(store, project="sdp-tag", title="sdp-tag 事实")
    _node(store, project="memhub", title="memhub 事实")
    catalog.create_kb(store, kb_id="cloudworld", name="CloudWorld", description="云世界")

    items = catalog.list_kbs(store)["items"]
    by_id = {item["id"]: item for item in items}

    assert set(by_id) == {"sdp-tag", "memhub", "cloudworld"}
    assert by_id["cloudworld"]["name"] == "CloudWorld"
    assert by_id["cloudworld"]["description"] == "云世界"
    assert by_id["sdp-tag"]["name"] == "sdp-tag"
    assert by_id["sdp-tag"]["nodes"] == 1
    assert by_id["sdp-tag"]["updated_at"]


def test_create_kb_validates_id_and_duplicates(store: KnowledgeStore) -> None:
    with pytest.raises(manage.InvalidError):
        catalog.create_kb(store, kb_id="Bad Id")
    catalog.create_kb(store, kb_id="sdp-tag")
    with pytest.raises(manage.InvalidError):
        catalog.create_kb(store, kb_id="sdp-tag")


def test_update_kb_requires_existing(store: KnowledgeStore) -> None:
    with pytest.raises(manage.NotFoundError):
        catalog.update_kb(store, "nope", name="x")


def test_graph_is_scoped_to_one_kb_and_resolves_slug(store: KnowledgeStore) -> None:
    anchor = _node(store, project="sdp-tag", title="三评架构", slug="three-review")
    other = _node(store, project="sdp-tag", title="仲裁口径", slug="arbitration")
    foreign = _node(store, project="memhub", title="别的库", slug="foreign")

    manage.replace_out_edges(
        store,
        anchor,
        [Edge(source=anchor, predicate=Predicate.ABOUT, target="arbitration")],
    )

    sub = catalog.graph(store, "sdp-tag")
    ids = {node["id"] for node in sub["nodes"]}

    assert ids == {anchor, other}
    assert foreign not in ids
    assert sub["edges"] == [
        {"source": anchor, "target": other, "predicate": "about"},
    ]
    degrees = {node["id"]: node["degree"] for node in sub["nodes"]}
    assert degrees[anchor] == 1 and degrees[other] == 1
    assert sub["unresolved_edges"] == 0


def test_graph_counts_unresolved_edges(store: KnowledgeStore) -> None:
    anchor = _node(store, project="sdp-tag", title="孤立事实", slug="lonely")
    manage.replace_out_edges(
        store,
        anchor,
        [Edge(source=anchor, predicate=Predicate.RELATED_TO, target="missing-node")],
    )

    sub = catalog.graph(store, "sdp-tag")
    assert sub["edges"] == []
    assert sub["unresolved_edges"] == 1


def test_graph_unknown_kb_is_not_found(store: KnowledgeStore) -> None:
    with pytest.raises(manage.NotFoundError):
        catalog.graph(store, "nope")
