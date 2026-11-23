"""首版 HTTP 入口独立鉴权，不进入管理台静态路由。"""

import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import anyio
import pytest
from fastapi.testclient import TestClient

from memhub.contract import Kind, NodeFrontmatter, Tier
from memhub.kb import catalog
from memhub.kb.api import create_app
from memhub.kb.store import KnowledgeStore

HEADERS = {"accept": "application/json, text/event-stream"}
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


@pytest.fixture
def web(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("fixture SPA", encoding="utf-8")
    monkeypatch.setenv("MEMHUB_KB_WEB_DIST", str(tmp_path))
    monkeypatch.setenv("MEMHUB_KNOWLEDGE_DIR", str(tmp_path))
    monkeypatch.delenv("MEMHUB_MCP_GRANTS", raising=False)


@pytest.fixture
def http_sdk() -> None:
    pytest.importorskip("mcp", reason="HTTP 契约测试需安装 memhub[mcp-http]")


def grant(
    project: str = "sample", *, expired: bool = False, scope: str = "mcp:read"
) -> tuple[dict, dict[str, str]]:
    token = secrets.token_urlsafe(32)
    expires = datetime.now(UTC) + timedelta(minutes=-5 if expired else 5)
    return (
        {
            "sha256": hashlib.sha256(token.encode()).hexdigest(),
            "scope": scope,
            "expires_at": expires.isoformat(),
            "projects": [project],
        },
        {**HEADERS, "authorization": f"Bearer {token}"},
    )


def configure(monkeypatch: pytest.MonkeyPatch, *, expired: bool = False) -> dict[str, str]:
    config, headers = grant(expired=expired)
    monkeypatch.setenv("MEMHUB_MCP_GRANTS", json.dumps([config]))
    return headers


def test_disabled_mcp_does_not_fall_through_to_spa(web: None) -> None:
    with TestClient(create_app(), base_url="http://localhost") as client:
        assert client.get("/").text == "fixture SPA"
        for path in ("/mcp", "/mcp/", "/mcp/other"):
            assert client.get(path).status_code == 404
            assert client.post(path, json=INIT).status_code == 404


def test_http_handshake_and_scope(
    web: None, http_sdk: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers = configure(monkeypatch)
    with TestClient(create_app(), base_url="http://localhost") as client:
        assert client.post("/mcp", json=INIT, headers=HEADERS).status_code == 401
        assert (
            client.post("/mcp", json=INIT, headers={**HEADERS, "cookie": "fixture=x"}).status_code
            == 401
        )
        assert (
            client.post(
                "/mcp", json=INIT, headers={**headers, "origin": "https://example.test"}
            ).status_code
            == 403
        )
        assert client.post("/mcp", content=b"x" * 16385, headers=headers).status_code == 413
        response = client.post("/mcp", json=INIT, headers=headers)
        assert response.status_code == 200
        assert "mcp-session-id" not in response.headers
        protocol = response.json()["result"]["protocolVersion"]
        headers["mcp-protocol-version"] = protocol
        response = client.post(
            "/mcp",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
            },
        )
        assert response.status_code == 202
        response = client.post(
            "/mcp",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/list",
            },
        )
        assert {tool["name"] for tool in response.json()["result"]["tools"]} == {
            "kb_search",
            "kb_read",
            "kb_related",
            "kb_audit_list",
        }
        response = client.post(
            "/mcp",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "kb_search",
                    "arguments": {"project": "private", "query": "fixture"},
                },
            },
        )
        result = response.json()["result"]
        assert result["isError"]
        assert json.loads(result["content"][0]["text"])["code"] == 3003
        assert client.get("/mcp", headers=headers).status_code == 405
        assert client.get("/mcp/", headers=headers).status_code == 404


