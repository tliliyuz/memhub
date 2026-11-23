"""真源写入不得隐式创建知识库目录（全异步 IO）。"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from anyio import Path as AsyncPath

from memhub.contract import Edge, Kind, NodeFrontmatter, Predicate, SourceKind, SourceRef, Tier
from memhub.kb import catalog
from memhub.kb.store import KnowledgeStore, ProjectMissing

NOW = datetime(2026, 11, 23, 2, 0, tzinfo=UTC)


@pytest.fixture
async def store(tmp_path: Path) -> KnowledgeStore:
    root = tmp_path / "knowledge"
    await AsyncPath(root).mkdir()
    return KnowledgeStore(root)


def _node(project: str) -> NodeFrontmatter:
    return NodeFrontmatter(
        id="",
        kind=Kind.FACT,
        title="重试需要退避",
        tier=Tier.CANDIDATE,
        project=project,
        source=[SourceRef(type=SourceKind.MANUAL, ref="test")],
        created_at=NOW,
        updated_at=NOW,
    )


async def test_write_does_not_create_missing_project(store: KnowledgeStore) -> None:
    with pytest.raises(ProjectMissing):
        await store.write("ghost/fact/retry-backoff", _node("ghost"), "正文")

    assert not (store.root / "ghost").exists()


async def test_append_edges_does_not_create_missing_project(store: KnowledgeStore) -> None:
    edges = [Edge(source="ghost/fact/a", predicate=Predicate.ABOUT, target="ghost/fact/b")]

    with pytest.raises(ProjectMissing):
        await store.append_edges("ghost", edges, "test")

    assert not (store.root / "ghost").exists()


async def test_write_succeeds_for_created_project(store: KnowledgeStore) -> None:
    await catalog.create_kb(store, kb_id="memhub")
    await store.write("memhub/fact/retry-backoff", _node("memhub"), "正文")

    node, body = await store.read("memhub/fact/retry-backoff")
    assert node.project == "memhub"
    assert body.strip() == "正文"


async def test_write_rejects_project_path_that_is_a_file(store: KnowledgeStore) -> None:
    (store.root / "shadow").write_text("not a directory", encoding="utf-8")

    with pytest.raises(ProjectMissing):
        await store.write("shadow/fact/retry-backoff", _node("shadow"), "正文")

    assert (store.root / "shadow").read_text(encoding="utf-8") == "not a directory"


async def test_append_edges_succeeds_for_created_project(store: KnowledgeStore) -> None:
    await catalog.create_kb(store, kb_id="memhub")
    await store.write("memhub/fact/a", _node("memhub"), "a")
    await store.write("memhub/fact/b", _node("memhub"), "b")

    added = await store.append_edges(
        "memhub",
        [Edge(source="memhub/fact/a", predicate=Predicate.ABOUT, target="memhub/fact/b")],
        "test",
    )

    assert added == 1
    assert (store.root / "memhub" / "_edges.jsonl").is_file()
