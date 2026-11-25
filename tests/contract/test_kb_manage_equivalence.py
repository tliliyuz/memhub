"""管理端写操作在文件存储与 PG 存储下行为等价（规格 §8.2/§8.3/§8.7）。

验收条件从规格导出，不看实现形状：同一串 manage 调用分别喂给 `KnowledgeStore`
（markdown，迁移前的真源）与 `PgKnowledgeStore`（`kb_*` 表），断言对外结论一致。
任一侧不成立即为行为变更，必须回到规格裁决。
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from anyio import Path as AsyncPath
from sqlalchemy.ext.asyncio import AsyncEngine

from memhub.contract import Edge, Kind, Predicate, Tier
from memhub.kb import manage
from memhub.kb.models import Base
from memhub.kb.pgstore import PgKnowledgeStore
from memhub.kb.session import create_sessionmaker
from memhub.kb.store import KnowledgeStore, ProjectMissing

REVISION_RE = re.compile(r"^[0-9a-f]{16}$")
PROJECT = "demo"
BODY = "代理失败时先看 trust_env 是否被环境代理污染。\n\n- 中文与 English 混排\n- 多行正文\n"


@pytest_asyncio.fixture(params=["file", "pg"])
async def store(
    request: pytest.FixtureRequest, tmp_path: Path, kb_engine: AsyncEngine
) -> AsyncIterator[KnowledgeStore | PgKnowledgeStore]:
    if request.param == "file":
        root = tmp_path / "knowledge"
        await AsyncPath(root / PROJECT).mkdir(parents=True)
        yield KnowledgeStore(root)
        return

    async with kb_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    pg = PgKnowledgeStore(create_sessionmaker(kb_engine))
    await pg.register_project(PROJECT, name="演示库")
    yield pg


def _draft(**overrides: Any) -> manage.NodeDraft:
    data: dict[str, Any] = {
        "kind": Kind.FACT,
        "title": "HTTPX trust_env 导致代理 502",
        "body": BODY,
        "project": PROJECT,
        "tags": ["httpx"],
    }
    data.update(overrides)
    return manage.NodeDraft(**data)  # type: ignore[arg-type]


async def test_create_read_update_round_trip(
    store: KnowledgeStore | PgKnowledgeStore,
) -> None:
    created = await manage.create_node(store, _draft())
    node_id = str(created["id"])
    assert node_id == "demo/fact/httpx-trust-env-502"
    assert REVISION_RE.fullmatch(str(created["revision"]))
    assert created["commit"] is None or isinstance(created["commit"], str)

    node, body = await store.read(node_id)
    assert node.title == "HTTPX trust_env 导致代理 502"
    assert node.tier is Tier.CANDIDATE
    assert node.tags == ["httpx"]
    assert body.rstrip() == BODY.rstrip()

    updated = await manage.update_node(
        store,
        node_id,
        expected_revision=str(created["revision"]),
        patch=manage.NodePatch(title="新标题", body="改写后的正文。"),
    )
    assert REVISION_RE.fullmatch(str(updated["revision"]))
    assert updated["revision"] != created["revision"]
    again, new_body = await store.read(node_id)
    assert again.title == "新标题"
    assert new_body.rstrip() == "改写后的正文。"
    detail = await manage.get_node(store, node_id)
    assert detail["revision"] == updated["revision"]


async def test_stale_revision_is_rejected_without_writing(
    store: KnowledgeStore | PgKnowledgeStore,
) -> None:
    """规格 §8.3：旧 revision 更新报冲突，数据不变，revision 恒为 16 位 hex。"""
    created = await manage.create_node(store, _draft())
    node_id = str(created["id"])

    with pytest.raises(manage.ConflictError) as excinfo:
        await manage.update_node(
            store, node_id, expected_revision="deadbeefdeadbeef", patch=manage.NodePatch(title="x")
        )
    assert excinfo.value.data["current"] == created["revision"]
    node, _ = await store.read(node_id)
    assert node.title == "HTTPX trust_env 导致代理 502"

    fresh = await manage.update_node(
        store,
        node_id,
        expected_revision=str(created["revision"]),
        patch=manage.NodePatch(title="z"),
    )
    with pytest.raises(manage.ConflictError) as stale:
        await manage.update_node(
            store,
            node_id,
            expected_revision=str(created["revision"]),
            patch=manage.NodePatch(title="w"),
        )
    assert stale.value.data["current"] == fresh["revision"]


async def test_create_requires_registered_project(
    store: KnowledgeStore | PgKnowledgeStore,
) -> None:
    with pytest.raises(ProjectMissing):
        await manage.create_node(store, _draft(project="ghost"))


async def test_delete_list_trash_and_restore(
    store: KnowledgeStore | PgKnowledgeStore,
) -> None:
    """规格 §8.7：删除是软删；回收站可列、可恢复；相连边随删除移除。"""
    a = await manage.create_node(store, _draft(slug="a"))
    b = await manage.create_node(store, _draft(title="B 节点", slug="b"))
    await manage.replace_out_edges(
        store,
        str(a["id"]),
        [Edge(source=str(a["id"]), predicate=Predicate.RELATED_TO, target=str(b["id"]))],
    )

    deleted = await manage.delete_node(
        store, str(b["id"]), expected_revision=str(b["revision"]), reason="重复", actor="tester"
    )
    assert deleted["removed_edges"] == 1
    assert not await store.exists(str(b["id"]))
    assert str(b["id"]) not in await store.list_ids()

    trash = await manage.list_trash(store)
    assert trash["total"] == 1
    item = trash["items"][0]
    assert item["id"] == b["id"]
    assert item["title"] == "B 节点"
    assert item["kind"] == "fact"
    assert item["project"] == PROJECT
    assert item["reason"] == "重复"
    assert item["actor"] == "tester"
    assert item["deleted_at"]
    assert str(b["id"]) in str(item["trash"])

    restored = await manage.restore_node(store, str(item["trash"]))
    assert restored["id"] == b["id"]
    assert REVISION_RE.fullmatch(str(restored["revision"]))
    assert await store.exists(str(b["id"]))
    assert (await manage.list_trash(store))["total"] == 0


async def test_restore_refuses_when_node_reappeared(
    store: KnowledgeStore | PgKnowledgeStore,
) -> None:
    created = await manage.create_node(store, _draft())
    deleted = await manage.delete_node(
        store, str(created["id"]), expected_revision=str(created["revision"])
    )
    await manage.create_node(store, _draft())
    with pytest.raises(manage.ConflictError):
        await manage.restore_node(store, str(deleted["trash"]))


async def test_replace_out_edges_rewrites_only_source_side(
    store: KnowledgeStore | PgKnowledgeStore,
) -> None:
    a = await manage.create_node(store, _draft(slug="a"))
    b = await manage.create_node(store, _draft(title="B", slug="b"))
    c = await manage.create_node(store, _draft(title="C", slug="c"))

    await manage.replace_out_edges(
        store,
        str(a["id"]),
        [Edge(source=str(a["id"]), predicate=Predicate.RELATED_TO, target=str(b["id"]))],
    )
    await manage.replace_out_edges(
        store,
        str(a["id"]),
        [Edge(source=str(a["id"]), predicate=Predicate.DEPENDS_ON, target=str(c["id"]))],
    )

    detail = await manage.get_node(store, str(a["id"]))
    assert [edge["target"] for edge in detail["edges"]["out"]] == [c["id"]]
    assert (await manage.get_node(store, str(b["id"])))["edges"]["out"] == []


async def test_deprecate_sets_tier_and_keeps_node(
    store: KnowledgeStore | PgKnowledgeStore,
) -> None:
    old = await manage.create_node(store, _draft(slug="old"))
    new = await manage.create_node(store, _draft(title="新版做法", slug="new"))

    result = await manage.deprecate_node(
        store, str(old["id"]), superseded_by=str(new["id"]), reason="已被新流程替代"
    )

    node, body = await store.read(str(old["id"]))
    assert node.tier is Tier.DEPRECATED
    assert node.superseded_by == new["id"]
    assert "废弃说明" in body
    assert result["revision"] == await manage.node_revision(store, str(old["id"]))