def test_expired_and_revoked_credentials(
    web: None, http_sdk: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    expired, expired_headers = grant(expired=True)
    revoked, revoked_headers = grant()
    valid, valid_headers = grant()
    monkeypatch.setenv("MEMHUB_MCP_GRANTS", json.dumps([expired, revoked, valid]))
    with TestClient(create_app(), base_url="http://localhost") as client:
        assert client.post("/mcp", json=INIT, headers=expired_headers).status_code == 401
        assert client.post("/mcp", json=INIT, headers=revoked_headers).status_code == 200
    monkeypatch.setenv("MEMHUB_MCP_GRANTS", json.dumps([valid]))
    with TestClient(create_app(), base_url="http://localhost") as client:
        assert client.post("/mcp", json=INIT, headers=revoked_headers).status_code == 401
        assert client.post("/mcp", json=INIT, headers=valid_headers).status_code == 200


def test_malformed_credentials(web: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEMHUB_MCP_GRANTS", "{}")
    with pytest.raises(ValueError, match="MEMHUB_MCP_GRANTS"):
        create_app()


async def test_sdk_round_trip_separates_grant_scopes(
    web: None, http_sdk: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from httpx2 import ASGITransport, AsyncClient
    from mcp import Client
    from mcp.client.streamable_http import streamable_http_client

    sample, sample_headers = grant()
    private, private_headers = grant("private")
    monkeypatch.setenv("MEMHUB_MCP_GRANTS", json.dumps([sample, private]))
    store = KnowledgeStore(tmp_path)
    now = datetime.now(UTC)
    for project in ("sample", "private"):
        await catalog.create_kb(store, kb_id=project, name=project)
        node_id = f"{project}/fact/example"
        await store.write(
            node_id,
            NodeFrontmatter(
                id=node_id,
                project=project,
                kind=Kind.FACT,
                tier=Tier.CANONICAL,
                title="合成样本",
                created_at=now,
                updated_at=now,
            ),
            "合成正文",
        )

    app = create_app()
    async with app.router.lifespan_context(app):
        # 交错使用不同凭据，确认请求级范围不串库；通过 SDK 进行协议协商和工具发现。
        for allowed, forbidden, headers in (
            ("sample", "private", sample_headers),
            ("private", "sample", private_headers),
            ("sample", "private", sample_headers),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), headers=headers) as http:
                transport = streamable_http_client("http://localhost/mcp", http_client=http)
                with anyio.fail_after(10):
                    async with Client(transport) as client:
                        assert {tool.name for tool in (await client.list_tools()).tools} == {
                            "kb_search",
                            "kb_read",
                            "kb_related",
                            "kb_audit_list",
                        }
                        node_id = f"{allowed}/fact/example"
                        found = await client.call_tool("kb_search", {"query": "合成样本"})
                        assert not found.is_error
                        results = json.loads(found.content[0].text)["results"]
                        assert [item["id"] for item in results] == [node_id]
                        read = await client.call_tool("kb_read", {"id": node_id})
                        assert not read.is_error
                        assert json.loads(read.content[0].text)["body"] == "合成正文"
                        denied = await client.call_tool(
                            "kb_read", {"id": f"{forbidden}/fact/example"}
                        )
                        assert denied.is_error
                        assert json.loads(denied.content[0].text)["code"] == 3001
                        invalid = await client.call_tool(
                            "kb_search", {"query": "sample", "limit": "2"}
                        )
                        assert invalid.is_error
                        assert json.loads(invalid.content[0].text)["code"] == 3004


async def test_sdk_write_scope_exposes_and_executes_candidate_tool(
    web: None, http_sdk: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from httpx2 import ASGITransport, AsyncClient
    from mcp import Client
    from mcp.client.streamable_http import streamable_http_client

    config, headers = grant(scope="mcp:write")
    monkeypatch.setenv("MEMHUB_MCP_GRANTS", json.dumps([config]))
    store = KnowledgeStore(tmp_path)
    await catalog.create_kb(store, kb_id="sample", name="sample")
    app = create_app()
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), headers=headers) as http,
    ):
        transport = streamable_http_client("http://localhost/mcp", http_client=http)
        with anyio.fail_after(10):
            async with Client(transport) as client:
                assert {tool.name for tool in (await client.list_tools()).tools} == {
                    "kb_search",
                    "kb_read",
                    "kb_related",
                    "kb_audit_list",
                    "kb_write_candidate",
                    "kb_update_candidate",
                    "kb_deprecate",
                }
                result = await client.call_tool(
                    "kb_write_candidate",
                    {
                        "project": "sample",
                        "kind": "fact",
                        "slug": "http-write",
                        "title": "HTTP 写候选",
                        "body": "这是通过 HTTP MCP 写入的可复用候选知识正文。",
                        "evidence": [{"type": "session", "ref": "session:http-test"}],
                    },
                )
                assert not result.is_error
                payload = json.loads(result.content[0].text)
                assert payload["id"] == "sample/fact/http-write"
                assert payload["tier"] == "candidate"

                read = await client.call_tool("kb_read", {"id": payload["id"]})
                assert not read.is_error
                assert json.loads(read.content[0].text)["revision"] == payload["revision"]

                updated = await client.call_tool(
                    "kb_update_candidate",
                    {
                        "id": payload["id"],
                        "expected_revision": payload["revision"],
                        "title": "HTTP 改过的候选",
                    },
                )
                assert not updated.is_error
                revised = json.loads(updated.content[0].text)
                assert revised["revision"] != payload["revision"]

                dropped = await client.call_tool(
                    "kb_deprecate",
                    {
                        "id": payload["id"],
                        "expected_revision": revised["revision"],
                        "reason": "HTTP 联调结束后废弃",
                    },
                )
                assert not dropped.is_error
                assert json.loads(dropped.content[0].text)["tier"] == "deprecated"
    node, _ = await store.read(payload["id"])
    assert node.source[-1].ref == f"mcp:{config['sha256'][:12]}"
    assert node.tier is Tier.DEPRECATED
    assert node.deprecated_reason == "HTTP 联调结束后废弃"


