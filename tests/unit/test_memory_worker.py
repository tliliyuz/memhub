"""长期记忆 worker 层：环境配置、聚合输入、注入选择与聚合落库（规格 §5–§7）。

聚合测试用替身存储，并按 AC-8 断言：聚合只读 canonical 节点与门槛所需的条目状态，
从不读取当前快照或条目正文作为模型输入。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest

from memhub.kb.memory import MemoryAggregateError
from memhub.worker.memory import (
    MemoryContext,
    MemorySettings,
    aggregate_memories,
    load_memory_context,
    render_node_inputs,
)

NOW = datetime(2026, 11, 26, 3, 0, tzinfo=UTC)


class FakeClient:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.prompts: list[str] = []
        self.models: list[str] = []

    async def complete(self, prompt: str, *, model: str, max_tokens: int = 32000) -> str:
        self.prompts.append(prompt)
        self.models.append(model)
        return self.reply


def _node(node_id: str, *, project: str, ref: str | None = None) -> dict[str, Any]:
    return {
        "id": node_id,
        "project": project,
        "kind": "fact",
        "title": "重试需要退避",
        "body": "失败后指数退避，避免打爆下游。",
        "source": [{"type": "session", "ref": ref}] if ref else [],
        "updated_at": NOW,
    }


def _reply(evidence: list[str]) -> str:
    return json.dumps(
        {
            "memories": [
                {
                    "slug": "retry-with-backoff",
                    "title": "重试需要退避",
                    "conclusion": "失败后的重试要带指数退避。",
                    "boundary": "幂等操作",
                    "invalidation": "不可重放时不适用。",
                    "confidence": 0.8,
                    "evidence": evidence,
                    "contradicts": [],
                }
            ]
        },
        ensure_ascii=False,
    )


def _threshold_nodes() -> list[dict[str, Any]]:
    return [
        _node("a/fact/retry", project="a", ref="a1.jsonl"),
        _node("b/fact/retry", project="b", ref="b1.jsonl"),
        _node("c/fact/retry", project="c", ref="c1.jsonl"),
    ]


def _entry(slug: str = "retry-backoff") -> dict[str, Any]:
    return {
        "slug": slug,
        "title": "重试退避",
        "conclusion": "重试需要指数退避，避免打爆下游。",
        "boundary": "幂等操作",
        "invalidation": "",
        "confidence": 0.9,
    }


# -- 配置 -------------------------------------------------------------------


def test_memory_settings_defaults_and_env_parsing() -> None:
    settings = MemorySettings.from_env({})
    assert (settings.top_k, settings.inject_chars) == (8, 4000)
    assert settings.disabled_projects == frozenset()

    parsed = MemorySettings.from_env(
        {
            "MEMHUB_MEMORY_TOP_K": "3",
            "MEMHUB_MEMORY_INJECT_CHARS": "1200",
            "MEMHUB_MEMORY_INJECT_DISABLED_PROJECTS": " alpha, ,beta ,",
        }
    )
    assert (parsed.top_k, parsed.inject_chars) == (3, 1200)
    assert parsed.disabled_projects == frozenset({"alpha", "beta"})


@pytest.mark.parametrize(
    "env",
    [
        {"MEMHUB_MEMORY_TOP_K": "0"},
        {"MEMHUB_MEMORY_TOP_K": "11"},
        {"MEMHUB_MEMORY_TOP_K": "many"},
        {"MEMHUB_MEMORY_INJECT_CHARS": "0"},
        {"MEMHUB_MEMORY_INJECT_CHARS": "-3"},
        {"MEMHUB_MEMORY_INJECT_CHARS": "lots"},
    ],
)
def test_memory_settings_rejects_invalid_values(env: dict[str, str]) -> None:
    with pytest.raises(ValueError):
        MemorySettings.from_env(env)


# -- 聚合输入 ---------------------------------------------------------------


def test_render_node_inputs_truncates_body_from_newest_and_drops_oldest() -> None:
    nodes = [
        {
            "id": f"p/fact/n{index:03d}",
            "project": "p",
            "kind": "fact",
            "title": "重试需要退避",
            "body": f"{index:03d}" + "x" * 997,
            "source": [],
            "updated_at": NOW,
        }
        for index in range(120)
    ]

    text = render_node_inputs(nodes)

    assert len(text) <= 60000
    lines = [json.loads(line) for line in text.splitlines()]
    assert lines[0]["id"] == "p/fact/n000"
    assert all(len(item["body"]) == 600 for item in lines)
    assert lines[0]["body"].startswith("000")
    kept = {item["id"] for item in lines}
    assert "p/fact/n119" not in kept
    assert [item["id"] for item in lines] == sorted(kept)


# -- 注入选择 ---------------------------------------------------------------


def test_memory_context_selects_top_k_and_honours_disabled_projects() -> None:
    context = MemoryContext(
        version=7,
        entries=(
            _entry("retry-backoff"),
            {
                **_entry("schema-migration"),
                "title": "迁移先备份",
                "conclusion": "改表前先备份生产库。",
                "boundary": "生产库",
            },
        ),
        settings=MemorySettings(top_k=1, inject_chars=4000),
    )

    block = context.block("重试退避打爆下游", project="a")
    assert "retry-backoff" in block
    assert "schema-migration" not in block
    assert context.audit_version("a") == 7

    disabled = "a"
    context = MemoryContext(
        version=7,
        entries=(_entry(),),
        settings=MemorySettings(disabled_projects=frozenset({disabled})),
    )
    assert context.block("重试退避", project=disabled) == "（本次未注入长期记忆）"
    assert context.audit_version(disabled) is None

    empty = MemoryContext()
    assert empty.block("重试退避", project="a") == "（本次未注入长期记忆）"
    assert empty.audit_version("a") is None


async def test_load_memory_context_freezes_the_published_snapshot() -> None:
    class SnapshotStore:
        async def published_memory_snapshot(self) -> dict[str, Any]:
            return {"version": 12, "entries": [_entry()], "item_count": 1}

    class EmptyStore:
        async def published_memory_snapshot(self) -> None:
            return None

    context = await load_memory_context(SnapshotStore())
    assert context.version == 12
    assert [entry["slug"] for entry in context.entries] == ["retry-backoff"]
    assert "retry-backoff" in context.block("重试退避", project="a")

    empty = await load_memory_context(EmptyStore())
    assert empty.version is None
    assert empty.audit_version("a") is None


# -- 聚合落库 ---------------------------------------------------------------


class AggregateStore:
    """只实现聚合允许的读取与写入；其他属性一律视为违规调用。"""

    def __init__(self, nodes: list[dict[str, Any]], existing: dict[str, Any] | None = None):
        self.nodes = nodes
        self.existing = existing or {}
        self.applied: list[Any] = []
        self.expected: list[dict[str, Any]] = []
        self.published: list[str] = []
        self.limits: list[tuple[datetime, int]] = []

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"聚合不应调用 {name}")

    async def recent_memory_inputs(self, *, since: datetime, limit: int) -> list[dict[str, Any]]:
        self.limits.append((since, limit))
        return self.nodes

    async def memory_states(self, slugs: list[str]) -> dict[str, Any]:
        return {slug: self.existing[slug] for slug in slugs if slug in self.existing}

    async def apply_memory_plan(
        self,
        plan: Any,
        *,
        expected_states: dict[str, Any],
        actor: str,
        reason: str,
    ) -> list[dict[str, Any]]:
        self.applied.append((plan, expected_states, actor, reason))
        return []

    async def publish_memory_snapshot(self, *, actor: str, note: str) -> dict[str, Any]:
        self.published.append(note)
        return {"version": 3, "note": note, "actor": actor}


async def test_aggregate_memories_writes_plan_and_never_reads_memory_tables() -> None:
    nodes = _threshold_nodes()
    store = AggregateStore(nodes)
    client = FakeClient(_reply([item["id"] for item in nodes]))

    report = await aggregate_memories(
        client,
        store,
        model="memory-model",
        template="节点：\n{nodes}",
        since_days=7,
        min_sessions=3,
        min_projects=2,
        max_nodes=100,
        now=NOW,
    )

    assert store.limits == [(datetime(2026, 11, 19, 3, 0, tzinfo=UTC), 100)]
    [plan] = [entry[0] for entry in store.applied]
    assert [write.action for write in plan.writes] == ["create"]
    assert client.models == ["memory-model"]
    assert "a/fact/retry" in client.prompts[0]
    assert report.nodes == 3
    assert report.drafts == 1
    assert [(item.slug, item.action) for item in report.writes] == [
        ("retry-with-backoff", "create")
    ]
    assert store.published == []


async def test_aggregate_memories_dry_run_does_not_write_or_publish() -> None:
    nodes = _threshold_nodes()
    store = AggregateStore(nodes)
    client = FakeClient(_reply([item["id"] for item in nodes]))

    report = await aggregate_memories(
        client,
        store,
        model="m",
        template="{nodes}",
        dry_run=True,
        publish=True,
        now=NOW,
    )

    assert client.prompts, "dry-run 仍然调用模型"
    assert store.applied == []
    assert store.published == []
    assert report.dry_run is True
    assert [item.action for item in report.writes] == ["create"]


async def test_aggregate_memories_publishes_with_fixed_note() -> None:
    nodes = _threshold_nodes()
    store = AggregateStore(nodes)
    client = FakeClient(_reply([item["id"] for item in nodes]))

    report = await aggregate_memories(
        client,
        store,
        model="m",
        template="{nodes}",
        since_days=14,
        publish=True,
        now=NOW,
    )

    assert store.published == ["aggregate since=14d"]
    assert report.published == 3


async def test_aggregate_memories_without_nodes_skips_the_model() -> None:
    client = FakeClient(_reply([]))
    store = AggregateStore([])

    report = await aggregate_memories(client, store, model="m", template="{nodes}", now=NOW)

    assert report.nodes == 0
    assert client.prompts == []
    assert store.applied == []


async def test_aggregate_memories_propagates_structural_failures() -> None:
    store = AggregateStore(_threshold_nodes())
    with pytest.raises(MemoryAggregateError):
        await aggregate_memories(
            FakeClient("not json"),
            store,
            model="m",
            template="{nodes}",
            now=NOW,
        )
    assert store.applied == []
