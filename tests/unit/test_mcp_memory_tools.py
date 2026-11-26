"""MCP 只读长期记忆工具：可见性、快照数据面与字段裁剪（ADR-0019）。

这些用例走真实的 `PgKnowledgeStore`：记忆真源在 PG，快照发布与条目状态都由存储层
提供，工具层只读当前 `published` 快照。
"""

from __future__ import annotations

import json
from typing import Any

import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from memhub.kb.memory import EvidenceRef
from memhub.kb.models import Base, KbWriteAudit
from memhub.kb.pgstore import PgKnowledgeStore
from memhub.kb.session import create_sessionmaker
from memhub.mcp.tools import call_tool, tools_for

READ_TOOLS = {"kb_search", "kb_read", "kb_related", "kb_audit_list"}
MEMORY_TOOLS = {"kb_memory_search", "kb_memory_read"}
WRITE_TOOLS = {"kb_write_candidate", "kb_update_candidate", "kb_deprecate"}


@pytest_asyncio.fixture
async def store(kb_engine: AsyncEngine) -> PgKnowledgeStore:
    async with kb_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return PgKnowledgeStore(create_sessionmaker(kb_engine))


def _evidence(project: str) -> tuple[EvidenceRef, ...]:
    return (
        EvidenceRef(
            node_id=f"{project}/fact/retry",
            project=project,
            session=f"{project}:session-1.jsonl",
            session_ref="session-1.jsonl",
            observed_at="2026-11-20T10:00:00+00:00",
        ),
    )


async def _seed(
    store: PgKnowledgeStore,
    slug: str = "retry-backoff",
    *,
    title: str = "重试退避",
    conclusion: str = "重试需要指数退避，避免打爆下游。",
) -> dict[str, Any]:
    return await store.create_memory(
        slug=slug,
        title=title,
        conclusion=conclusion,
        boundary="幂等操作",
        invalidation="不可重放时不适用。",
        confidence=0.8,
        evidence=_evidence("memhub"),
        contradicts=(),
        actor="memory-aggregate",
        reason="seed",
    )


async def _invoke(
    store: PgKnowledgeStore,
    name: str,
    arguments: dict[str, Any],
    *,
    memory: bool = True,
) -> tuple[dict[str, Any], bool]:
    result = await call_tool(name, arguments, store, memory=memory)
    return json.loads(result["content"][0]["text"]), bool(result["isError"])


def test_tools_for_combines_scope_and_memory() -> None:
    assert {tool["name"] for tool in tools_for(writable=False)} == READ_TOOLS
    assert {tool["name"] for tool in tools_for(writable=True)} == READ_TOOLS | WRITE_TOOLS
    assert {tool["name"] for tool in tools_for(writable=False, memory=True)} == (
        READ_TOOLS | MEMORY_TOOLS
    )
    assert {tool["name"] for tool in tools_for(writable=True, memory=True)} == (
        READ_TOOLS | WRITE_TOOLS | MEMORY_TOOLS
    )


async def test_memory_tools_require_explicit_memory_grant(store: PgKnowledgeStore) -> None:
    await _seed(store)
    for name, arguments in (
        ("kb_memory_search", {"query": "重试"}),
        ("kb_memory_read", {"slug": "retry-backoff"}),
    ):
        payload, is_error = await _invoke(store, name, arguments, memory=False)
        # 与越权直读同码，不泄露快照或条目是否存在。
        assert is_error and payload["code"] == 3001, name


async def test_search_without_published_snapshot_returns_empty_hint(
    store: PgKnowledgeStore,
) -> None:
    await _seed(store)  # 有条目但没有发布快照，数据面仍为空。
    payload, is_error = await _invoke(store, "kb_memory_search", {"query": "重试"})
    assert not is_error
    assert payload["results"] == []
    assert isinstance(payload["hint"], str) and payload["hint"]
    assert "version" not in payload


async def test_read_without_published_snapshot_returns_not_found(
    store: PgKnowledgeStore,
) -> None:
    await _seed(store)
    payload, is_error = await _invoke(store, "kb_memory_read", {"slug": "retry-backoff"})
    assert is_error and payload["code"] == 3001


