"""写入审计（规格 §3.6）：MCP 写工具把每次写尝试落 `kb_write_audit`。

审计只记凭据标识、库、节点、动作、结果与时间；不含正文与 token。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import select

from memhub.kb import catalog
from memhub.kb.models import KbWriteAudit
from memhub.kb.pgstore import PgKnowledgeStore
from memhub.kb.session import create_runtime_store
from memhub.mcp.tools import call_tool

GRANT = "grant-audit"
BODY = "写入审计用例的候选正文，重复出现时会被判为同项目正文重复。"


@pytest.fixture
async def pg_store(test_dsn: str, kb_pg_schema: str) -> AsyncIterator[PgKnowledgeStore]:
    store = create_runtime_store(dsn=test_dsn, schema=kb_pg_schema)
    try:
        await catalog.create_kb(store, kb_id="sample", name="sample")
        yield store
    finally:
        await store.aclose()


async def _rows(
    store: PgKnowledgeStore,
) -> list[tuple[str | None, str | None, str | None, str, str]]:
    async with store.sessions() as session:
        records = (await session.scalars(select(KbWriteAudit).order_by(KbWriteAudit.id))).all()
    return [(row.actor, row.project, row.node_id, row.action, row.result) for row in records]


async def _write(store: PgKnowledgeStore, name: str, args: dict) -> dict:  # type: ignore[type-arg]
    result = await call_tool(name, args, store, grant_id=GRANT, writable=True)
    return result


async def test_write_tools_record_one_row_per_attempt(pg_store: PgKnowledgeStore) -> None:
    """创建、更新、废弃各记一行：凭据、库、节点、动作与结果。"""
    created = await _write(
        pg_store,
        "kb_write_candidate",
        {
            "project": "sample",
            "kind": "fact",
            "slug": "audited",
            "title": "写入审计用例",
            "body": BODY,
            "evidence": [{"type": "session", "ref": "session:audit-test"}],
        },
    )
    assert not created["isError"]
    payload = json.loads(created["content"][0]["text"])

    updated = await _write(
        pg_store,
        "kb_update_candidate",
        {
            "id": payload["id"],
            "expected_revision": payload["revision"],
            "title": "写入审计用例（改）",
        },
    )
    assert not updated["isError"]
    revised = json.loads(updated["content"][0]["text"])

    dropped = await _write(
        pg_store,
        "kb_deprecate",
        {
            "id": payload["id"],
            "expected_revision": revised["revision"],
            "reason": "审计用例收尾",
        },
    )
    assert not dropped["isError"]

    rows = await _rows(pg_store)
    node_id = "sample/fact/audited"
    assert rows == [
        (f"mcp:{GRANT}", "sample", node_id, "create", "ok"),
        (f"mcp:{GRANT}", "sample", node_id, "update", "ok"),
        (f"mcp:{GRANT}", "sample", node_id, "deprecate", "ok"),
    ]
    joined = repr(rows)
    assert BODY not in joined
    assert "session:audit-test" not in joined


async def test_rejected_write_keeps_reason_and_does_not_leak_body(
    pg_store: PgKnowledgeStore,
) -> None:
    """被拒的写尝试也留审计，`result` 是拒绝原因码；正文不落库。"""
    first = {
        "project": "sample",
        "kind": "fact",
        "slug": "audited",
        "title": "写入审计用例",
        "body": BODY,
        "evidence": [{"type": "session", "ref": "session:audit-test"}],
    }
    assert not (await _write(pg_store, "kb_write_candidate", first))["isError"]
    duplicate = await _write(pg_store, "kb_write_candidate", {**first, "slug": "audited-again"})
    assert duplicate["isError"]
    assert json.loads(duplicate["content"][0]["text"])["data"]["reason"] == "content_duplicate"

    rows = await _rows(pg_store)
    assert rows[-1] == (
        f"mcp:{GRANT}",
        "sample",
        "sample/fact/audited-again",
        "create",
        "content_duplicate",
    )
    assert BODY not in repr(rows)


async def test_out_of_scope_write_is_audited_as_not_found(pg_store: PgKnowledgeStore) -> None:
    """授权范围外的更新按原语义拒绝，审计记录 `not_found`。"""
    created = await _write(
        pg_store,
        "kb_write_candidate",
        {
            "project": "sample",
            "kind": "fact",
            "slug": "outside",
            "title": "范围外用例",
            "body": BODY + "范围外。",
            "evidence": [{"type": "session", "ref": "session:audit-test"}],
        },
    )
    payload = json.loads(created["content"][0]["text"])
    denied = await call_tool(
        "kb_update_candidate",
        {
            "id": payload["id"],
            "expected_revision": payload["revision"],
            "title": "越权修改",
        },
        pg_store,
        projects=frozenset({"other"}),
        writable=True,
        grant_id=GRANT,
    )
    assert denied["isError"]
    rows = await _rows(pg_store)
    assert rows[-1] == (f"mcp:{GRANT}", "sample", payload["id"], "update", "not_found")
