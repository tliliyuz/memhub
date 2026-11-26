"""写工具的创建者边界：`kb_update_candidate` 与 `kb_deprecate`。

两条工具都只碰「创建者为本凭据」的节点（ADR-0014）：按 revision 做乐观并发，
别人的节点返回 `not_owner`；已 deprecated 的节点不可再改（`deprecated_immutable`）。
废弃支持「有替代节点」与「只写原因」两种形态。
"""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from memhub.contract import Kind, NodeFrontmatter, SourceKind, SourceRef, Tier
from memhub.kb import catalog, manage
from memhub.kb.store import KnowledgeStore
from memhub.mcp.server import call_tool

GRANT_ID = "abcdef012345"
OTHER_GRANT = "ffffffffffff"
BODY = "这是一段至少二十个字符的正文，用来作为更新与废弃夹具的起点。"


@pytest.fixture
async def store(tmp_path: Path) -> KnowledgeStore:
    kb = KnowledgeStore(tmp_path)
    await catalog.create_kb(kb, kb_id="sample", name="sample")
    return kb


async def invoke(
    store: KnowledgeStore,
    name: str,
    args: dict,
    *,
    projects: frozenset[str] | None = None,
    grant_id: str = GRANT_ID,
    writable: bool = True,
) -> dict:
    result = await call_tool(
        name,
        args,
        store,
        **({} if projects is None else {"projects": projects}),
        grant_id=grant_id,
        writable=writable,
    )
    payload = json.loads(result["content"][0]["text"])
    assert result["isError"] == ("code" in payload)
    return payload


async def make_node(
    store: KnowledgeStore,
    slug: str,
    *,
    tier: Tier = Tier.CANONICAL,
    body: str = BODY,
    title: str = "夹具节点",
    kind: Kind = Kind.FACT,
    grant_id: str = GRANT_ID,
) -> tuple[str, str]:
    node_id = f"sample/{kind.value}/{slug}"
    now = datetime.now(UTC)
    node = NodeFrontmatter(
        id=node_id,
        kind=kind,
        entity_kind="service" if kind is Kind.ENTITY else None,
        status="open" if kind is Kind.QUESTION else None,
        title=title,
        project="sample",
        tier=tier,
        superseded_by="sample/fact/elsewhere" if tier is Tier.DEPRECATED else None,
        source=[SourceRef(type=SourceKind.MANUAL, ref=f"mcp:{grant_id}")],
        created_at=now,
        updated_at=now,
    )
    await store.write(node_id, node, body)
    revision = await manage.node_revision(store, node_id)
    assert revision is not None
    return node_id, revision


# ---------------------------------------------------------------- kb_update_candidate


async def test_update_requires_writable_scope(store: KnowledgeStore) -> None:
    node_id, revision = await make_node(store, "scope")
    payload = await invoke(
        store,
        "kb_update_candidate",
        {"id": node_id, "expected_revision": revision, "title": "新标题"},
        writable=False,
    )
    assert payload["code"] == 3004


async def test_update_requires_at_least_one_field(store: KnowledgeStore) -> None:
    node_id, revision = await make_node(store, "empty-patch")
    payload = await invoke(
        store, "kb_update_candidate", {"id": node_id, "expected_revision": revision}
    )
    assert payload["code"] == 3004


async def test_update_changes_body_and_returns_new_revision(store: KnowledgeStore) -> None:
    node_id, revision = await make_node(store, "edit")
    payload = await invoke(
        store,
        "kb_update_candidate",
        {
            "id": node_id,
            "expected_revision": revision,
            "body": "改正后的正文，长度仍然满足内容门槛要求。",
        },
    )
    assert "code" not in payload
    assert payload["id"] == node_id
    assert payload["tier"] == "canonical"
    assert payload["revision"] != revision
    node, body = await store.read(node_id)
    assert body == "改正后的正文，长度仍然满足内容门槛要求。"
    assert node.title == "夹具节点"
    assert node.tier is Tier.CANONICAL
    assert node.created_at == node.created_at

    again = await invoke(
        store,
        "kb_update_candidate",
        {"id": node_id, "expected_revision": payload["revision"], "title": "改过的标题"},
    )
    assert "code" not in again
    node, _ = await store.read(node_id)
    assert node.title == "改过的标题"


async def test_update_keeps_source_and_created_at(store: KnowledgeStore) -> None:
    node_id, revision = await make_node(store, "keep")
    before, _ = await store.read(node_id)
    payload = await invoke(
        store,
        "kb_update_candidate",
        {"id": node_id, "expected_revision": revision, "title": "只改标题"},
    )
    assert "code" not in payload
    after, _ = await store.read(node_id)
    assert after.created_at == before.created_at
    assert after.source == before.source


async def test_update_revision_conflict_leaves_file_untouched(store: KnowledgeStore) -> None:
    node_id, revision = await make_node(store, "conflict")
    before, before_body = await store.read(node_id)
    payload = await invoke(
        store,
        "kb_update_candidate",
        {"id": node_id, "expected_revision": "0" * 16, "title": "不该生效"},
    )
    assert payload["code"] == 1010
    assert payload["data"]["reason"] == "revision_conflict"
    assert payload["data"]["current"] == revision
    after, after_body = await store.read(node_id)
    assert after.title == before.title
    assert after_body == before_body