async def test_http_rejects_overlapping_posts(
    web: None, http_sdk: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    # httpx 的 ASGI 传输会先读完请求体再进应用，无法模拟「上一请求仍持有入口」；
    # 这里直接驱动 ASGI，用阻塞的 receive 让第一个 POST 停在应用内部。
    body = json.dumps(INIT).encode()
    token = configure(monkeypatch)["authorization"].removeprefix("Bearer ")
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/mcp",
        "raw_path": b"/mcp",
        "query_string": b"",
        "root_path": "",
        "server": ("localhost", 80),
        "client": ("127.0.0.1", 1),
        "state": {},
        "headers": [
            (b"host", b"localhost"),
            (b"accept", b"application/json, text/event-stream"),
            (b"content-type", b"application/json"),
            (b"authorization", f"Bearer {token}".encode()),
        ],
    }

    async def call(app: Any, receive: Any) -> tuple[int, dict[str, str]]:
        started: dict[str, Any] = {}

        async def send(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                started["status"] = message["status"]
                started["headers"] = {
                    key.decode().lower(): value.decode() for key, value in message["headers"]
                }

        await app(scope, receive, send)
        return started["status"], started.get("headers", {})

    async def complete() -> dict[str, Any]:
        return {"type": "http.request", "body": body, "more_body": False}

    app = create_app()
    entered, release = anyio.Event(), anyio.Event()

    async def slow() -> dict[str, Any]:
        entered.set()
        await release.wait()
        return await complete()

    results: dict[str, tuple[int, dict[str, str]]] = {}

    async def first() -> None:
        results["first"] = await call(app, slow)

    async with app.router.lifespan_context(app):
        with anyio.fail_after(10):
            async with anyio.create_task_group() as tasks:
                tasks.start_soon(first)
                await entered.wait()
                status, headers = await call(app, complete)
                assert status == 429
                assert headers["retry-after"] == "1"
                release.set()
        assert results["first"][0] == 200
        assert (await call(app, complete))[0] == 200
