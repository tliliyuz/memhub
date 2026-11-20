"""四个检索工具的输入、可见范围与归档一致性。"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from anyio import Path as AsyncPath

from memhub.contract import Edge, Kind, NodeFrontmatter, Predicate, SourceKind, SourceRef, Tier
from memhub.kb import catalog, manage
from memhub.kb.store import KnowledgeStore
from memhub.mcp.server import call_tool

VISIBLE = "sample/fact/example"
HIDDEN = "private/fact/secret"


@pytest.fixture
async def store(tmp_path: Path) -> KnowledgeStore:
    kb = KnowledgeStore(tmp_path)
    now = datetime.now(UTC)
    for node_id in (VISIBLE, HIDDEN, "sample/fact/second"):
        await kb.write(
            node_id,
            NodeFrontmatter(
                id=node_id,
                kind=Kind.FACT,
                title="示例节点",
                project=node_id.split("/")[0],
                tier=Tier.CANONICAL,
                created_at=now,
                updated_at=now,
                supersedes=[HIDDEN],
                source=[SourceRef(type=SourceKind.SESSION, ref="private-ref")],
            ),
            "合成样本",
        )
    await kb.append_edges(
        "sample",
        [
            Edge(source=VISIBLE, predicate=Predicate.RELATED_TO, target="sample/fact/second"),
            Edge(source=VISIBLE, predicate=Predicate.CONTRADICTS, target=HIDDEN),
            Edge(source=VISIBLE, predicate=Predicate.CONTRADICTS, target="second"),
        ],
        "fixture",
    )
    return kb


async def invoke(
    store: KnowledgeStore, name: str, args: dict[str, Any], projects: frozenset[str] | None = None
) -> dict[str, Any]:
    result = await call_tool(
        name, args, store, **({} if projects is None else {"projects": projects})
    )
    payload: dict[str, Any] = json.loads(result["content"][0]["text"])
    assert result["isError"] == ("code" in payload)
    return payload


@pytest.mark.parametrize(
    ("name", "args"),
    [
        ("kb_search", {"query": 1}),
        ("kb_search", {"query": "x", "limit": "2"}),
        ("kb_search", {"query": "x", "project": "../other"}),
        ("kb_search", {"query": "x", "kinds": ["unknown"]}),
        ("kb_read", {"id": "_trash/fixture/sample/fact/example"}),
        ("kb_related", {"id": VISIBLE, "depth": 3}),
        ("kb_audit_list", {"offset": -1}),
        ("kb_audit_list", {"projects": ["private"]}),
    ],
)
async def test_tool_arguments_enforce_schema(
    store: KnowledgeStore, name: str, args: dict[str, Any]
) -> None:
    assert (await invoke(store, name, args))["code"] == 3004


async def test_scope_is_applied_before_reading_and_resolving_edges(store: KnowledgeStore) -> None:
    # 不应尝试解析未授权库的边文件或节点。
    await AsyncPath(store.edges_path("private")).write_text("not-json")

    class GuardedStore(KnowledgeStore):
        async def read(self, node_id: str) -> tuple[NodeFrontmatter, str]:
            assert node_id.startswith("sample/")
            return await super().read(node_id)

    guarded = GuardedStore(store.root)
    scope = frozenset({"sample"})
    search = await invoke(guarded, "kb_search", {"query": "样本"}, scope)
    assert {row["id"] for row in search["results"]} == {VISIBLE, "sample/fact/second"}
    detail = await invoke(guarded, "kb_read", {"id": VISIBLE}, scope)
    assert detail["id"] == VISIBLE
    assert "private" not in json.dumps(detail)
    related = await invoke(guarded, "kb_related", {"id": VISIBLE}, scope)
    assert related["edges"] == [
        {"source": VISIBLE, "predicate": "related_to", "target": "sample/fact/second"}
    ]
    audit = await invoke(guarded, "kb_audit_list", {}, scope)
    assert audit["issues"] == []
    assert (await invoke(guarded, "kb_read", {"id": HIDDEN}, scope))["code"] == 3001
    assert (await invoke(guarded, "kb_related", {"id": HIDDEN}, scope))["code"] == 3001
    denied = await invoke(guarded, "kb_search", {"query": "样本", "project": "private"}, scope)
    assert denied["code"] == 3003
    empty = await invoke(guarded, "kb_search", {"query": "样本"}, frozenset())
    assert empty["results"] == []


async def test_archive_and_pending_state_are_respected(store: KnowledgeStore) -> None:
    async with manage.write_lock(store.root):
        assert (await invoke(store, "kb_read", {"id": VISIBLE}))["code"] == 3006
    archive = await catalog.delete_kb(store, "sample")
    assert (await invoke(store, "kb_read", {"id": VISIBLE}))["code"] == 3001
    assert (await invoke(store, "kb_search", {"query": "样本", "project": "sample"}))[
        "results"
    ] == []
    await catalog.restore_kb(store, archive["archive_id"])
    assert (await invoke(store, "kb_read", {"id": VISIBLE}))["id"] == VISIBLE
    await AsyncPath(store.root / "_kb_archives" / "pending.json").write_text("{}")
    assert (await invoke(store, "kb_audit_list", {}))["code"] == 3006


async def test_mcp_skips_links_and_non_node_markdown(store: KnowledgeStore) -> None:
    await AsyncPath(store.root / "_internal").mkdir()
    await AsyncPath(store.root / "_internal" / "notes.md").write_text("ignored")
    path = store.root / "sample" / "fact" / "linked.md"
    try:
        path.symlink_to(store.path_for(HIDDEN))
    except OSError as exc:
        pytest.skip(
            f"本机不允许创建符号链接：{exc.winerror if hasattr(exc, 'winerror') else exc.errno}"
        )
    assert (await invoke(store, "kb_read", {"id": "sample/fact/linked"}))["code"] == 3001
    found = await invoke(store, "kb_search", {"query": "样本", "project": "sample"})
    assert all(row["id"] != "sample/fact/linked" for row in found["results"])
