"""抽取 → 合并 → 投影 的端到端形状（不调用真实模型）。"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from memhub.contract import SourceKind, SourceRef, Tier
from memhub.kb.projection import build_graph
from memhub.kb.store import KnowledgeStore
from memhub.worker.extract import ExtractionFailed, extract_document
from memhub.worker.merge import merge
from memhub.worker.prompts import load_profile


class FakeClient:
    def __init__(self, payloads: list[dict[str, object]]) -> None:
        self._payloads = payloads
        self.prompts: list[str] = []

    async def complete(self, prompt: str, *, model: str, max_tokens: int = 8000) -> str:
        self.prompts.append(prompt)
        return json.dumps(self._payloads.pop(0), ensure_ascii=False)


def _payload() -> dict[str, object]:
    return {
        "nodes": [
            {
                "kind": "pitfall",
                "entity_kind": None,
                "title": "Proxy 502 的两个根因",
                "slug": "proxy-502-two-causes",
                "body": "## 症状\n502\n\n## 根因\n上游超时",
                "tags": ["proxy"],
                "confidence": 0.8,
            },
            {
                "kind": "procedure",
                "entity_kind": None,
                "title": "分段定位上游超时",
                "slug": "locate-upstream-timeout",
                "body": "1. 看 upstream 段耗时",
                "tags": [],
                "confidence": 0.7,
            },
        ],
        "edges": [
            {
                "source": "proxy-502-two-causes",
                "predicate": "resolved_by",
                "target": "locate-upstream-timeout",
            },
            {"source": "unknown", "predicate": "about", "target": "x"},
        ],
    }


async def test_extract_normalizes_and_drops_unsourced_edges() -> None:
    client = FakeClient([_payload()])
    extraction = await extract_document(
        client,
        template=await load_profile("wiki"),
        path="a.md",
        text="内容",
        model="m",
    )
    assert [node.slug for node in extraction.nodes] == [
        "proxy-502-two-causes",
        "locate-upstream-timeout",
    ]
    assert len(extraction.edges) == 1


async def test_merge_creates_updates_and_protects_canonical(tmp_path: Path) -> None:
    store = KnowledgeStore(tmp_path)
    source = SourceRef(type=SourceKind.SESSION, ref="s1")
    now = datetime(2026, 11, 18, tzinfo=UTC)

    client = FakeClient([_payload()])
    extraction = await extract_document(
        client, template=await load_profile("wiki"), path="a.md", text="内容", model="m"
    )
    first = await merge(store, extraction, project="demo", source=source, now=now)
    assert len(first.created) == 2
    assert first.edges_added == 1

    second = await merge(store, extraction, project="demo", source=source, now=now)
    assert second.created == []
    assert len(second.updated) == 2
    node, body = await store.read("demo/pitfall/proxy-502-two-causes")
    assert body.count("## 症状") == 1, "重复抽取不得重复追加正文"
    assert len(node.source) == 1, "同一来源不重复记录"

    node.tier = Tier.CANONICAL
    await store.write(node.id, node, body)
    third = await merge(store, extraction, project="demo", source=source, now=now)
    assert "demo/pitfall/proxy-502-two-causes" in third.skipped_canonical


async def test_projection_builds_nodes_and_resolves_edges(tmp_path: Path) -> None:
    store = KnowledgeStore(tmp_path)
    source = SourceRef(type=SourceKind.WIKI, ref="a.md")
    client = FakeClient([_payload()])
    extraction = await extract_document(
        client, template=await load_profile("wiki"), path="a.md", text="内容", model="m"
    )
    await merge(store, extraction, project="demo", source=source)

    graph, report = await build_graph(store)
    assert report.nodes == 2
    assert report.edges == 1
    assert report.unresolved == []
    assert graph is not None


def _node(slug: str, **overrides: object) -> dict[str, object]:
    node: dict[str, object] = {
        "kind": "fact",
        "entity_kind": None,
        "title": slug,
        "slug": slug,
        "body": f"## 要点\n{slug}",
        "tags": [],
        "confidence": 0.8,
    }
    node.update(overrides)
    return node


async def test_unknown_predicate_falls_back_instead_of_failing() -> None:
    """实测模型会自造谓词（alternative_to）；丢整篇文档比收敛成 related_to 更糟。"""
    payload = {
        "nodes": [_node("a"), _node("b")],
        "edges": [{"source": "a", "predicate": "alternative_to", "target": "b"}],
    }
    extraction = await extract_document(
        FakeClient([payload]),
        template=await load_profile("wiki"),
        path="a.md",
        text="内容",
        model="m",
    )
    assert [edge.predicate.value for edge in extraction.edges] == ["related_to"]


async def test_one_bad_node_does_not_lose_the_rest() -> None:
    payload = {
        "nodes": [
            _node("good"),
            _node("bad-entity", kind="entity"),  # kind=entity 但缺 entity_kind
        ],
        "edges": [],
    }
    extraction = await extract_document(
        FakeClient([payload]),
        template=await load_profile("wiki"),
        path="a.md",
        text="内容",
        model="m",
    )
    assert [node.slug for node in extraction.nodes] == ["good"]


async def test_all_nodes_invalid_still_fails_loudly() -> None:
    """全部不合法说明契约跑偏，静默产出空结果会掩盖问题。"""
    payload = {"nodes": [_node("x", kind="entity")], "edges": []}
    with pytest.raises(ExtractionFailed, match="全部校验失败"):
        await extract_document(
            FakeClient([payload]),
            template=await load_profile("wiki"),
            path="a.md",
            text="内容",
            model="m",
        )
