"""抽取 → 合并 → 投影 的端到端形状（不调用真实模型）。"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from memhub.contract import SourceKind, SourceRef, Tier
from memhub.kb.projection import build_graph
from memhub.kb.store import KnowledgeStore
from memhub.worker.extract import extract_document
from memhub.worker.merge import merge
from memhub.worker.prompts import load_profile


class FakeClient:
    def __init__(self, payloads: list[dict[str, object]]) -> None:
        self._payloads = payloads
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, model: str, max_tokens: int = 8000) -> str:
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


def test_extract_normalizes_and_drops_unsourced_edges() -> None:
    client = FakeClient([_payload()])
    extraction = extract_document(
        client,
        template=load_profile("wiki"),
        path="a.md",
        text="内容",
        model="m",
    )
    assert [node.slug for node in extraction.nodes] == [
        "proxy-502-two-causes",
        "locate-upstream-timeout",
    ]
    assert len(extraction.edges) == 1


def test_merge_creates_updates_and_protects_canonical(tmp_path: Path) -> None:
    store = KnowledgeStore(tmp_path)
    source = SourceRef(type=SourceKind.SESSION, ref="s1")
    now = datetime(2026, 11, 18, tzinfo=UTC)

    client = FakeClient([_payload()])
    extraction = extract_document(
        client, template=load_profile("wiki"), path="a.md", text="内容", model="m"
    )
    first = merge(store, extraction, project="demo", source=source, now=now)
    assert len(first.created) == 2
    assert first.edges_added == 1

    second = merge(store, extraction, project="demo", source=source, now=now)
    assert second.created == []
    assert len(second.updated) == 2
    node, body = store.read("demo/pitfall/proxy-502-two-causes")
    assert body.count("## 症状") == 1, "重复抽取不得重复追加正文"
    assert len(node.source) == 1, "同一来源不重复记录"

    node.tier = Tier.CANONICAL
    store.write(node.id, node, body)
    third = merge(store, extraction, project="demo", source=source, now=now)
    assert "demo/pitfall/proxy-502-two-causes" in third.skipped_canonical


def test_projection_builds_nodes_and_resolves_edges(tmp_path: Path) -> None:
    store = KnowledgeStore(tmp_path)
    source = SourceRef(type=SourceKind.WIKI, ref="a.md")
    client = FakeClient([_payload()])
    extraction = extract_document(
        client, template=load_profile("wiki"), path="a.md", text="内容", model="m"
    )
    merge(store, extraction, project="demo", source=source)

    graph, report = build_graph(store)
    assert report.nodes == 2
    assert report.edges == 1
    assert report.unresolved == []
    assert graph is not None
