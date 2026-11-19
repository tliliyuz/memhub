"""管理写操作：创建、修订号并发、废弃、归档删除、边编辑。"""

from __future__ import annotations

from pathlib import Path

import pytest

from memhub.contract import Edge, Kind, Predicate, Tier
from memhub.kb import manage
from memhub.kb.store import KnowledgeStore


@pytest.fixture
def store(tmp_path: Path) -> KnowledgeStore:
    root = tmp_path / "knowledge"
    root.mkdir()
    return KnowledgeStore(root)


def _draft(**overrides: object) -> manage.NodeDraft:
    data: dict[str, object] = {
        "kind": Kind.FACT,
        "title": "HTTPX trust_env 导致代理 502",
        "body": "代理失败时先看 trust_env。",
        "project": "memhub",
        "tags": ["httpx"],
    }
    data.update(overrides)
    return manage.NodeDraft(**data)  # type: ignore[arg-type]


def test_create_generates_kebab_id_and_frontmatter(store: KnowledgeStore) -> None:
    result = manage.create_node(store, _draft())

    assert result["id"] == "memhub/fact/httpx-trust-env-502"
    node, body = store.read(result["id"])
    assert node.title == "HTTPX trust_env 导致代理 502"
    assert node.tier is Tier.CANDIDATE
    assert node.source[0].type.value == "manual"
    assert "trust_env" in body
    assert result["revision"] == manage.node_revision(store, result["id"])


def test_create_falls_back_to_random_slug_for_cjk_title(store: KnowledgeStore) -> None:
    result = manage.create_node(store, _draft(title="纯中文标题"))
    node_id = result["id"]
    assert node_id.startswith("memhub/fact/n-")
    assert manage.slugify("纯中文标题") == ""


def test_create_duplicate_is_conflict(store: KnowledgeStore) -> None:
    manage.create_node(store, _draft(slug="same-slug"))
    with pytest.raises(manage.ConflictError):
        manage.create_node(store, _draft(title="另一个标题", slug="same-slug"))


def test_create_entity_without_entity_kind_is_invalid(store: KnowledgeStore) -> None:
    with pytest.raises(manage.InvalidError):
        manage.create_node(store, _draft(kind=Kind.ENTITY, title="Some Service"))


def test_update_requires_matching_revision(store: KnowledgeStore) -> None:
    created = manage.create_node(store, _draft())
    node_id = str(created["id"])
    revision = str(created["revision"])

    with pytest.raises(manage.ConflictError) as excinfo:
        manage.update_node(
            store, node_id, expected_revision="deadbeef", patch=manage.NodePatch(title="新标题")
        )
    assert excinfo.value.data["current"] == revision

    updated = manage.update_node(
        store, node_id, expected_revision=revision, patch=manage.NodePatch(title="新标题")
    )
    assert updated["revision"] != revision
    node, body = store.read(node_id)
    assert node.title == "新标题"
    assert body.startswith("代理失败")


def test_update_to_deprecated_without_superseded_by_is_invalid(store: KnowledgeStore) -> None:
    created = manage.create_node(store, _draft())
    with pytest.raises(manage.InvalidError):
        manage.update_node(
            store,
            str(created["id"]),
            expected_revision=str(created["revision"]),
            patch=manage.NodePatch(tier=Tier.DEPRECATED),
        )


def test_deprecate_sets_tier_and_appends_reason(store: KnowledgeStore) -> None:
    old = manage.create_node(store, _draft(slug="old"))
    new = manage.create_node(store, _draft(title="新版做法", slug="new"))

    result = manage.deprecate_node(
        store, str(old["id"]), superseded_by=str(new["id"]), reason="已被新流程替代"
    )

    node, body = store.read(str(old["id"]))
    assert node.tier is Tier.DEPRECATED
    assert node.superseded_by == new["id"]
    assert "废弃说明" in body
    assert result["revision"] == manage.node_revision(store, str(old["id"]))


def test_deprecate_rejects_unknown_superseded_by(store: KnowledgeStore) -> None:
    created = manage.create_node(store, _draft())
    with pytest.raises(manage.InvalidError):
        manage.deprecate_node(store, str(created["id"]), superseded_by="memhub/fact/nope")


def test_delete_archives_and_removes_incident_edges(store: KnowledgeStore) -> None:
    a = manage.create_node(store, _draft(slug="a"))
    b = manage.create_node(store, _draft(title="B", slug="b"))
    manage.replace_out_edges(
        store,
        str(a["id"]),
        [Edge(source=str(a["id"]), predicate=Predicate.RELATED_TO, target=str(b["id"]))],
    )

    result = manage.delete_node(
        store, str(b["id"]), expected_revision=str(b["revision"]), reason="重复"
    )

    assert result["removed_edges"] == 1
    assert not store.exists(str(b["id"]))
    trash = manage.list_trash(store)
    assert trash["total"] == 1
    assert trash["items"][0]["id"] == b["id"]

    restored = manage.restore_node(store, str(result["trash"]))
    assert restored["id"] == b["id"]
    assert store.exists(str(b["id"]))