async def test_search_ranks_snapshot_entries_with_version(store: PgKnowledgeStore) -> None:
    await _seed(store)
    await _seed(store, "schema-migration", title="迁移先备份", conclusion="改表前先备份。")
    await _seed(store, "retry-jitter", title="退避加抖动", conclusion="重试退避要加随机抖动。")
    snapshot = await store.publish_memory_snapshot(actor="ui", note="seed")

    payload, is_error = await _invoke(store, "kb_memory_search", {"query": "打爆下游"})
    assert not is_error
    assert payload["version"] == snapshot["version"]
    assert [item["slug"] for item in payload["results"]] == ["retry-backoff"]
    [item] = payload["results"]
    assert set(item) == {"slug", "title", "conclusion", "boundary", "confidence", "score"}
    assert item["title"] == "重试退避"
    assert item["confidence"] == 0.8
    assert 0 < item["score"] <= 0.99

    payload, _ = await _invoke(store, "kb_memory_search", {"query": "重试退避", "limit": 2})
    scores = [item["score"] for item in payload["results"]]
    assert len(scores) == 2
    assert scores == sorted(scores, reverse=True)


async def test_search_defaults_to_five_and_validates_params(store: PgKnowledgeStore) -> None:
    for index in range(6):
        await _seed(
            store,
            f"retry-{index}",
            title=f"重试退避 {index}",
            conclusion="重试需要指数退避。",
        )
    await store.publish_memory_snapshot(actor="ui", note="seed")

    payload, is_error = await _invoke(store, "kb_memory_search", {"query": "重试退避"})
    assert not is_error
    assert len(payload["results"]) == 5

    for arguments in (
        {"query": "重试退避", "limit": 21},
        {"query": "重试退避", "limit": 0},
        {"query": ""},
        {"query": "x" * 513},
        {},
    ):
        payload, is_error = await _invoke(store, "kb_memory_search", arguments)
        assert is_error and payload["code"] == 3004, arguments


async def test_search_skips_deprecated_entries_in_frozen_snapshot(
    store: PgKnowledgeStore,
) -> None:
    created = await _seed(store)
    await store.publish_memory_snapshot(actor="ui", note="seed")
    await store.deprecate_memory(
        "retry-backoff",
        expected_revision=str(created["revision"]),
        reason="过期",
        superseded_by=None,
        actor="ui",
    )
    payload, is_error = await _invoke(store, "kb_memory_search", {"query": "重试退避"})
    assert not is_error
    assert payload["results"] == []


async def test_read_returns_active_entry_with_trimmed_evidence(
    store: PgKnowledgeStore,
) -> None:
    created = await _seed(store)
    snapshot = await store.publish_memory_snapshot(actor="ui", note="seed")

    payload, is_error = await _invoke(store, "kb_memory_read", {"slug": "retry-backoff"})
    assert not is_error
    assert set(payload) == {
        "version",
        "title",
        "conclusion",
        "boundary",
        "invalidation",
        "confidence",
        "status",
        "revision",
        "evidence",
    }
    assert payload["version"] == snapshot["version"]
    assert payload["status"] == "active"
    assert payload["revision"] == created["revision"]
    assert payload["conclusion"] == "重试需要指数退避，避免打爆下游。"
    [reference] = payload["evidence"]
    # 证据只保留跨项目可复用的来源元数据，裁剪 node_id。
    assert set(reference) == {"project", "session", "session_ref", "observed_at"}
    assert reference["project"] == "memhub"
    assert reference["session"] == "memhub:session-1.jsonl"


async def test_read_hides_deprecated_and_missing_entries(store: PgKnowledgeStore) -> None:
    created = await _seed(store)
    await store.publish_memory_snapshot(actor="ui", note="seed")
    await store.deprecate_memory(
        "retry-backoff",
        expected_revision=str(created["revision"]),
        reason="过期",
        superseded_by=None,
        actor="ui",
    )
    for slug in ("retry-backoff", "ghost"):
        payload, is_error = await _invoke(store, "kb_memory_read", {"slug": slug})
        assert is_error and payload["code"] == 3001, slug

    for arguments in ({"slug": "Retry-Backoff"}, {"slug": "x" * 101}, {}):
        payload, is_error = await _invoke(store, "kb_memory_read", arguments)
        assert is_error and payload["code"] == 3004, arguments


async def test_memory_reads_do_not_write_audit(
    store: PgKnowledgeStore, kb_engine: AsyncEngine
) -> None:
    await _seed(store)
    await store.publish_memory_snapshot(actor="ui", note="seed")
    maker = create_sessionmaker(kb_engine)

    async def audit_count() -> int:
        async with maker() as session:
            return int(await session.scalar(select(func.count()).select_from(KbWriteAudit)) or 0)

    before = await audit_count()
    await _invoke(store, "kb_memory_search", {"query": "重试退避"})
    await _invoke(store, "kb_memory_read", {"slug": "retry-backoff"})
    assert await audit_count() == before
