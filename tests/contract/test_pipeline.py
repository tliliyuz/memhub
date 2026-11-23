"""抽取 → 合并 → 投影 的端到端形状（不调用真实模型）。"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from anyio import Path as AsyncPath

from memhub.contract import SourceKind, SourceRef, Tier
from memhub.kb.projection import build_graph
from memhub.kb.store import KnowledgeStore
from memhub.worker import extract, render
from memhub.worker.extract import ExtractionFailed, extract_document
from memhub.worker.merge import merge
from memhub.worker.prompts import load_profile


class FakeClient:
    def __init__(self, payloads: list[object]) -> None:
        self._payloads = payloads
        self.prompts: list[str] = []

    async def complete(self, prompt: str, *, model: str, max_tokens: int = 32000) -> str:
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


async def _demo_store(tmp_path: Path) -> KnowledgeStore:
    """存储层不再隐式建库：先显式建好 demo 库目录。"""
    await AsyncPath(tmp_path / "demo").mkdir(exist_ok=True)
    return KnowledgeStore(tmp_path)


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
    store = await _demo_store(tmp_path)
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
    store = await _demo_store(tmp_path)
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


def _cited_node(slug: str, block: str, quote: str, **overrides: object) -> dict[str, object]:
    return _node(slug, evidence=[{"block": block, "quote": quote}], **overrides)


def _cited_edge(source: str, target: str, block: str, quote: str) -> dict[str, object]:
    return {
        "source": source,
        "target": target,
        "predicate": "related_to",
        "evidence": [{"block": block, "quote": quote}],
    }


async def test_session_candidates_require_exact_support_and_live_endpoints(tmp_path: Path) -> None:
    quote = "冷启动使用只读配置；缺少快照时从模板生成。"
    events = [
        {"type": "summary", "summary": "SYNTHETIC_SUMMARY"},
        {"type": "user", "isMeta": True, "message": {"content": "SYNTHETIC_META"}},
        {"type": "user", "message": {"content": "正在运行。"}},
        {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "text", "text": quote},
                    {"type": "tool_use", "input": {"x": "SYNTHETIC_TOOL"}},
                ]
            },
        },
        {"type": "assistant", "message": {"content": "I suspect cold starts may need retries."}},
    ]
    raw = "SYNTHETIC_FRAGMENT\n" + "\n".join(json.dumps(event) for event in events)
    client = FakeClient(
        [
            {
                "nodes": [
                    _cited_node(
                        "read-only", "b0002", quote, kind="decision", body="冷启动保持只读。"
                    ),
                    _cited_node(
                        "snapshot", "b0002", quote, kind="procedure", body="缺少快照时从模板生成。"
                    ),
                    _cited_node("in-progress", "b0001", "正在运行。", body="正在运行。"),
                    _cited_node("generic", "b0002", quote, body="Follow best practices."),
                    _cited_node(
                        "speculation",
                        "b0003",
                        "cold starts may need retries.",
                        body="Enable retries.",
                    ),
                    _cited_node("fabricated", "b0002", "缺少快照时从文件生成。"),
                    _cited_node("wrong-block", "b0001", quote),
                    _cited_node("preference", "b0002", quote, kind="preference"),
                    _node("not-cited"),
                ],
                "edges": [
                    _cited_edge("read-only", "snapshot", "b0002", quote),
                    _cited_edge("read-only", "fabricated", "b0002", quote),
                    _cited_edge("missing", "snapshot", "b0002", quote),
                    _cited_edge("snapshot", "read-only", "b0001", quote),
                ],
            }
        ]
    )
    extraction = await extract.extract_session(
        client,
        template=await load_profile("sessions"),
        path="fixture.jsonl",
        blocks=render.render_session_blocks(raw),
        model="fake",
    )
    assert "SYNTHETIC_" not in client.prompts[0]
    assert [node.slug for node in extraction.nodes] == ["read-only", "snapshot"]
    assert [(edge.source, edge.target) for edge in extraction.edges] == [("read-only", "snapshot")]
    store = await _demo_store(tmp_path)
    source = SourceRef(type=SourceKind.SESSION, ref="fixture.jsonl", device="synthetic")
    report = await merge(store, extraction, project="demo", source=source)
    assert report.created == ["demo/decision/read-only", "demo/procedure/snapshot"]
    assert report.edges_added == 1
    node, body = await store.read("demo/decision/read-only")
    assert node.tier == Tier.CANDIDATE and node.source == [source]
    assert quote not in body


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        "not a JSON object",
        {},
        {"nodes": []},
        {"edges": []},
        {"nodes": [], "edges": {}},
        {"nodes": ["bad"], "edges": []},
        {"nodes": [_node("bad", evidence={})], "edges": []},
        {"nodes": [_node("bad", evidence=[{"block": "b0001", "quote": 1}])], "edges": []},
    ],
)
async def test_session_fails_on_malformed_response(payload: object) -> None:
    with pytest.raises(ExtractionFailed):
        await extract.extract_session(
            FakeClient([payload]),
            template="{text}",
            path="synthetic.txt",
            blocks=render.render_plaintext_blocks("Fixture verified."),
            model="fake",
        )


@pytest.mark.parametrize(
    "payload",
    [
        {"nodes": [], "edges": []},
        {"nodes": [_cited_node("noise", "b0001", "Thanks!", body="Thanks!")], "edges": []},
    ],
)
async def test_session_noise_can_succeed_with_no_candidates(payload: object) -> None:
    output = await extract.extract_session(
        FakeClient([payload]),
        template="{text}",
        path="synthetic.txt",
        blocks=render.render_plaintext_blocks("Thanks!"),
        model="fake",
    )
    assert output.nodes == [] and output.edges == []
    client = FakeClient([])
    output = await extract.extract_session(
        client,
        template="{text}",
        path="synthetic.jsonl",
        blocks=render.render_session_blocks('{"fragment":'),
        model="fake",
    )
    assert output.nodes == [] and output.edges == [] and client.prompts == []


async def test_session_windows_are_bounded_and_overlap_cannot_be_the_only_evidence() -> None:
    first = "A" * 115
    previous = "Synthetic cache defaults to read-only."
    current = "B" * 110
    client = FakeClient(
        [
            {"nodes": [], "edges": []},
            {
                "nodes": [
                    _cited_node("stale", "b0002", previous),
                    _node(
                        "usable",
                        evidence=[
                            {"block": "b0002", "quote": previous},
                            {"block": "b0003", "quote": current},
                        ],
                    ),
                ],
                "edges": [],
            },
        ]
    )
    output = await extract.extract_session(
        client,
        template="{text}",
        path="synthetic.txt",
        blocks=render.render_plaintext_blocks(f"{first}\n\n{previous}\n\n{current}"),
        model="fake",
        max_chars=196,
    )
    assert [node.slug for node in output.nodes] == ["usable"]
    assert len(client.prompts) == 2 and all(len(prompt) <= 196 for prompt in client.prompts)
    assert previous in client.prompts[0] and previous in client.prompts[1]
    assert first not in client.prompts[1]


async def test_session_dedupes_without_appending_paraphrases_or_misrouting_edges(
    tmp_path: Path,
) -> None:
    request = "Synthetic request limit is 5."
    cache = "Synthetic cache limit is 40."
    quote = f"{cache} {request}"
    blocks = [
        render.SessionBlock("b0001", "user", quote + " A" * 74),
        render.SessionBlock("b0002", "assistant", quote + " B" * 74),
    ]
    payloads = [
        {
            "nodes": [
                _cited_node("cache-limit", "b0001", quote, body="The cache limit is 40."),
                _cited_node("request-limit", "b0001", quote, body="The request limit is 5."),
                _cited_node("ambiguous", "b0001", quote, body="Requests are capped."),
                _cited_node("ambiguous", "b0001", quote, kind="decision", body="Cap requests."),
                _cited_node("cache-ceiling", "b0001", cache, title=cache, body=cache),
            ],
            "edges": [_cited_edge("request-limit", "ambiguous", "b0001", quote)],
        },
        {
            "nodes": [
                _cited_node("cache-limit", "b0002", quote, body="Cap the cache at 40."),
                _cited_node("alternate-cache", "b0002", quote, body="  The CACHE limit is 40. "),
                _cited_node("alternate-request", "b0002", quote, body="The request LIMIT is 5."),
                _cited_node("max-cache", "b0002", cache, title=cache, body=cache.rstrip(".")),
                _cited_node("request-ceiling", "b0002", request, body=request),
            ],
            "edges": [
                _cited_edge("alternate-cache", "request-limit", "b0002", quote),
                _cited_edge("max-cache", "alternate-request", "b0002", quote),
            ],
        },
    ]
    output = await extract.extract_session(
        FakeClient(payloads),
        template="{text}",
        path="synthetic.txt",
        blocks=blocks,
        model="fake",
        max_chars=265,
    )
    expected = [
        "cache-limit",
        "request-limit",
        "ambiguous",
        "ambiguous",
        "cache-ceiling",
        "request-ceiling",
    ]
    assert [node.slug for node in output.nodes] == expected
    assert [(edge.source, edge.target) for edge in output.edges] == [
        ("cache-ceiling", "request-limit"),
    ]
    store = await _demo_store(tmp_path)
    report = await merge(
        store,
        output,
        project="demo",
        source=SourceRef(type=SourceKind.SESSION, ref="synthetic.txt"),
    )
    assert len(report.created) == len(expected) and report.updated == []
    _, body = await store.read("demo/fact/cache-limit")
    assert body.strip() == "The cache limit is 40."


async def test_session_identity_collision_does_not_hide_distinct_claim_with_valid_slug() -> None:
    first = "Synthetic cache limit is 40."
    second = "Synthetic request limit is 5."
    payloads = [
        {"nodes": [_cited_node("limit", "b0001", first, body=first)], "edges": []},
        {
            "nodes": [
                _cited_node("limit", "b0002", second, body=second),
                _cited_node("request-limit", "b0002", second, body=second),
            ],
            "edges": [],
        },
    ]
    output = await extract.extract_session(
        FakeClient(payloads),
        template="{text}",
        path="synthetic.txt",
        blocks=render.render_plaintext_blocks(f"{first}\n\n{second}"),
        model="fake",
        max_chars=64,
    )
    assert [(node.slug, node.body) for node in output.nodes] == [
        ("limit", first),
        ("request-limit", second),
    ]


async def test_session_rejects_duplicate_response_keys_without_logging_values() -> None:
    class DuplicateKeysClient:
        async def complete(self, prompt: str, *, model: str, max_tokens: int = 32000) -> str:
            return '{"nodes":"SYNTHETIC_PRIVATE","nodes":[],"edges":[]}'

    with pytest.raises(ExtractionFailed) as err:
        await extract.extract_session(
            DuplicateKeysClient(),
            template="{text}",
            path="synthetic.txt",
            blocks=render.render_plaintext_blocks("Fixture verified."),
            model="fake",
        )
    assert "SYNTHETIC_PRIVATE" not in str(err.value)
