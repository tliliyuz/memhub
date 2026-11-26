"""长期记忆存储契约：条目修订、乐观锁、快照发布/回滚/停用与审计（规格 §3/§6）。"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from memhub.kb.errors import ConflictError, NotFoundError, RevisionConflict
from memhub.kb.memory import (
    CandidateWrite,
    EvidenceRef,
    parse_memories,
    plan_memories,
)
from memhub.kb.models import Base, KbWriteAudit
from memhub.kb.pgstore import REVISION_RE, PgKnowledgeStore, new_revision
from memhub.kb.session import create_sessionmaker

NOW = datetime(2026, 11, 20, 10, 0, tzinfo=UTC)


@pytest_asyncio.fixture
async def store(kb_engine: AsyncEngine) -> AsyncIterator[PgKnowledgeStore]:
    async with kb_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield PgKnowledgeStore(create_sessionmaker(kb_engine))


def _evidence(*node_ids: str) -> tuple[EvidenceRef, ...]:
    return tuple(
        EvidenceRef(
            node_id=node_id,
            project=node_id.split("/", 1)[0],
            session=f"{node_id.split('/', 1)[0]}:session-{index}.jsonl",
            session_ref=f"session-{index}.jsonl",
            observed_at=NOW.isoformat(),
        )
        for index, node_id in enumerate(node_ids)
    )


async def _create(
    store: PgKnowledgeStore,
    slug: str = "retry-backoff",
    *,
    conclusion: str = "失败后的重试要带指数退避。",
) -> dict[str, object]:
    return await store.create_memory(
        slug=slug,
        title="重试需要退避",
        conclusion=conclusion,
        boundary="幂等操作",
        invalidation="不可重放时不适用。",
        confidence=0.8,
        evidence=_evidence("a/fact/retry", "b/fact/retry"),
        contradicts=(),
        actor="memory-aggregate",
        reason="aggregate",
    )


async def test_create_update_and_deprecate_append_revisions(store: PgKnowledgeStore) -> None:
    created = await _create(store)
    assert REVISION_RE.match(str(created["revision"]))
    assert created["status"] == "active"
    assert len(await store.memory_revisions("retry-backoff")) == 1

    updated = await store.update_memory(
        "retry-backoff",
        expected_revision=str(created["revision"]),
        patch={"conclusion": "重试必须带退避。", "confidence": 0.9},
        actor="ui",
        reason="edit",
    )
    assert updated["revision"] != created["revision"]
    assert updated["conclusion"] == "重试必须带退避。"

    revisions = await store.memory_revisions("retry-backoff")
    assert [item["actor"] for item in revisions] == ["memory-aggregate", "ui"]
    assert revisions[1]["before"]["conclusion"] == "失败后的重试要带指数退避。"

    deprecated = await store.deprecate_memory(
        "retry-backoff",
        expected_revision=str(updated["revision"]),
        reason="被新准则替代",
        superseded_by=None,
        actor="ui",
    )
    assert deprecated["status"] == "deprecated"
    assert deprecated["deprecated_reason"] == "被新准则替代"
    assert len(await store.memory_revisions("retry-backoff")) == 3


async def test_stale_expected_revision_does_not_overwrite(store: PgKnowledgeStore) -> None:
    created = await _create(store)
    first = await store.update_memory(
        "retry-backoff",
        expected_revision=str(created["revision"]),
        patch={"title": "第一次修改"},
        actor="ui",
        reason="",
    )

    with pytest.raises(RevisionConflict):
        await store.update_memory(
            "retry-backoff",
            expected_revision=str(created["revision"]),
            patch={"title": "过期修改"},
            actor="ui",
            reason="",
        )

    current = await store.get_memory("retry-backoff")
    assert current["title"] == "第一次修改"
    assert current["revision"] == first["revision"]


async def test_deprecate_rejects_missing_target(store: PgKnowledgeStore) -> None:
    created = await _create(store)
    with pytest.raises(ConflictError):
        await store.deprecate_memory(
            "retry-backoff",
            expected_revision=str(created["revision"]),
            reason="替代",
            superseded_by="ghost",
            actor="ui",
        )
    with pytest.raises(NotFoundError):
        await store.get_memory("ghost")


async def test_snapshot_lifecycle_keeps_at_most_one_published(store: PgKnowledgeStore) -> None:
    await _create(store)
    deprecated = await _create(store, "old-guidance", conclusion="旧准则。")
    await store.deprecate_memory(
        "old-guidance",
        expected_revision=str(deprecated["revision"]),
        reason="过期",
        superseded_by=None,
        actor="ui",
    )

    first = await store.publish_memory_snapshot(actor="ui", note="第一版")
    assert first["status"] == "published"
    assert first["item_count"] == 1
    assert [item["slug"] for item in first["entries"]] == ["retry-backoff"]

    second = await store.publish_memory_snapshot(actor="ui", note="第二版")
    assert second["version"] != first["version"]
    current = await store.published_memory_snapshot()
    assert current is not None and current["version"] == second["version"]
    statuses = {item["version"]: item["status"] for item in await store.list_memory_snapshots()}
    assert statuses[first["version"]] == "superseded"
    assert statuses[second["version"]] == "published"

    activated = await store.activate_memory_snapshot(first["version"], actor="ui")
    assert activated["status"] == "published"
    current = await store.published_memory_snapshot()
    assert current is not None and current["version"] == first["version"]

    disabled = await store.disable_memory_snapshot(first["version"], actor="ui")
    assert disabled["status"] == "disabled"
    assert await store.published_memory_snapshot() is None

    with pytest.raises(ConflictError):
        await store.activate_memory_snapshot(first["version"], actor="ui")

    audits = await _audits(store)
    assert [item["action"] for item in audits] == [
        "memory_snapshot_publish",
        "memory_snapshot_publish",
        "memory_snapshot_activate",
        "memory_snapshot_disable",
    ]
    assert [item["memory_snapshot"] for item in audits] == [
        first["version"],
        second["version"],
        first["version"],
        first["version"],
    ]


async def test_candidate_upsert_replaces_latest_counts(store: PgKnowledgeStore) -> None:
    def candidate(sessions: int) -> CandidateWrite:
        return CandidateWrite(
            slug="retry-backoff",
            title="重试需要退避",
            conclusion="失败后的重试要带指数退避。",
            boundary="",
            invalidation="",
            confidence=0.7,
            evidence=_evidence("a/fact/retry"),
            contradicts=(),
            session_count=sessions,
            project_count=1,
            status="pending",
            reason="below_threshold",
        )

    await store.upsert_memory_candidate(candidate(2), now=NOW)
    await store.upsert_memory_candidate(candidate(3), now=NOW)
    body = await store.list_memory_candidates()
    [item] = body["items"]
    assert item["session_count"] == 3
    assert item["first_seen_at"] == item["last_seen_at"]


async def test_write_audit_records_memory_snapshot(store: PgKnowledgeStore) -> None:
    await store.record_write_audit(
        actor="worker",
        project="a",
        node_id=None,
        action="extract_session",
        result="ok",
        memory_snapshot=42,
    )
    [audit] = await _audits(store)
    assert audit["memory_snapshot"] == 42


async def _audits(store: PgKnowledgeStore) -> list[dict[str, object]]:
    async with store.sessions() as session:
        rows = (await session.scalars(select(KbWriteAudit).order_by(KbWriteAudit.id))).all()
    return [
        {
            "action": row.action,
            "actor": row.actor,
            "memory_snapshot": row.memory_snapshot,
            "result": row.result,
        }
        for row in rows
    ]


def test_revision_helper_shape() -> None:
    """候选写入与条目写入共用 16 位 hex 口径。"""
    assert REVISION_RE.match(new_revision())


# -- 聚合计划原子落库（规格 §5.4） ------------------------------------------


def _input_node(node_id: str, project: str, ref: str) -> dict[str, object]:
    return {
        "id": node_id,
        "project": project,
        "kind": "fact",
        "title": "重试需要退避",
        "body": "失败后指数退避，避免打爆下游。",
        "source": [{"type": "session", "ref": ref}],
        "updated_at": NOW,
    }


def _plan(
    nodes: dict[str, dict[str, object]],
    existing: dict[str, dict[str, object]],
    *,
    min_sessions: int = 3,
    min_projects: int = 2,
):
    payload = {
        "memories": [
            {
                "slug": "retry-with-backoff",
                "title": "重试需要退避",
                "conclusion": "失败后的重试要带指数退避。",
                "boundary": "幂等操作",
                "invalidation": "不可重放时不适用。",
                "confidence": 0.8,
                "evidence": list(nodes),
                "contradicts": [],
            }
        ]
    }
    drafts = parse_memories(json.dumps(payload, ensure_ascii=False), nodes)
    return plan_memories(
        drafts, nodes, existing, min_sessions=min_sessions, min_projects=min_projects
    )


def _threshold_nodes() -> dict[str, dict[str, object]]:
    return {
        "a/fact/retry": _input_node("a/fact/retry", "a", "a1.jsonl"),
        "b/fact/retry": _input_node("b/fact/retry", "b", "b1.jsonl"),
        "c/fact/retry": _input_node("c/fact/retry", "c", "c1.jsonl"),
    }


async def test_apply_plan_creates_entry_revision_and_promotes_candidate(
    store: PgKnowledgeStore,
) -> None:
    nodes = _threshold_nodes()
    plan = _plan(nodes, {})
    expected = await store.memory_states(["retry-with-backoff"])
    assert expected == {}

    [entry] = await store.apply_memory_plan(
        plan, expected_states=expected, actor="memory-aggregate", reason="aggregate"
    )

    assert entry["slug"] == "retry-with-backoff"
    assert entry["status"] == "active"
    assert len(await store.memory_revisions("retry-with-backoff")) == 1
    [candidate] = (await store.list_memory_candidates())["items"]
    assert candidate["status"] == "promoted"
    assert candidate["reason"] == "below_threshold"
    assert (candidate["session_count"], candidate["project_count"]) == (3, 3)


async def test_apply_plan_promotes_existing_candidate_and_keeps_first_seen(
    store: PgKnowledgeStore,
) -> None:
    nodes = _threshold_nodes()
    pending = _plan(nodes, {}, min_sessions=9)
    [candidate] = pending.candidates
    await store.upsert_memory_candidate(candidate, now=NOW)
    [before] = (await store.list_memory_candidates())["items"]

    ready = _plan(nodes, {})
    expected = await store.memory_states(["retry-with-backoff"])
    await store.apply_memory_plan(
        ready, expected_states=expected, actor="memory-aggregate", reason="aggregate"
    )

    [after] = (await store.list_memory_candidates())["items"]
    assert after["status"] == "promoted"
    assert after["reason"] == "below_threshold"
    assert after["first_seen_at"] == before["first_seen_at"]


async def test_apply_plan_merges_evidence_for_same_conclusion(store: PgKnowledgeStore) -> None:
    created = await _create(store, slug="retry-with-backoff")
    nodes = _threshold_nodes()
    existing = await store.memory_states(["retry-with-backoff"])
    plan = _plan(nodes, existing)

    [entry] = await store.apply_memory_plan(
        plan, expected_states=existing, actor="memory-aggregate", reason="aggregate"
    )

    node_ids = {item["node_id"] for item in entry["evidence"]}
    assert node_ids == {"a/fact/retry", "b/fact/retry", "c/fact/retry"}
    assert len(await store.memory_revisions("retry-with-backoff")) == 2
    current = await store.get_memory("retry-with-backoff")
    assert current["revision"] != created["revision"]


async def test_apply_plan_rejects_stale_state_without_writes(store: PgKnowledgeStore) -> None:
    nodes = _threshold_nodes()
    plan = _plan(nodes, {})
    expected = await store.memory_states(["retry-with-backoff"])
    # 规划之后有人先写了同 slug：创建计划必须整批作废，不覆盖也不留半成品。
    await _create(store, slug="retry-with-backoff")
    with pytest.raises(ConflictError):
        await store.apply_memory_plan(
            plan, expected_states=expected, actor="memory-aggregate", reason="aggregate"
        )
    assert len(await store.memory_revisions("retry-with-backoff")) == 1
    assert (await store.list_memory_candidates())["items"] == []

    # 更新计划同理：拿到 expected 之后条目被改过，旧结论不能写回去。
    stale = await store.memory_states(["retry-with-backoff"])
    current = await store.get_memory("retry-with-backoff")
    await store.update_memory(
        "retry-with-backoff",
        expected_revision=str(current["revision"]),
        patch={"conclusion": "另一个人改过的结论。"},
        actor="ui",
        reason="",
    )
    with pytest.raises(ConflictError):
        await store.apply_memory_plan(
            _plan(nodes, stale),
            expected_states=stale,
            actor="memory-aggregate",
            reason="aggregate",
        )
    assert (await store.get_memory("retry-with-backoff"))["conclusion"] == "另一个人改过的结论。"
    assert len(await store.memory_revisions("retry-with-backoff")) == 2


async def test_apply_plan_writes_only_candidates_below_threshold(
    store: PgKnowledgeStore,
) -> None:
    nodes = {"a/fact/retry": _input_node("a/fact/retry", "a", "a1.jsonl")}
    plan = _plan(nodes, {})
    assert plan.writes == []
    expected = await store.memory_states(["retry-with-backoff"])

    written = await store.apply_memory_plan(
        plan, expected_states=expected, actor="memory-aggregate", reason="aggregate"
    )

    assert written == []
    [candidate] = (await store.list_memory_candidates())["items"]
    assert candidate["status"] == "pending"
    assert candidate["reason"] == "below_threshold"
    with pytest.raises(NotFoundError):
        await store.get_memory("retry-with-backoff")
