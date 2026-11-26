"""ADR-0014 取消候选门槛的验收测试（规格 docs/plans/tier-canonical-spec.md §4）。

覆盖：写入即 canonical、检索默认排除 deprecated、MCP 创建者边界、
管理台 tier 写入拒绝。存量迁移的验收在 `test_tier_migration.py`。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from memhub.contract import Kind, NodeFrontmatter, SourceKind, SourceRef, Tier
from memhub.kb import catalog, manage, query
from memhub.kb.store import KnowledgeStore
from memhub.mcp.server import call_tool
from memhub.worker.merge import merge
from memhub.worker.schema import ExtractedNode, Extraction

NOW = datetime(2026, 11, 26, tzinfo=UTC)
BODY = "这是一段至少二十个字符的正文，用来通过内容门槛的最低长度检查。"


def _extraction(slug: str) -> Extraction:
    return Extraction(
        nodes=[
            ExtractedNode(
                kind=Kind.FACT,
                title="抽取出的结论",
                slug=slug,
                body=BODY,
                tags=["tag-a"],
                confidence=0.8,
            )
        ],
        edges=[],
    )


# ---------------------------------------------------------------- 写入层级


async def test_merge_creates_canonical_and_merges_existing(tmp_path: Path) -> None:
    store = KnowledgeStore(tmp_path)
    await catalog.create_kb(store, kb_id="demo", name="demo")
    source = SourceRef(type=SourceKind.SESSION, ref="s1")

    first = await merge(store, _extraction("alpha"), project="demo", source=source, now=NOW)
    assert first.created == ["demo/fact/alpha"]
    node, _ = await store.read("demo/fact/alpha")
    assert node.tier is Tier.CANONICAL, "新抽取的节点必须是 canonical"

    # 已有 canonical 节点不再跳过：第二次抽取走追加合并。
    second = await merge(store, _extraction("alpha"), project="demo", source=source, now=NOW)
    assert second.created == []
    assert second.updated == ["demo/fact/alpha"]
    assert not hasattr(second, "skipped_canonical"), "报告不再有「跳过 canonical」计数"
    merged, merged_body = await store.read("demo/fact/alpha")
    assert merged_body.count(BODY.strip()) == 1, "同一正文不重复追加"
    assert len(merged.source) == 1, "同一来源不重复记录"


# ---------------------------------------------------------------- MCP 写入层级


@pytest.fixture
async def store(tmp_path: Path) -> KnowledgeStore:
    kb = KnowledgeStore(tmp_path)
    await catalog.create_kb(kb, kb_id="sample", name="sample")
    return kb


async def _invoke(
    store: KnowledgeStore,
    name: str,
    args: dict,
    *,
    grant_id: str = "abcdef012345",
) -> dict:
    result = await call_tool(name, args, store, grant_id=grant_id, writable=True)
    payload = json.loads(result["content"][0]["text"])
    assert result["isError"] == ("code" in payload)
    return payload


def _write_args(**overrides: object) -> dict:
    data: dict = {
        "project": "sample",
        "kind": "fact",
        "slug": "mcp-write",
        "title": "MCP 写入夹具",
        "body": BODY,
        "evidence": [{"type": "session", "ref": "session:abc", "captured_at": NOW.isoformat()}],
    }
    data.update(overrides)
    return data


async def test_mcp_write_creates_canonical(store: KnowledgeStore) -> None:
    payload = await _invoke(store, "kb_write_candidate", _write_args())
    assert "code" not in payload
    assert payload["tier"] == "canonical"
    node, _ = await store.read(payload["id"])
    assert node.tier is Tier.CANONICAL


async def test_mcp_update_returns_current_tier(store: KnowledgeStore) -> None:
    created = await _invoke(store, "kb_write_candidate", _write_args())
    revision = created["revision"]
    payload = await _invoke(
        store,
        "kb_update_candidate",
        {"id": created["id"], "expected_revision": revision, "title": "改过的标题"},
    )
    assert "code" not in payload
    assert payload["tier"] == "canonical"
    node, _ = await store.read(created["id"])
    assert node.title == "改过的标题"


# ---------------------------------------------------------------- MCP 创建者边界


def _seed_node(store: KnowledgeStore, node_id: str, *, tier: Tier) -> object:
    now = datetime.now(UTC)
    node = NodeFrontmatter(
        id=node_id,
        kind=Kind.FACT,
        title="无主节点",
        project=node_id.split("/", 1)[0],
        tier=tier,
        created_at=now,
        updated_at=now,
    )
    return node


async def test_mcp_update_by_owner_succeeds(store: KnowledgeStore) -> None:
    created = await _invoke(store, "kb_write_candidate", _write_args(slug="mine"))
    payload = await _invoke(
        store,
        "kb_update_candidate",
        {
            "id": created["id"],
            "expected_revision": created["revision"],
            "body": "创建者本人更新后的正文，长度满足门槛要求。",
        },
    )
    assert "code" not in payload


async def test_mcp_update_by_other_grant_is_not_owner(store: KnowledgeStore) -> None:
    created = await _invoke(store, "kb_write_candidate", _write_args(slug="mine"))
    payload = await _invoke(
        store,
        "kb_update_candidate",
        {
            "id": created["id"],
            "expected_revision": created["revision"],
            "title": "别人的修改",
        },
        grant_id="ffffffffffff",
    )
    assert payload["code"] == 1010
    assert payload["data"]["reason"] == "not_owner"
    node, _ = await store.read(created["id"])
    assert node.title == "MCP 写入夹具"


async def test_mcp_update_unowned_existing_node_is_not_owner(store: KnowledgeStore) -> None:
    node_id = "sample/fact/orphan"
    node = _seed_node(store, node_id, tier=Tier.CANONICAL)
    await store.write(node_id, node, BODY)  # type: ignore[arg-type]
    revision = await manage.node_revision(store, node_id)
    assert revision is not None
    payload = await _invoke(
        store,
        "kb_update_candidate",
        {"id": node_id, "expected_revision": revision, "title": "越权修改"},
    )
    assert payload["code"] == 1010
    assert payload["data"]["reason"] == "not_owner"
    assert (await store.read(node_id))[0].title == "无主节点"


async def test_mcp_deprecate_by_other_grant_is_not_owner(store: KnowledgeStore) -> None:
    created = await _invoke(store, "kb_write_candidate", _write_args(slug="mine"))
    payload = await _invoke(
        store,
        "kb_deprecate",
        {
            "id": created["id"],
            "expected_revision": created["revision"],
            "reason": "别人的废弃",
        },
        grant_id="ffffffffffff",
    )
    assert payload["code"] == 1010
    assert payload["data"]["reason"] == "not_owner"
    assert (await store.read(created["id"]))[0].tier is Tier.CANONICAL


async def test_mcp_owner_can_deprecate(store: KnowledgeStore) -> None:
    created = await _invoke(store, "kb_write_candidate", _write_args(slug="mine"))
    payload = await _invoke(
        store,
        "kb_deprecate",
        {
            "id": created["id"],
            "expected_revision": created["revision"],
            "reason": "结论被证伪",
        },
    )
    assert "code" not in payload
    assert payload["tier"] == "deprecated"
    node, _ = await store.read(created["id"])
    assert node.tier is Tier.DEPRECATED
    assert node.deprecated_reason == "结论被证伪"


async def test_mcp_update_deprecated_is_immutable(store: KnowledgeStore) -> None:
    created = await _invoke(store, "kb_write_candidate", _write_args(slug="mine"))
    deprecated = await _invoke(
        store,
        "kb_deprecate",
        {"id": created["id"], "expected_revision": created["revision"], "reason": "废弃"},
    )
    payload = await _invoke(
        store,
        "kb_update_candidate",
        {
            "id": created["id"],
            "expected_revision": deprecated["revision"],
            "title": "复活废弃节点",
        },
    )
    assert payload["code"] == 1010
    assert payload["data"]["reason"] == "deprecated_immutable"

    again = await _invoke(
        store,
        "kb_deprecate",
        {"id": created["id"], "expected_revision": deprecated["revision"], "reason": "再废弃"},
    )
    assert again["code"] == 1010
    assert again["data"]["reason"] == "deprecated_immutable"


# ---------------------------------------------------------------- 去重集合


async def test_content_duplicate_covers_canonical(store: KnowledgeStore) -> None:
    await _invoke(store, "kb_write_candidate", _write_args(slug="first"))
    payload = await _invoke(
        store, "kb_write_candidate", _write_args(slug="second", title="另一个标题")
    )
    assert payload["code"] == 1010
    assert payload["data"]["reason"] == "content_duplicate"


# ---------------------------------------------------------------- 检索默认层


async def test_search_default_excludes_only_deprecated(store: KnowledgeStore) -> None:
    created = await _invoke(store, "kb_write_candidate", _write_args(slug="visible"))
    await _invoke(
        store,
        "kb_deprecate",
        {"id": created["id"], "expected_revision": created["revision"], "reason": "废弃"},
    )
    await _invoke(store, "kb_write_candidate", _write_args(slug="alive", title="另一个标题不同"))

    default = await query.search(store, "正文")
    ids = [item["id"] for item in default["results"]]
    assert "sample/fact/alive" in ids
    assert all(not node_id.endswith("visible") for node_id in ids)

    everything = await query.search(store, "正文", tier="all")
    ids_all = [item["id"] for item in everything["results"]]
    assert "sample/fact/visible" in ids_all and "sample/fact/alive" in ids_all


async def test_search_rejects_candidate_tier(store: KnowledgeStore) -> None:
    with pytest.raises(query.QueryError):
        await query.search(store, "任意", tier="candidate")


async def test_search_empty_hint_has_no_candidate_nag(store: KnowledgeStore) -> None:
    response = await query.search(store, "完全无关的查询词")
    assert response["results"] == []
    assert "候选" not in response.get("hint", "")
