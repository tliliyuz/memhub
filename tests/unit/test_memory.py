"""长期记忆的纯逻辑：响应校验、门槛、冲突裁决与注入选择（规格 §5/§7）。

这些用例不碰数据库：聚合响应、输入节点与现有条目状态都以普通映射传入，
失败应来自业务规则，而不是夹具或连接。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from memhub.kb.memory import (
    MemoryAggregateError,
    normalize_memory_slug,
    parse_memories,
    plan_memories,
    render_memory_block,
    select_memories,
)

NOW = datetime(2026, 11, 20, 10, 0, tzinfo=UTC)


def _node(
    node_id: str,
    *,
    project: str,
    ref: str | None = None,
    title: str = "重试需要退避",
    body: str = "失败后指数退避，避免打爆下游。",
) -> dict[str, object]:
    source = [{"type": "session", "ref": ref}] if ref else []
    return {
        "id": node_id,
        "project": project,
        "kind": "fact",
        "title": title,
        "body": body,
        "source": source,
        "updated_at": NOW,
    }


def _payload(*memories: dict[str, object]) -> str:
    return json.dumps({"memories": list(memories)}, ensure_ascii=False)


def _memory(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "slug": "retry-with-backoff",
        "title": "重试需要退避",
        "conclusion": "失败后的重试要带指数退避。",
        "boundary": "适用于可重放的幂等操作。",
        "invalidation": "下游不支持重放时不适用。",
        "confidence": 0.8,
        "evidence": ["a/fact/retry", "b/fact/retry"],
        "contradicts": [],
    }
    data.update(overrides)
    return data


def test_normalize_memory_slug_rejects_non_kebab() -> None:
    assert normalize_memory_slug(" Retry_With Backoff ") == "retry-with-backoff"
    assert normalize_memory_slug("验证/先补测试") == ""
    assert normalize_memory_slug("") == ""


def test_parse_memories_drops_items_with_unknown_or_empty_evidence() -> None:
    nodes = {
        "a/fact/retry": _node("a/fact/retry", project="a", ref="a1.jsonl"),
        "b/fact/retry": _node("b/fact/retry", project="b", ref="b1.jsonl"),
    }
    raw = _payload(
        _memory(slug="good", evidence=["a/fact/retry"]),
        _memory(slug="ghost", evidence=["missing/fact/x"]),
        _memory(slug="empty", evidence=[]),
        _memory(slug="验证", evidence=["a/fact/retry"]),
    )

    drafts = parse_memories(raw, nodes)

    assert [draft.slug for draft in drafts] == ["good"]


def test_parse_memories_rejects_broken_envelope() -> None:
    nodes = {"a/fact/retry": _node("a/fact/retry", project="a")}

    with pytest.raises(MemoryAggregateError):
        parse_memories("not json", nodes)
    with pytest.raises(MemoryAggregateError):
        parse_memories(json.dumps({"memories": {}}), nodes)
    with pytest.raises(MemoryAggregateError):
        parse_memories(json.dumps({"items": []}), nodes)


def test_threshold_requires_three_sessions_and_two_projects() -> None:
    nodes = {
        "a/fact/retry": _node("a/fact/retry", project="a", ref="a1.jsonl"),
        "a/fact/observe": _node("a/fact/observe", project="a", ref="a2.jsonl"),
        "b/fact/retry": _node("b/fact/retry", project="b", ref="b1.jsonl"),
    }
    draft = parse_memories(_payload(_memory(evidence=list(nodes))), nodes)[0]

    plan = plan_memories([draft], nodes, {}, min_sessions=3, min_projects=2)
    assert plan.writes[0].session_count == 3
    assert plan.writes[0].project_count == 2
    assert plan.writes[0].action == "create"
    assert {item.node_id for item in plan.writes[0].evidence} == set(nodes)
    assert plan.candidates == []

    plan = plan_memories([draft], nodes, {}, min_sessions=4, min_projects=2)
    assert plan.writes == []
    [candidate] = plan.candidates
    assert candidate.status == "pending"
    assert candidate.reason == "below_threshold"
    assert candidate.session_count == 3


def test_same_conclusion_merges_evidence_and_different_conclusion_conflicts() -> None:
    nodes = {
        "a/fact/retry": _node("a/fact/retry", project="a", ref="a1.jsonl"),
        "b/fact/retry": _node("b/fact/retry", project="b", ref="b1.jsonl"),
        "c/fact/retry": _node("c/fact/retry", project="c", ref="c1.jsonl"),
    }
    draft = parse_memories(_payload(_memory(evidence=list(nodes))), nodes)[0]
    existing = {
        "retry-with-backoff": {
            "status": "active",
            "conclusion": "失败后的重试要带指数退避。",
            "evidence": [{"node_id": "old/fact/retry", "project": "old"}],
        }
    }

    plan = plan_memories([draft], nodes, existing, min_sessions=3, min_projects=2)
    [write] = plan.writes
    assert write.action == "update"
    assert {item.node_id for item in write.evidence} == set(nodes) | {"old/fact/retry"}
    assert plan.candidates == []

    conflicting = parse_memories(
        _payload(_memory(conclusion="重试不要退避。", evidence=list(nodes))), nodes
    )[0]
    plan = plan_memories([conflicting], nodes, existing, min_sessions=3, min_projects=2)
    assert plan.writes == []
    [candidate] = plan.candidates
    assert candidate.status == "conflict"
    assert candidate.reason == "conclusion_differs"
    assert candidate.contradicts == ("retry-with-backoff",)


def test_deprecated_entry_is_not_resurrected() -> None:
    nodes = {
        "a/fact/retry": _node("a/fact/retry", project="a", ref="a1.jsonl"),
        "b/fact/retry": _node("b/fact/retry", project="b", ref="b1.jsonl"),
        "c/fact/retry": _node("c/fact/retry", project="c", ref="c1.jsonl"),
    }
    draft = parse_memories(_payload(_memory(evidence=list(nodes))), nodes)[0]
    existing = {"retry-with-backoff": {"status": "deprecated", "conclusion": "旧结论"}}

    plan = plan_memories([draft], nodes, existing, min_sessions=3, min_projects=2)
    assert plan.writes == []
    [candidate] = plan.candidates
    assert candidate.status == "conflict"
    assert candidate.reason == "deprecated"


def test_session_count_deduplicates_repeated_source_refs() -> None:
    nodes = {
        "a/fact/one": _node("a/fact/one", project="a", ref="same.jsonl"),
        "a/fact/two": _node("a/fact/two", project="a", ref="same.jsonl"),
        "b/fact/three": _node("b/fact/three", project="b", ref="b.jsonl"),
    }
    draft = parse_memories(_payload(_memory(evidence=list(nodes))), nodes)[0]

    plan = plan_memories([draft], nodes, {}, min_sessions=3, min_projects=2)
    assert plan.writes == []
    [candidate] = plan.candidates
    assert candidate.session_count == 2
    assert candidate.project_count == 2


def test_select_memories_uses_positive_scores_top_k_and_budget() -> None:
    entries = [
        {
            "slug": "retry-backoff",
            "title": "重试退避",
            "conclusion": "重试需要指数退避，避免打爆下游。",
            "boundary": "幂等操作",
            "invalidation": "",
            "confidence": 0.9,
        },
        {
            "slug": "schema-migration",
            "title": "迁移先备份",
            "conclusion": "改表前先备份。",
            "boundary": "生产库",
            "invalidation": "",
            "confidence": 0.8,
        },
        {
            "slug": "retry-jitter",
            "title": "退避加抖动",
            "conclusion": "重试退避要加随机抖动。",
            "boundary": "高并发",
            "invalidation": "",
            "confidence": 0.7,
        },
    ]

    selected = select_memories(entries, "重试退避打爆下游", top_k=1, budget_chars=200)
    assert [item["slug"] for item in selected] == ["retry-backoff"]

    selected = select_memories(entries, "重试退避", top_k=10, budget_chars=80)
    assert [item["slug"] for item in selected] == ["retry-backoff"]

    assert select_memories(entries, "重试退避", top_k=10, budget_chars=10) == []

    assert select_memories(entries, "完全无关的词汇", top_k=8, budget_chars=4000) == []
    assert select_memories(entries, "", top_k=8, budget_chars=4000) == []


def test_render_memory_block_marks_guidance_not_evidence() -> None:
    block = render_memory_block(
        [
            {
                "slug": "retry-backoff",
                "title": "重试退避",
                "conclusion": "重试需要指数退避。",
                "boundary": "幂等操作",
                "invalidation": "不可重放时不适用。",
                "confidence": 0.9,
            }
        ]
    )
    assert "retry-backoff" in block
    assert "重试需要指数退避。" in block
    assert "不是事实来源" in block
    assert "不得写入 evidence" in block

    empty = render_memory_block([])
    assert empty == "（本次未注入长期记忆）"