async def test_update_rejects_other_owner(store: KnowledgeStore) -> None:
    node_id, revision = await make_node(store, "canonical", grant_id=OTHER_GRANT)
    payload = await invoke(
        store,
        "kb_update_candidate",
        {"id": node_id, "expected_revision": revision, "title": "越权修改"},
    )
    assert payload["code"] == 1010
    assert payload["data"]["reason"] == "not_owner"
    node, _ = await store.read(node_id)
    assert node.title == "夹具节点"


async def test_update_rejects_deprecated(store: KnowledgeStore) -> None:
    node_id, revision = await make_node(store, "gone", tier=Tier.DEPRECATED)
    payload = await invoke(
        store,
        "kb_update_candidate",
        {"id": node_id, "expected_revision": revision, "title": "越权修改"},
    )
    assert payload["code"] == 1010
    assert payload["data"]["reason"] == "deprecated_immutable"


async def test_update_unknown_node_is_not_found(store: KnowledgeStore) -> None:
    payload = await invoke(
        store,
        "kb_update_candidate",
        {"id": "sample/fact/missing", "expected_revision": "0" * 16, "title": "新标题"},
    )
    assert payload["code"] == 3001


async def test_update_out_of_project_scope_is_not_found(store: KnowledgeStore) -> None:
    node_id, revision = await make_node(store, "outsider")
    payload = await invoke(
        store,
        "kb_update_candidate",
        {"id": node_id, "expected_revision": revision, "title": "新标题"},
        projects=frozenset({"other"}),
    )
    assert payload["code"] == 3001


async def test_update_rejects_short_body(store: KnowledgeStore) -> None:
    node_id, revision = await make_node(store, "short")
    payload = await invoke(
        store,
        "kb_update_candidate",
        {"id": node_id, "expected_revision": revision, "body": "太短"},
    )
    assert payload["code"] == 1003
    assert payload["data"]["reason"] == "content_rejected"


async def test_update_rejects_secret(store: KnowledgeStore) -> None:
    node_id, revision = await make_node(store, "secret")
    payload = await invoke(
        store,
        "kb_update_candidate",
        {
            "id": node_id,
            "expected_revision": revision,
            "body": "把凭据写进正文 password = hunter2hunter2 是不允许的。",
        },
    )
    assert payload["code"] == 1003
    assert payload["data"]["reason"] == "secret_detected"


async def test_update_rejects_duplicate_body(store: KnowledgeStore) -> None:
    await make_node(store, "first", body="第一条候选正文，长度足够通过内容门槛检查。")
    second, second_rev = await make_node(
        store, "second", body="第二条候选正文，长度足够通过内容门槛检查。"
    )
    payload = await invoke(
        store,
        "kb_update_candidate",
        {
            "id": second,
            "expected_revision": second_rev,
            "body": "第一条候选正文，长度足够通过内容门槛检查。",
        },
    )
    assert payload["code"] == 1010
    assert payload["data"]["reason"] == "content_duplicate"
    _, body = await store.read(second)
    assert body == "第二条候选正文，长度足够通过内容门槛检查。"


async def test_update_same_body_is_not_a_duplicate_of_itself(store: KnowledgeStore) -> None:
    node_id, revision = await make_node(store, "self")
    payload = await invoke(
        store,
        "kb_update_candidate",
        {"id": node_id, "expected_revision": revision, "title": "只改标题不动正文"},
    )
    assert "code" not in payload


async def test_update_is_deferred_when_lock_is_held(store: KnowledgeStore) -> None:
    node_id, revision = await make_node(store, "busy")
    async with manage.write_lock(store.root):
        payload = await invoke(
            store,
            "kb_update_candidate",
            {"id": node_id, "expected_revision": revision, "title": "新标题"},
        )
    assert payload["code"] == 3006


# ---------------------------------------------------------------- kb_deprecate


async def test_deprecate_without_successor_keeps_file(store: KnowledgeStore) -> None:
    node_id, revision = await make_node(store, "wrong")
    payload = await invoke(
        store,
        "kb_deprecate",
        {"id": node_id, "expected_revision": revision, "reason": "结论已被证伪，没有替代节点"},
    )
    assert "code" not in payload
    assert payload["tier"] == "deprecated"
    node, body = await store.read(node_id)
    assert node.tier is Tier.DEPRECATED
    assert node.superseded_by is None
    assert node.deprecated_reason == "结论已被证伪，没有替代节点"
    assert "## 废弃说明" in body
    assert store.path_for(node_id).is_file()


async def test_deprecate_with_successor_records_target(store: KnowledgeStore) -> None:
    successor, _ = await make_node(store, "better")
    node_id, revision = await make_node(store, "worse")
    payload = await invoke(
        store,
        "kb_deprecate",
        {
            "id": node_id,
            "expected_revision": revision,
            "reason": "被更准确的候选取代",
            "superseded_by": successor,
        },
    )
    assert "code" not in payload
    node, _ = await store.read(node_id)
    assert node.tier is Tier.DEPRECATED
    assert node.superseded_by == successor