def test_delete_rejects_stale_revision(store: KnowledgeStore) -> None:
    created = manage.create_node(store, _draft())
    with pytest.raises(manage.ConflictError):
        manage.delete_node(store, str(created["id"]), expected_revision="stale")


def test_restore_refuses_when_node_reappeared(store: KnowledgeStore) -> None:
    created = manage.create_node(store, _draft())
    deleted = manage.delete_node(
        store, str(created["id"]), expected_revision=str(created["revision"])
    )
    manage.create_node(store, _draft(slug=str(created["id"]).rsplit("/", 1)[-1]))
    with pytest.raises(manage.ConflictError):
        manage.restore_node(store, str(deleted["trash"]))


def test_replace_out_edges_rewrites_only_source_side(store: KnowledgeStore) -> None:
    a = manage.create_node(store, _draft(slug="a"))
    b = manage.create_node(store, _draft(title="B", slug="b"))
    c = manage.create_node(store, _draft(title="C", slug="c"))

    manage.replace_out_edges(
        store,
        str(a["id"]),
        [
            Edge(source=str(a["id"]), predicate=Predicate.RELATED_TO, target=str(b["id"])),
            Edge(source=str(b["id"]), predicate=Predicate.RELATED_TO, target=str(c["id"])),
        ][:1],
    )
    result = manage.replace_out_edges(
        store,
        str(a["id"]),
        [Edge(source=str(a["id"]), predicate=Predicate.DEPENDS_ON, target=str(c["id"]))],
    )
    assert result["added"] == 1

    detail = manage.get_node(store, str(a["id"]))
    assert [edge["target"] for edge in detail["edges"]["out"]] == [c["id"]]
    # b 的出边不受影响
    assert manage.get_node(store, str(b["id"]))["edges"]["out"] == []


def test_replace_out_edges_rejects_foreign_source(store: KnowledgeStore) -> None:
    a = manage.create_node(store, _draft(slug="a"))
    b = manage.create_node(store, _draft(title="B", slug="b"))
    with pytest.raises(manage.InvalidError):
        manage.replace_out_edges(
            store,
            str(a["id"]),
            [Edge(source=str(b["id"]), predicate=Predicate.RELATED_TO, target=str(a["id"]))],
        )


def test_list_nodes_filters_and_pages(store: KnowledgeStore) -> None:
    manage.create_node(store, _draft(slug="one", title="代理 502 排查"))
    manage.create_node(
        store,
        _draft(
            slug="two",
            title="夜间运行窗口",
            body="凌晨两点前跑完。",
            kind=Kind.PROCEDURE,
            tags=["ops"],
        ),
    )

    everything = manage.list_nodes(store)
    assert everything["total"] == 2

    facts = manage.list_nodes(store, kind="fact")
    assert [item["id"] for item in facts["items"]] == ["memhub/fact/one"]

    tagged = manage.list_nodes(store, tag="ops")
    assert [item["id"] for item in tagged["items"]] == ["memhub/procedure/two"]

    searched = manage.list_nodes(store, q="代理")
    assert [item["id"] for item in searched["items"]] == ["memhub/fact/one"]

    page = manage.list_nodes(store, limit=1, offset=1)
    assert page["total"] == 2
    assert len(page["items"]) == 1


def test_stats_counts_kinds_tiers_and_orphans(store: KnowledgeStore) -> None:
    a = manage.create_node(store, _draft(slug="a"))
    b = manage.create_node(store, _draft(title="B", slug="b", kind=Kind.PITFALL))
    manage.replace_out_edges(
        store,
        str(a["id"]),
        [Edge(source=str(a["id"]), predicate=Predicate.RELATED_TO, target=str(b["id"]))],
    )

    stats = manage.stats(store)
    assert stats["nodes"] == 2
    assert stats["edges"] == 1
    assert stats["orphans"] == 0
    assert stats["by_kind"] == {"fact": 1, "pitfall": 1}


def test_revision_is_content_addressed(store: KnowledgeStore) -> None:
    created = manage.create_node(store, _draft())
    path = store.path_for(str(created["id"]))
    before = manage.revision_of(path)
    path.write_text(path.read_text(encoding="utf-8") + "\n额外一行\n", encoding="utf-8")
    assert manage.revision_of(path) != before


def test_write_lock_takes_over_stale_lock(store: KnowledgeStore) -> None:
    lock = store.root / manage.LOCK_NAME
    lock.write_text("stale", encoding="utf-8")
    old = 0.0
    import os

    os.utime(lock, (old, old))
    with manage.write_lock(store.root, timeout=0.1):
        assert lock.is_file()
    assert not lock.exists()
