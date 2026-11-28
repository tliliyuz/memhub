"""MCP 调用轨迹（规格 `docs/plans/mcp-trace-spec.md` §9，ADR-0015）。

服务端把每次 `tools/call` 与鉴权/路由拒绝记入 `kb_mcp_trace`；只记元数据，
不记参数原文、正文或 token。写入按可靠落库处理：重试 → 本地 spool 补投。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, insert, select
from sqlalchemy.engine import Engine

from memhub.contract import Kind, NodeFrontmatter, Tier
from memhub.kb import catalog
from memhub.kb.api import create_app
from memhub.kb.models import KbMcpTrace
from memhub.kb.pgstore import PgKnowledgeStore
from memhub.kb.session import KB_DSN_KEY, create_runtime_store
from memhub.kb.store import KnowledgeStore
from memhub.mcp.trace import TraceEntry, TraceRecorder

ACCEPT = {"accept": "application/json, text/event-stream"}
INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "fixture", "version": "1"},
    },
}
MARKER = "TRACEMARK-9f3a7c"
MODERN = {
    "jsonrpc": "2.0",
    "id": "server-discover-probe-1",
    "method": "server/discover",
    "params": {
        "_meta": {
            "io.modelcontextprotocol/protocolVersion": "2026-07-28",
            "io.modelcontextprotocol/clientInfo": {"name": "fixture", "version": "1"},
            "io.modelcontextprotocol/clientCapabilities": {"roots": {"listChanged": True}},
        }
    },
}

# ---- 夹具与工具 -----------------------------------------------------------


@pytest.fixture
def web(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, test_dsn: str, kb_pg_schema: str) -> Path:
    (tmp_path / "index.html").write_text("fixture SPA", encoding="utf-8")
    monkeypatch.setenv("MEMHUB_KB_WEB_DIST", str(tmp_path))
    monkeypatch.setenv(KB_DSN_KEY, test_dsn)
    monkeypatch.setenv("MEMHUB_KB_GRAPH", str(tmp_path / "kg.json"))
    monkeypatch.setenv("MEMHUB_KB_AUTO_REBUILD", "0")
    spool = tmp_path / "trace-spool.jsonl"
    monkeypatch.setenv("MEMHUB_KB_TRACE_SPOOL", str(spool))
    monkeypatch.delenv("MEMHUB_MCP_GRANTS", raising=False)
    monkeypatch.delenv("MEMHUB_DATA_DIR", raising=False)
    return spool


@pytest.fixture
def http_sdk() -> None:
    pytest.importorskip("mcp", reason="HTTP 契约测试需安装 memhub[mcp-http]")


@pytest.fixture
async def pg_store(test_dsn: str, kb_pg_schema: str) -> AsyncIterator[PgKnowledgeStore]:
    store = create_runtime_store(dsn=test_dsn, schema=kb_pg_schema)
    try:
        yield store
    finally:
        await store.aclose()


def _grant(
    *, name: str | None = None, project: str = "sample"
) -> tuple[dict[str, Any], dict[str, str]]:
    token = secrets.token_urlsafe(32)
    config: dict[str, Any] = {
        "sha256": hashlib.sha256(token.encode()).hexdigest(),
        "scope": "mcp:read",
        "expires_at": (datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
        "projects": [project],
    }
    if name is not None:
        config["name"] = name
    return config, {**ACCEPT, "authorization": f"Bearer {token}"}


def _seed(dsn: str, schema: str) -> None:
    """建库并写一条 canonical 节点，供 kb_search 命中。"""

    async def go() -> None:
        store = create_runtime_store(dsn=dsn, schema=schema)
        try:
            await catalog.create_kb(store, kb_id="sample", name="sample")
            now = datetime.now(UTC)
            await store.write(
                "sample/fact/example",
                NodeFrontmatter(
                    id="sample/fact/example",
                    project="sample",
                    kind=Kind.FACT,
                    tier=Tier.CANONICAL,
                    title="合成样本",
                    created_at=now,
                    updated_at=now,
                ),
                "合成正文",
            )
        finally:
            await store.aclose()

    asyncio.run(go())


def _engine(dsn: str, schema: str) -> Engine:
    url = dsn.replace("postgresql://", "postgresql+psycopg://", 1)
    return create_engine(url, connect_args={"options": f"-csearch_path={schema}"})


def _traces(dsn: str, schema: str) -> list[dict[str, Any]]:
    engine = _engine(dsn, schema)
    try:
        with engine.connect() as conn:
            rows = conn.execute(select(KbMcpTrace).order_by(KbMcpTrace.id)).mappings()
            return [dict(row) for row in rows]
    finally:
        engine.dispose()


def _row(trace_id: str, called_at: datetime, **overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "trace_id": trace_id,
        "request_id": f"req-{trace_id}",
        "rpc_id": "2",
        "called_at": called_at,
        "event": "call",
        "credential_id": "a1b2c3d4e5f6",
        "credential_name": "fixture",
        "tool": "kb_search",
        "status": "ok",
        "http_status": 200,
        "error_code": None,
        "error_kind": None,
        "duration_ms": 5,
        "result_bytes": 10,
        "args_digest": None,
        "projects": ["sample"],
        "client": "fixture/1",
        "tool_count": None,
    }
    values.update(overrides)
    return values


def _call_rows(dsn: str, schema: str) -> list[dict[str, Any]]:
    """只取 `event=call` 的行；发现层事件另有断言。"""
    return [row for row in _traces(dsn, schema) if row["event"] == "call"]


def _entry(
    trace_id: str = "t-1", *, called_at: datetime | None = None, **overrides: Any
) -> TraceEntry:
    return TraceEntry(**_row(trace_id, called_at or datetime.now(UTC), **overrides))


def _open(client: TestClient, headers: dict[str, str]) -> dict[str, str]:
    response = client.post("/mcp", json=INIT, headers=headers)
    assert response.status_code == 200
    ready = {**headers, "mcp-protocol-version": response.json()["result"]["protocolVersion"]}
    assert (
        client.post(
            "/mcp", headers=ready, json={"jsonrpc": "2.0", "method": "notifications/initialized"}
        ).status_code
        == 202
    )
    return ready


def _call(
    client: TestClient,
    headers: dict[str, str],
    name: str,
    arguments: dict[str, Any],
    *,
    rpc_id: int = 2,
) -> Any:
    return client.post(
        "/mcp",
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "id": rpc_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
    )


class _FlakyStore:
    """可注入写入失败的存储替身；只实现轨迹写入。"""

    def __init__(self, failures: int = 0) -> None:
        self.failures = failures
        self.entries: list[TraceEntry] = []

    async def record_mcp_trace(self, entry: TraceEntry) -> None:
        if self.failures:
            self.failures -= 1
            raise RuntimeError("模拟写入失败")
        self.entries.append(entry)


async def _ids(store: PgKnowledgeStore) -> list[str]:
    async with store.sessions() as session:
        scalar = session.scalars(select(KbMcpTrace.trace_id).order_by(KbMcpTrace.id))
        return list((await scalar).all())


# ---- §9.1 记录 ------------------------------------------------------------


def test_ok_call_records_metadata(
    web: Path, http_sdk: None, monkeypatch: pytest.MonkeyPatch, test_dsn: str, kb_pg_schema: str
) -> None:
    """一次连接产生 initialize / tools/list / tools/call 三行；通知不记录（§9.1）。"""
    _seed(test_dsn, kb_pg_schema)
    config, headers = _grant(name="claude-code-laptop")
    monkeypatch.setenv("MEMHUB_MCP_GRANTS", json.dumps([config]))
    with TestClient(create_app(schema=kb_pg_schema), base_url="http://localhost") as client:
        ready = _open(client, headers)
        listed = client.post(
            "/mcp", headers=ready, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
        )
        assert listed.status_code == 200
        pong = client.post(
            "/mcp", headers=ready, json={"jsonrpc": "2.0", "id": 9, "method": "ping"}
        )
        assert pong.status_code == 200
        response = _call(client, ready, "kb_search", {"query": "合成样本"}, rpc_id=3)
        assert response.status_code == 200
        assert not response.json()["result"]["isError"]

    rows = _traces(test_dsn, kb_pg_schema)
    assert [row["event"] for row in rows] == ["initialize", "list_tools", "call"]

    init, listing, call = rows
    assert init["status"] == "ok"
    assert init["rpc_id"] == "1"
    assert init["tool"] is None
    assert init["tool_count"] is None
    assert init["credential_id"] == config["sha256"][:12]
    assert init["credential_name"] == "claude-code-laptop"
    assert init["client"]

    assert listing["status"] == "ok"
    assert listing["rpc_id"] == "2"
    assert listing["tool"] is None
    assert listing["tool_count"] == 4  # mcp:read 的四个读工具
    assert listing["credential_id"] == config["sha256"][:12]

    assert call["status"] == "ok"
    assert call["tool"] == "kb_search"
    assert call["http_status"] == 200
    assert call["rpc_id"] == "3"
    assert call["request_id"]
    assert call["called_at"] is not None
    assert call["duration_ms"] >= 0
    assert call["result_bytes"] and call["result_bytes"] > 0
    assert call["credential_id"] == config["sha256"][:12]
    assert call["credential_name"] == "claude-code-laptop"
    assert call["projects"] == ["sample"]
    assert call["error_code"] is None
    assert call["error_kind"] is None


def test_modern_discover_records_connection_without_initialize(
    web: Path, http_sdk: None, monkeypatch: pytest.MonkeyPatch, test_dsn: str, kb_pg_schema: str
) -> None:
    """现代协议（2026-07-28）以 `server/discover` 建立连接，记 `discover` 且不记 `initialize`（§9.1）。"""
    _seed(test_dsn, kb_pg_schema)
    config, headers = _grant(name="claude-code-laptop")
    monkeypatch.setenv("MEMHUB_MCP_GRANTS", json.dumps([config]))
    modern = {**headers, "mcp-protocol-version": "2026-07-28", "mcp-method": "server/discover"}
    with TestClient(create_app(schema=kb_pg_schema), base_url="http://localhost") as client:
        response = client.post("/mcp", json=MODERN, headers=modern)
        assert response.status_code == 200
        result = response.json()["result"]
        assert result["supportedVersions"] == ["2026-07-28"]
        assert result["instructions"]

    rows = _traces(test_dsn, kb_pg_schema)
    assert [row["event"] for row in rows] == ["discover"]
    discover = rows[0]
    assert discover["status"] == "ok"
    assert discover["rpc_id"] == "server-discover-probe-1"
    assert discover["tool"] is None
    assert discover["tool_count"] is None
    assert discover["credential_id"] == config["sha256"][:12]
    assert discover["credential_name"] == "claude-code-laptop"
    assert discover["client"]


def test_error_call_records_business_code(
    web: Path, http_sdk: None, monkeypatch: pytest.MonkeyPatch, test_dsn: str, kb_pg_schema: str
) -> None:
    """`isError` 的调用记 `status=error`，`error_code` 与返回的 `data.code` 一致。"""
    _seed(test_dsn, kb_pg_schema)
    config, headers = _grant()
    monkeypatch.setenv("MEMHUB_MCP_GRANTS", json.dumps([config]))
    with TestClient(create_app(schema=kb_pg_schema), base_url="http://localhost") as client:
        ready = _open(client, headers)
        response = _call(client, ready, "kb_search", {"project": "private", "query": "x"})
        result = response.json()["result"]
        assert result["isError"]
        assert json.loads(result["content"][0]["text"])["code"] == 3003

    row = _call_rows(test_dsn, kb_pg_schema)[0]
    assert row["status"] == "error"
    assert row["tool"] == "kb_search"
    assert row["error_code"] == 3003
    assert row["http_status"] == 200


def test_credential_name_degrades_to_null_without_grant_name(
    web: Path, http_sdk: None, monkeypatch: pytest.MonkeyPatch, test_dsn: str, kb_pg_schema: str
) -> None:
    """未配置 `name` 时 `credential_name=null`，`credential_id` 仍然记录。"""
    _seed(test_dsn, kb_pg_schema)
    config, headers = _grant()
    monkeypatch.setenv("MEMHUB_MCP_GRANTS", json.dumps([config]))
    with TestClient(create_app(schema=kb_pg_schema), base_url="http://localhost") as client:
        ready = _open(client, headers)
        assert _call(client, ready, "kb_search", {"query": "合成样本"}).status_code == 200

    row = _call_rows(test_dsn, kb_pg_schema)[0]
    assert row["credential_id"] == config["sha256"][:12]
    assert row["credential_name"] is None


def test_rejections_are_recorded(
    web: Path, http_sdk: None, monkeypatch: pytest.MonkeyPatch, test_dsn: str, kb_pg_schema: str
) -> None:
    """401 / 403 / 405 各记一行 `rejected`，工具为空。"""
    config, headers = _grant()
    monkeypatch.setenv("MEMHUB_MCP_GRANTS", json.dumps([config]))
    with TestClient(create_app(schema=kb_pg_schema), base_url="http://localhost") as client:
        assert client.post("/mcp", json=INIT, headers=ACCEPT).status_code == 401
        ready = _open(client, headers)
        assert (
            client.post(
                "/mcp", json=INIT, headers={**ready, "origin": "https://example.test"}
            ).status_code
            == 403
        )
        assert client.get("/mcp", headers=ready).status_code == 405

    rows = [row for row in _traces(test_dsn, kb_pg_schema) if row["status"] == "rejected"]
    assert [(row["status"], row["error_kind"], row["http_status"]) for row in rows] == [
        ("rejected", "unauthorized", 401),
        ("rejected", "forbidden", 403),
        ("rejected", "method_not_allowed", 405),
    ]
    assert rows[0]["credential_id"] is None
    assert rows[1]["credential_id"] == config["sha256"][:12]
    assert all(row["tool"] is None for row in rows)
    assert all(row["event"] == "call" for row in rows)


def test_arguments_are_not_persisted(
    web: Path, http_sdk: None, monkeypatch: pytest.MonkeyPatch, test_dsn: str, kb_pg_schema: str
) -> None:
    """参数原文不落任何列，只留规范化 JSON 的 sha256。"""
    _seed(test_dsn, kb_pg_schema)
    config, headers = _grant()
    monkeypatch.setenv("MEMHUB_MCP_GRANTS", json.dumps([config]))
    with TestClient(create_app(schema=kb_pg_schema), base_url="http://localhost") as client:
        ready = _open(client, headers)
        assert _call(client, ready, "kb_search", {"query": MARKER}).status_code == 200

    rows = _traces(test_dsn, kb_pg_schema)
    assert MARKER not in repr(rows)
    canonical = json.dumps(
        {"query": MARKER}, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    assert (
        _call_rows(test_dsn, kb_pg_schema)[0]["args_digest"]
        == hashlib.sha256(canonical.encode()).hexdigest()
    )


# ---- §9.2 可靠落库 --------------------------------------------------------


async def test_failed_write_spools_then_replays(tmp_path: Path) -> None:
    """写入连败 4 次（初次 + 3 重试）进 spool；下一次成功记录时补投并清空 spool。"""
    store = _FlakyStore(failures=4)
    spool = tmp_path / "spool.jsonl"
    recorder = TraceRecorder(store, spool_path=spool)

    await recorder.record(_entry("t-1"))
    assert store.entries == []
    lines = [json.loads(line) for line in spool.read_text(encoding="utf-8").splitlines()]
    assert [line["trace_id"] for line in lines] == ["t-1"]
    assert lines[0]["called_at"]

    store.failures = 0
    await recorder.record(_entry("t-2"))
    assert {entry.trace_id for entry in store.entries} == {"t-1", "t-2"}
    assert spool.read_text(encoding="utf-8") == ""


async def test_spool_keeps_newest_lines_within_the_size_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """spool 超过上限时保留最新行、丢弃最旧行，总大小回到上限以内（规格 §4.2）。"""
    from memhub.mcp import trace as trace_module

    monkeypatch.setattr(trace_module, "_RETRY_DELAYS", ())
    monkeypatch.setattr(trace_module, "_SPOOL_MAX_BYTES", 700)
    store = _FlakyStore(failures=10**6)
    spool = tmp_path / "spool.jsonl"
    recorder = TraceRecorder(store, spool_path=spool)
    for index in range(10):
        await recorder.record(_entry(f"old-{index}"))

    lines = spool.read_text(encoding="utf-8").splitlines()
    assert 0 < len(lines) < 10
    assert json.loads(lines[-1])["trace_id"] == "old-9"
    assert sum(len(line.encode("utf-8")) + 1 for line in lines) <= 700


async def test_duplicate_trace_id_inserts_once(pg_store: PgKnowledgeStore) -> None:
    """同一 `trace_id` 重放只留一行（幂等）。"""
    entry = _entry("dup")
    await pg_store.record_mcp_trace(entry)
    await pg_store.record_mcp_trace(entry)
    assert await _ids(pg_store) == ["dup"]


def test_trace_write_failure_does_not_change_response(
    web: Path, http_sdk: None, monkeypatch: pytest.MonkeyPatch, test_dsn: str, kb_pg_schema: str
) -> None:
    """轨迹写入彻底失败时，tools/call 的响应与状态码不变。"""
    _seed(test_dsn, kb_pg_schema)
    config, headers = _grant()
    monkeypatch.setenv("MEMHUB_MCP_GRANTS", json.dumps([config]))

    async def boom(self: PgKnowledgeStore, entry: TraceEntry) -> None:
        raise RuntimeError("模拟落库失败")

    monkeypatch.setattr(PgKnowledgeStore, "record_mcp_trace", boom)
    with TestClient(create_app(schema=kb_pg_schema), base_url="http://localhost") as client:
        ready = _open(client, headers)
        response = _call(client, ready, "kb_search", {"query": "合成样本"})
        assert response.status_code == 200
        assert not response.json()["result"]["isError"]
    assert _traces(test_dsn, kb_pg_schema) == []


# ---- §9.3 保留期 ----------------------------------------------------------


async def test_cleanup_removes_rows_older_than_30_days(pg_store: PgKnowledgeStore) -> None:
    """超过 30 天的明细在写入路径上被清理，新行保留。"""
    now = datetime.now(UTC)
    await pg_store.record_mcp_trace(_entry("old", called_at=now - timedelta(days=31)))
    recorder = TraceRecorder(pg_store, spool_path=None)
    await recorder.record(_entry("fresh", called_at=now))
    assert await _ids(pg_store) == ["fresh"]


async def test_cleanup_is_throttled_within_the_hour(pg_store: PgKnowledgeStore) -> None:
    """一小时内只清理一次：第二次写入不重复删除。"""
    now = datetime.now(UTC)
    recorder = TraceRecorder(pg_store, spool_path=None)
    await recorder.record(_entry("first", called_at=now))
    await pg_store.record_mcp_trace(_entry("old", called_at=now - timedelta(days=31)))
    await recorder.record(_entry("second", called_at=now))
    assert await _ids(pg_store) == ["first", "old", "second"]


# ---- §9.4 API -------------------------------------------------------------


def _insert(dsn: str, schema: str, *rows: dict[str, Any]) -> None:
    engine = _engine(dsn, schema)
    try:
        with engine.begin() as conn:
            conn.execute(insert(KbMcpTrace), list(rows))
    finally:
        engine.dispose()


def test_list_endpoint_filters_and_orders(web: Path, test_dsn: str, kb_pg_schema: str) -> None:
    """列表返回 `{items,total,offset,limit}`，时间倒序，过滤条件生效。"""
    base = datetime.now(UTC) - timedelta(hours=2)
    _insert(
        test_dsn,
        kb_pg_schema,
        _row("t1", base, tool="kb_search", status="ok"),
        _row("t2", base + timedelta(minutes=1), tool="kb_read", status="error", error_code=3001),
        _row(
            "t3",
            base + timedelta(minutes=2),
            tool="kb_search",
            status="ok",
            credential_id="bbbbbbbbbbbb",
            credential_name=None,
        ),
        _row(
            "d0",
            base + timedelta(minutes=2, seconds=30),
            event="discover",
            tool=None,
            rpc_id="server-discover-probe-1",
            result_bytes=None,
        ),
        _row(
            "d1",
            base + timedelta(minutes=3),
            event="initialize",
            tool=None,
            rpc_id="1",
            result_bytes=None,
        ),
        _row(
            "d2",
            base + timedelta(minutes=4),
            event="list_tools",
            tool=None,
            rpc_id="2",
            result_bytes=None,
            tool_count=7,
        ),
    )
    with TestClient(create_app(schema=kb_pg_schema), base_url="http://localhost") as client:
        body = client.get("/api/v1/kb/mcp-traces").json()
        assert set(body) == {"items", "total", "offset", "limit"}
        assert [item["trace_id"] for item in body["items"]] == ["t3", "t2", "t1"]
        assert (body["total"], body["offset"], body["limit"]) == (3, 0, 50)
        assert body["items"][0]["credential"] == {"id": "bbbbbbbbbbbb", "name": None}
        assert body["items"][1]["error_code"] == 3001
        assert body["items"][0]["event"] == "call"

        listings = client.get("/api/v1/kb/mcp-traces", params={"event": "list_tools"}).json()
        assert [item["trace_id"] for item in listings["items"]] == ["d2"]
        assert listings["items"][0]["tool_count"] == 7
        assert listings["items"][0]["tool"] is None

        inits = client.get("/api/v1/kb/mcp-traces", params={"event": "initialize"}).json()
        assert [item["trace_id"] for item in inits["items"]] == ["d1"]

        discovers = client.get("/api/v1/kb/mcp-traces", params={"event": "discover"}).json()
        assert [item["trace_id"] for item in discovers["items"]] == ["d0"]
        assert discovers["items"][0]["tool"] is None
        assert discovers["items"][0]["tool_count"] is None

        by_tool = client.get("/api/v1/kb/mcp-traces", params={"tool": "kb_search"}).json()
        assert [item["trace_id"] for item in by_tool["items"]] == ["t3", "t1"]
        assert by_tool["total"] == 2

        by_status = client.get("/api/v1/kb/mcp-traces", params={"status": "error"}).json()
        assert [item["trace_id"] for item in by_status["items"]] == ["t2"]

        by_credential = client.get("/api/v1/kb/mcp-traces", params={"credential": "fixture"}).json()
        assert [item["trace_id"] for item in by_credential["items"]] == ["t2", "t1"]

        windowed = client.get(
            "/api/v1/kb/mcp-traces", params={"since": (base + timedelta(seconds=30)).isoformat()}
        ).json()
        assert [item["trace_id"] for item in windowed["items"]] == ["t3", "t2"]


def test_summary_endpoint_aggregates(web: Path, test_dsn: str, kb_pg_schema: str) -> None:
    """汇总按 `days` 聚合，`total = ok + error + rejected`。"""
    now = datetime.now(UTC)
    _insert(
        test_dsn,
        kb_pg_schema,
        _row("s1", now - timedelta(days=1), tool="kb_search", status="ok", duration_ms=10),
        _row("s2", now - timedelta(days=2), tool="kb_search", status="error", duration_ms=30),
        _row(
            "s3",
            now - timedelta(days=3),
            tool="kb_read",
            status="rejected",
            http_status=401,
            error_kind="unauthorized",
        ),
        _row("s4", now - timedelta(days=20), tool="kb_search", status="ok"),
    )
    with TestClient(create_app(schema=kb_pg_schema), base_url="http://localhost") as client:
        body = client.get("/api/v1/kb/mcp-traces/summary", params={"days": 7}).json()
    assert body["days"] == 7
    assert body["total"] == body["ok"] + body["error"] + body["rejected"] == 3
    tools = {item["tool"]: item for item in body["tools"]}
    assert tools["kb_search"]["count"] == 2
    assert tools["kb_search"]["ok"] == 1
    assert tools["kb_search"]["error"] == 1
    assert tools["kb_search"]["avg_ms"] == 20
    assert tools["kb_read"]["rejected"] == 1
    assert body["credentials"] == [{"id": "a1b2c3d4e5f6", "name": "fixture", "count": 3}]
    assert body["funnel"] == {
        "connections": 0,
        "listings": 0,
        "calls": 2,
        "listings_per_connection": 0.0,
        "calls_per_listing": 0.0,
        "avg_tools": 0,
    }


def test_summary_funnel_counts_discovery_events(
    web: Path, test_dsn: str, kb_pg_schema: str
) -> None:
    """漏斗只数成功连接/列工具与 ok+error 调用；拒绝不算实际调用（§6.2）。"""
    now = datetime.now(UTC) - timedelta(minutes=5)
    _insert(
        test_dsn,
        kb_pg_schema,
        _row("i1", now, event="initialize", tool=None, result_bytes=None, rpc_id="1"),
        _row(
            "i2",
            now + timedelta(seconds=1),
            event="initialize",
            tool=None,
            result_bytes=None,
            rpc_id="1",
        ),
        _row(
            "i3",
            now + timedelta(seconds=2),
            event="initialize",
            tool=None,
            result_bytes=None,
            rpc_id="1",
            status="error",
            error_kind="internal",
        ),
        _row(
            "m1",
            now + timedelta(seconds=2, milliseconds=500),
            event="discover",
            tool=None,
            rpc_id="server-discover-probe-1",
            result_bytes=None,
        ),
        _row(
            "m2",
            now + timedelta(seconds=2, milliseconds=600),
            event="discover",
            tool=None,
            rpc_id="server-discover-probe-1",
            result_bytes=None,
            status="error",
            http_status=500,
            error_kind="internal",
        ),
        _row(
            "l1",
            now + timedelta(seconds=3),
            event="list_tools",
            tool=None,
            result_bytes=None,
            tool_count=4,
        ),
        _row(
            "l2",
            now + timedelta(seconds=4),
            event="list_tools",
            tool=None,
            result_bytes=None,
            tool_count=6,
        ),
        _row("c1", now + timedelta(seconds=5), tool="kb_search", status="ok"),
        _row("c2", now + timedelta(seconds=6), tool="kb_search", status="ok"),
        _row("c3", now + timedelta(seconds=7), tool="kb_read", status="error", error_code=3001),
        _row(
            "c4",
            now + timedelta(seconds=8),
            tool=None,
            status="rejected",
            http_status=401,
            error_kind="unauthorized",
            event="call",
        ),
    )
    with TestClient(create_app(schema=kb_pg_schema), base_url="http://localhost") as client:
        body = client.get("/api/v1/kb/mcp-traces/summary", params={"days": 1}).json()
    assert body["total"] == body["ok"] + body["error"] + body["rejected"] == 4
    assert body["funnel"] == {
        "connections": 3,
        "listings": 2,
        "calls": 3,
        "listings_per_connection": 0.67,
        "calls_per_listing": 1.5,
        "avg_tools": 5,
    }


def test_non_pg_store_returns_503(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, kb_pg_schema: str
) -> None:
    """非 PG 存储（仅测试夹具可能出现）返回 503/`2001`。"""
    monkeypatch.setenv("MEMHUB_KB_GRAPH", str(tmp_path / "kg.json"))
    monkeypatch.setenv("MEMHUB_KB_AUTO_REBUILD", "0")
    monkeypatch.delenv("MEMHUB_MCP_GRANTS", raising=False)
    with TestClient(
        create_app(store=KnowledgeStore(tmp_path / "kb")), base_url="http://localhost"
    ) as client:
        response = client.get("/api/v1/kb/mcp-traces")
        assert response.status_code == 503
        assert response.json()["code"] == 2001
        summary = client.get("/api/v1/kb/mcp-traces/summary")
        assert summary.status_code == 503
        assert summary.json()["code"] == 2001
