"""`kb_write_candidate` 的输入校验、冲突、去重、内容与每日上限（ADR-0014 写入即 canonical）。"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from memhub.contract import Kind, NodeFrontmatter, Tier
from memhub.kb import catalog, manage
from memhub.kb.store import KnowledgeStore
from memhub.mcp.server import call_tool

GRANT_ID = "abcdef012345"


@pytest.fixture
async def store(tmp_path: Path) -> KnowledgeStore:
    kb = KnowledgeStore(tmp_path)
    await catalog.create_kb(kb, kb_id="sample", name="sample")
    return kb


async def invoke(
    store: KnowledgeStore,
    args: dict,
    *,
    projects: frozenset[str] | None = None,
    grant_id: str = GRANT_ID,
    writable: bool = True,
) -> dict:
    result = await call_tool(
        "kb_write_candidate",
        args,
        store,
        **({} if projects is None else {"projects": projects}),
        grant_id=grant_id,
        writable=writable,
    )
    payload = json.loads(result["content"][0]["text"])
    assert result["isError"] == ("code" in payload)
    return payload


def evidence(*refs: str) -> list[dict]:
    return [
        {
            "type": "session",
            "ref": ref,
            "captured_at": datetime.now(UTC).isoformat(),
        }
        for ref in refs
    ]


GOOD_ARGS = {
    "project": "sample",
    "kind": "fact",
    "slug": "mcp-write-fixture",
    "title": "MCP 写候选夹具",
    "body": "这是一段至少二十个字符的正文，用来通过内容门槛的最低长度检查。",
    "evidence": evidence("session:abc"),
}


async def test_write_requires_writable_scope(store: KnowledgeStore) -> None:
    payload = await invoke(store, GOOD_ARGS, writable=False)
    assert payload["code"] == 3004


async def test_write_rejects_unknown_project(store: KnowledgeStore) -> None:
    payload = await invoke(store, {**GOOD_ARGS, "project": "missing"})
    assert payload["code"] == 1003
    assert payload["data"]["reason"] == "project_unavailable"


async def test_write_rejects_archived_project(store: KnowledgeStore) -> None:
    await catalog.delete_kb(store, "sample", actor="fixture")
    payload = await invoke(store, GOOD_ARGS)
    assert payload["code"] == 1003
    assert payload["data"]["reason"] == "project_unavailable"


async def test_write_creates_canonical_node(store: KnowledgeStore) -> None:
    payload = await invoke(store, GOOD_ARGS)
    assert "code" not in payload
    assert payload["tier"] == "canonical"
    assert payload["id"] == "sample/fact/mcp-write-fixture"
    node, body = await store.read(payload["id"])
    assert node.tier is Tier.CANONICAL
    assert node.title == "MCP 写候选夹具"
    assert body.startswith("这是一段")
    assert any(src.ref == f"mcp:{GRANT_ID}" for src in node.source)
    assert any(src.ref == "session:abc" for src in node.source)


async def test_slug_conflict_canonical(store: KnowledgeStore) -> None:
    now = datetime.now(UTC)
    await store.write(
        "sample/fact/mcp-write-fixture",
        NodeFrontmatter(
            id="sample/fact/mcp-write-fixture",
            kind=Kind.FACT,
            title="既有 canonical",
            project="sample",
            tier=Tier.CANONICAL,
            created_at=now,
            updated_at=now,
        ),
        "既有正文",
    )
    payload = await invoke(store, GOOD_ARGS)
    assert payload["code"] == 1010
    assert payload["data"]["reason"] == "slug_conflict_canonical"


async def test_slug_conflict_candidate(store: KnowledgeStore) -> None:
    # `slug_conflict_candidate` 只保留给历史存量 candidate 行。
    now = datetime.now(UTC)
    await store.write(
        "sample/fact/mcp-write-fixture",
        NodeFrontmatter(
            id="sample/fact/mcp-write-fixture",
            kind=Kind.FACT,
            title="历史候选",
            project="sample",
            tier=Tier.CANDIDATE,
            created_at=now,
            updated_at=now,
        ),
        "历史候选正文，长度足够。",
    )
    payload = await invoke(store, GOOD_ARGS)
    assert payload["code"] == 1010
    assert payload["data"]["reason"] == "slug_conflict_candidate"


async def test_content_duplicate_across_titles(store: KnowledgeStore) -> None:
    await invoke(store, GOOD_ARGS)
    payload = await invoke(
        store,
        {
            **GOOD_ARGS,
            "slug": "mcp-write-fixture-2",
            "title": "另一个标题",
            "body": GOOD_ARGS["body"].upper(),  # 归一化后相同
        },
    )
    assert payload["code"] == 1010
    assert payload["data"]["reason"] == "content_duplicate"


async def test_evidence_missing(store: KnowledgeStore) -> None:
    payload = await invoke(store, {**GOOD_ARGS, "evidence": []})
    assert payload["code"] == 1003
    assert payload["data"]["reason"] == "evidence_missing"


async def test_evidence_invalid_type(store: KnowledgeStore) -> None:
    payload = await invoke(store, {**GOOD_ARGS, "evidence": [{"type": "bogus", "ref": "x"}]})
    assert payload["code"] == 1003
    assert payload["data"]["reason"] == "evidence_invalid"


async def test_evidence_omitted(store: KnowledgeStore) -> None:
    payload = await invoke(store, {key: val for key, val in GOOD_ARGS.items() if key != "evidence"})
    assert payload["code"] == 1003
    assert payload["data"]["reason"] == "evidence_missing"


async def test_evidence_cannot_supply_caller_marker(store: KnowledgeStore) -> None:
    payload = await invoke(store, {**GOOD_ARGS, "evidence": evidence("mcp:aaaaaaaaaaaa")})
    assert payload["code"] == 1003
    assert payload["data"]["reason"] == "evidence_invalid"


async def test_daily_limit_shared_across_granted_projects(
    store: KnowledgeStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("memhub.kb.candidates.DAILY_LIMIT", 1)
    await catalog.create_kb(store, kb_id="other", name="other")
    projects = frozenset({"sample", "other"})
    assert (await invoke(store, GOOD_ARGS, projects=projects))["tier"] == "canonical"
    payload = await invoke(store, {**GOOD_ARGS, "project": "other"}, projects=projects)
    assert payload["code"] == 1010
    assert payload["data"]["reason"] == "daily_limit_exceeded"


async def test_evidence_rejects_absolute_path(store: KnowledgeStore) -> None:
    payload = await invoke(store, {**GOOD_ARGS, "evidence": evidence("/etc/passwd")})
    assert payload["code"] == 1003
    assert payload["data"]["reason"] == "evidence_invalid"


async def test_evidence_rejects_traversal(store: KnowledgeStore) -> None:
    payload = await invoke(store, {**GOOD_ARGS, "evidence": evidence("../other")})
    assert payload["code"] == 1003
    assert payload["data"]["reason"] == "evidence_invalid"


async def test_evidence_rejects_out_of_scope_kb(store: KnowledgeStore) -> None:
    await catalog.create_kb(store, kb_id="other", name="other")
    payload = await invoke(
        store,
        {**GOOD_ARGS, "evidence": evidence("other/fact/something")},
        projects=frozenset({"sample"}),
    )
    assert payload["code"] == 1003
    assert payload["data"]["reason"] == "evidence_out_of_scope"


async def test_evidence_secret_detected(store: KnowledgeStore) -> None:
    payload = await invoke(
        store, {**GOOD_ARGS, "evidence": evidence("session:sk-abcdef0123456789xyz")}
    )
    assert payload["code"] == 1003
    assert payload["data"]["reason"] == "secret_detected"


async def test_content_too_short(store: KnowledgeStore) -> None:
    payload = await invoke(store, {**GOOD_ARGS, "body": "太短"})
    assert payload["code"] == 1003
    assert payload["data"]["reason"] == "content_rejected"


async def test_content_ack_rejected(store: KnowledgeStore) -> None:
    payload = await invoke(
        store,
        {
            **GOOD_ARGS,
            "title": "收到",
            "body": "好的，收到你的消息，我会尽快处理的。谢谢你的反馈。",
        },
    )
    assert payload["code"] == 1003
    assert payload["data"]["reason"] == "content_rejected"


async def test_content_log_dump_rejected(store: KnowledgeStore) -> None:
    log_lines = "\n".join(
        f"2026-11-23T10:00:{i:02d}Z INFO some.module message number {i}" for i in range(15)
    )
    payload = await invoke(store, {**GOOD_ARGS, "body": log_lines})
    assert payload["code"] == 1003
    assert payload["data"]["reason"] == "content_rejected"


async def test_daily_limit(store: KnowledgeStore) -> None:
    # 上限是 50/日；写满 50 条后第 51 条被拒。
    for index in range(50):
        payload = await invoke(
            store,
            {
                **GOOD_ARGS,
                "slug": f"limit-{index:03d}",
                "title": f"每日上限夹具 {index}",
                "body": f"这是第 {index} 条正文，长度足够通过内容门槛的最低要求。",
            },
        )
        assert "code" not in payload, f"index={index} failed: {payload}"
    payload = await invoke(
        store,
        {
            **GOOD_ARGS,
            "slug": "limit-overflow",
            "title": "溢出条目",
            "body": "这是第 51 条正文，长度足够通过内容门槛的最低要求。",
        },
    )
    assert payload["code"] == 1010
    assert payload["data"]["reason"] == "daily_limit_exceeded"


async def test_daily_limit_is_per_grant(
    store: KnowledgeStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("memhub.kb.candidates.DAILY_LIMIT", 2)
    for index in range(2):
        payload = await invoke(
            store,
            {
                **GOOD_ARGS,
                "slug": f"a-{index:03d}",
                "title": f"每日上限夹具 {index}",
                "body": f"这是第 {index} 条正文，长度足够通过内容门槛的最低要求。",
            },
            grant_id="aaaaaaaaaaaa",
        )
        assert "code" not in payload
    payload = await invoke(
        store,
        {**GOOD_ARGS, "slug": "b-000", "title": "另一凭据的首条", "body": GOOD_ARGS["body"]},
        grant_id="bbbbbbbbbbbb",
    )
    assert "code" not in payload


async def test_daily_limit_is_per_utc_day(
    store: KnowledgeStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("memhub.kb.candidates.DAILY_LIMIT", 1)
    # 写满昨天的额度，再回到今天应能继续写。
    fake_today = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)

    class FakeDateTime(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            return fake_today

    monkeypatch.setattr("memhub.kb.candidates.datetime", FakeDateTime)
    assert (await invoke(store, GOOD_ARGS))["tier"] == "canonical"
    next_args = {
        **GOOD_ARGS,
        "slug": "d-new",
        "body": "另一段长度足够且与昨日样本不同的候选知识正文。",
    }
    assert (await invoke(store, next_args))["data"]["reason"] == "daily_limit_exceeded"
    fake_today += timedelta(days=1)
    assert (await invoke(store, next_args))["tier"] == "canonical"


async def test_write_under_write_lock_is_deferred(store: KnowledgeStore) -> None:
    async with manage.write_lock(store.root):
        payload = await invoke(store, GOOD_ARGS)
    assert payload["code"] == 3006


async def test_write_out_of_project_scope(store: KnowledgeStore) -> None:
    payload = await invoke(store, GOOD_ARGS, projects=frozenset({"other"}))
    assert payload["code"] == 1003
    assert payload["data"]["reason"] == "project_unavailable"
