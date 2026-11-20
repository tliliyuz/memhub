"""知识库目录：发现、命名、子图隔离与边解析（异步 IO）。"""

from __future__ import annotations

from pathlib import Path

import pytest
from anyio import Path as AsyncPath

from memhub.contract import Edge, Kind, Predicate
from memhub.kb import archive, catalog, manage, query
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
    # 已存在是冲突（409/1010）；InvalidError（422/1012）只留给 id 不合法。
    with pytest.raises(manage.ConflictError):
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


async def test_delete_kb_archives_nodes_and_removes_dir(store: KnowledgeStore) -> None:
    a = await _node(store, project="old-lib", title="旧库事实甲", slug="old-fact-a")
    b = await _node(store, project="old-lib", title="旧库事实乙", slug="old-fact-b")
    await manage.replace_out_edges(
        store, a, [Edge(source=a, predicate=Predicate.RELATED_TO, target=b)]
    )

    result = await catalog.delete_kb(store, "old-lib", actor="test")

    assert result["archived_count"] == 2
    assert result["removed_edges"] == 1
    assert await store.list_ids() == []
    assert (await catalog.list_kbs(store))["total"] == 0
    assert (await manage.list_trash(store))["total"] == 0
    assert (await catalog.list_archives(store))["items"][0]["archive_id"] == result["archive_id"]
    restored = await catalog.restore_kb(store, result["archive_id"])
    assert restored["restored_edges"] == 1
    assert await store.list_ids() == sorted([a, b])
    assert (await catalog.list_archives(store))["total"] == 0
    assert (await catalog.graph(store, "old-lib"))["edges"] == [
        {"source": a, "target": b, "predicate": "related_to"}
    ]
    assert not await AsyncPath(store.root / ".kbs.json").exists()


async def test_delete_kb_rejects_unrecognized_files_before_archiving(
    store: KnowledgeStore,
) -> None:
    node_id = await _node(store, project="mixed", title="保留节点", slug="keep")
    await AsyncPath(store.root / "mixed" / "README.md").write_text("未识别的文件")

    with pytest.raises(manage.ConflictError):
        await catalog.delete_kb(store, "mixed")

    assert await store.exists(node_id)
    assert (await manage.list_trash(store))["total"] == 0


async def test_delete_kb_unknown_is_not_found(store: KnowledgeStore) -> None:
    with pytest.raises(manage.NotFoundError):
        await catalog.delete_kb(store, "nope")


async def test_delete_kb_keeps_other_libs_and_edges(store: KnowledgeStore) -> None:
    a = await _node(store, project="gone", title="即将删除", slug="gone-fact")
    keep = await _node(store, project="stay", title="保留事实", slug="stay-fact")
    await manage.replace_out_edges(
        store, a, [Edge(source=a, predicate=Predicate.RELATED_TO, target=keep)]
    )
    # 跨库引用：边写在 stay 自己的边文件里，指向即将被删的库。
    await manage.replace_out_edges(
        store, keep, [Edge(source=keep, predicate=Predicate.ABOUT, target=a)]
    )

    result = await catalog.delete_kb(store, "gone")

    # 两处边（被删库自身的 + 别的库指向它的）都算进计数
    assert result["removed_edges"] == 2
    # 与被删节点相连的边清掉，但目标节点本身完好
    assert (await manage.get_node(store, keep))["frontmatter"]["title"] == "保留事实"
    sub = await catalog.graph(store, "stay")
    assert len(sub["nodes"]) == 1 and sub["edges"] == []
    # 跨库边文件被就地清理，不留永远解析不到的悬空边
    stay_edges = await AsyncPath(store.edges_path("stay")).read_text(encoding="utf-8")
    assert a not in stay_edges


async def test_restore_preserves_bytes_registry_and_later_foreign_edges(
    store: KnowledgeStore,
) -> None:
    entry = await catalog.create_kb(store, kb_id="first", name="样本库", description="样本说明")
    a = await _node(store, project="first", title="A", slug="a")
    b = await _node(store, project="first", title="B", slug="b")
    c = await _node(store, project="second", title="C", slug="c")
    d = await _node(store, project="second", title="D", slug="d")
    node_path = AsyncPath(store.path_for(a))
    node_bytes = (await node_path.read_bytes()).replace(b"\n", b"\r\n") + b"\r\n"
    await node_path.write_bytes(node_bytes)
    await store.append_edges(
        "first", [Edge(source=a, predicate=Predicate.ABOUT, target=b)], "local-source"
    )
    await store.append_edges(
        "second", [Edge(source=c, predicate=Predicate.ABOUT, target="a")], "foreign-source"
    )
    local_path, foreign_path = (AsyncPath(store.edges_path(p)) for p in ("first", "second"))
    local_bytes = await local_path.read_bytes()
    foreign_bytes = await foreign_path.read_bytes()
    result = await catalog.delete_kb(store, "first")
    assert (await query.edge_index(store)).edges == []
    await store.append_edges(
        "second", [Edge(source=c, predicate=Predicate.RELATED_TO, target=d)], "new-source"
    )
    later_bytes = await foreign_path.read_bytes()
    await catalog.restore_kb(store, result["archive_id"])
    assert await node_path.read_bytes() == node_bytes
    assert await local_path.read_bytes() == local_bytes
    assert await foreign_path.read_bytes() == later_bytes + foreign_bytes
    assert (await catalog._load(store))["first"] == entry
    assert len((await query.edge_index(store)).edges) == 3


async def test_restore_missing_foreign_endpoint_keeps_archive(store: KnowledgeStore) -> None:
    a = await _node(store, project="first", title="A", slug="a")
    b = await _node(store, project="second", title="B", slug="b")
    await store.append_edges(
        "first", [Edge(source=a, predicate=Predicate.ABOUT, target=b)], "sample"
    )
    result = await catalog.delete_kb(store, "first")
    await AsyncPath(store.path_for(b)).unlink()
    with pytest.raises(manage.ConflictError):
        await catalog.restore_kb(store, result["archive_id"])
    assert not await AsyncPath(store.root / "first").exists()
    assert (await catalog.list_archives(store))["total"] == 1
    assert not await AsyncPath(store.root / archive.PENDING).exists()


async def test_archive_empty_library_and_reject_occupied_destination(store: KnowledgeStore) -> None:
    entry = await catalog.create_kb(store, kb_id="empty", name="空库")
    result = await catalog.delete_kb(store, "empty")
    assert result["archived_count"] == 0
    with pytest.raises(manage.WriteDeferred):
        await catalog.create_kb(store, kb_id="empty")
    dest = AsyncPath(store.root / "empty")
    await dest.mkdir()
    with pytest.raises(manage.ConflictError):
        await catalog.restore_kb(store, result["archive_id"])
    await dest.rmdir()
    await catalog.restore_kb(store, result["archive_id"])
    assert await dest.is_dir()
    assert (await catalog._load(store))["empty"] == entry


async def test_archive_refuses_to_resolve_previously_ambiguous_edge(store: KnowledgeStore) -> None:
    await _node(store, project="first", title="A", slug="shared")
    other = await _node(store, project="second", title="B", slug="shared")
    await store.append_edges(
        "second", [Edge(source=other, predicate=Predicate.ABOUT, target="shared")], "sample"
    )
    path = AsyncPath(store.edges_path("second"))
    original = await path.read_bytes()
    with pytest.raises(manage.ConflictError):
        await catalog.delete_kb(store, "first")
    assert await path.read_bytes() == original
    assert (await catalog.list_archives(store))["total"] == 0