async def test_deprecate_rejects_other_owner(store: KnowledgeStore) -> None:
    node_id, revision = await make_node(store, "authoritative", grant_id=OTHER_GRANT)
    payload = await invoke(
        store,
        "kb_deprecate",
        {"id": node_id, "expected_revision": revision, "reason": "不该生效"},
    )
    assert payload["code"] == 1010
    assert payload["data"]["reason"] == "not_owner"
    node, _ = await store.read(node_id)
    assert node.tier is Tier.CANONICAL


async def test_deprecate_already_deprecated_is_rejected(store: KnowledgeStore) -> None:
    node_id, revision = await make_node(store, "twice")
    first = await invoke(
        store,
        "kb_deprecate",
        {"id": node_id, "expected_revision": revision, "reason": "第一轮废弃"},
    )
    assert "code" not in first
    payload = await invoke(
        store,
        "kb_deprecate",
        {"id": node_id, "expected_revision": first["revision"], "reason": "第二轮废弃"},
    )
    assert payload["code"] == 1010
    assert payload["data"]["reason"] == "deprecated_immutable"


async def test_deprecate_rejects_self_successor(store: KnowledgeStore) -> None:
    node_id, revision = await make_node(store, "self-ref")
    payload = await invoke(
        store,
        "kb_deprecate",
        {
            "id": node_id,
            "expected_revision": revision,
            "reason": "指向自己",
            "superseded_by": node_id,
        },
    )
    assert payload["code"] == 1003
    assert payload["data"]["reason"] == "superseded_by_invalid"
    node, _ = await store.read(node_id)
    assert node.tier is Tier.CANONICAL


async def test_deprecate_rejects_unknown_successor(store: KnowledgeStore) -> None:
    node_id, revision = await make_node(store, "orphan-target")
    payload = await invoke(
        store,
        "kb_deprecate",
        {
            "id": node_id,
            "expected_revision": revision,
            "reason": "替代节点不存在",
            "superseded_by": "sample/fact/nope",
        },
    )
    assert payload["code"] == 1003
    assert payload["data"]["reason"] == "superseded_by_unavailable"
    node, _ = await store.read(node_id)
    assert node.tier is Tier.CANONICAL


async def test_deprecate_revision_conflict_leaves_file_untouched(store: KnowledgeStore) -> None:
    node_id, _ = await make_node(store, "stale")
    payload = await invoke(
        store,
        "kb_deprecate",
        {"id": node_id, "expected_revision": "0" * 16, "reason": "基于旧版本"},
    )
    assert payload["code"] == 1010
    assert payload["data"]["reason"] == "revision_conflict"
    node, _ = await store.read(node_id)
    assert node.tier is Tier.CANONICAL


async def test_deprecate_requires_reason(store: KnowledgeStore) -> None:
    node_id, revision = await make_node(store, "no-reason")
    payload = await invoke(
        store,
        "kb_deprecate",
        {"id": node_id, "expected_revision": revision},
    )
    assert payload["code"] == 3004


async def test_deprecate_unknown_node_is_not_found(store: KnowledgeStore) -> None:
    payload = await invoke(
        store,
        "kb_deprecate",
        {"id": "sample/fact/missing", "expected_revision": "0" * 16, "reason": "不存在"},
    )
    assert payload["code"] == 3001


async def test_deprecate_rejects_successor_out_of_scope(store: KnowledgeStore) -> None:
    await catalog.create_kb(store, kb_id="other", name="other")
    await make_node(store, "foreign", kind=Kind.FACT)
    node_id, revision = await make_node(store, "scoped")
    payload = await invoke(
        store,
        "kb_deprecate",
        {
            "id": node_id,
            "expected_revision": revision,
            "reason": "替代节点在别的库",
            "superseded_by": "other/fact/foreign",
        },
        projects=frozenset({"sample"}),
    )
    assert payload["code"] == 1003
    assert payload["data"]["reason"] == "superseded_by_unavailable"


async def test_deprecate_rejects_overlong_reason(store: KnowledgeStore) -> None:
    node_id, revision = await make_node(store, "long-reason")
    payload = await invoke(
        store,
        "kb_deprecate",
        {"id": node_id, "expected_revision": revision, "reason": "长" * 2001},
    )
    assert payload["code"] == 3004
    node, _ = await store.read(node_id)
    assert node.tier is Tier.CANONICAL


async def test_update_cannot_change_slug_or_kind(store: KnowledgeStore) -> None:
    node_id, revision = await make_node(store, "fixed-identity")
    payload = await invoke(
        store,
        "kb_update_candidate",
        {
            "id": node_id,
            "expected_revision": revision,
            "slug": "another",
            "kind": "decision",
        },
    )
    assert payload["code"] == 3004
    node, _ = await store.read(node_id)
    assert node.kind is Kind.FACT


async def test_read_tool_exposes_revision_for_write_tools(store: KnowledgeStore) -> None:
    node_id, revision = await make_node(store, "roundtrip")
    payload = await invoke(store, "kb_read", {"id": node_id})
    assert payload["revision"] == revision
