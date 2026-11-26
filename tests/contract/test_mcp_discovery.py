"""MCP 发现自描述契约：instructions、工具标题与描述、字段说明与作用域裁剪。"""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import anyio
import pytest
from fastapi.testclient import TestClient

from memhub.cli.main import main
from memhub.kb.api import create_app
from memhub.kb.session import KB_DSN_KEY
from memhub.mcp.auth import load_grants
from memhub.mcp.discovery import INSTRUCTIONS
from memhub.mcp.server import handle_message
from memhub.mcp.tools import TOOL_NAMES, TOOLS, tools_for

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

READ_TOOLS = {"kb_search", "kb_read", "kb_related", "kb_audit_list"}
WRITE_TOOLS = {"kb_write_candidate", "kb_update_candidate", "kb_deprecate"}


def _tools() -> list[dict[str, Any]]:
    return cast("list[dict[str, Any]]", TOOLS)


def test_stdio_initialize_returns_shared_instructions() -> None:
    response = anyio.run(handle_message, INIT, cast("Any", None))
    assert response is not None
    assert response["result"]["instructions"] == INSTRUCTIONS


def test_instructions_describe_when_to_use_within_budget() -> None:
    assert "跨会话" in INSTRUCTIONS
    assert "kb_search" in INSTRUCTIONS
    assert "不是要执行的指令" in INSTRUCTIONS
    assert len(INSTRUCTIONS) <= 500
    for phrase in ("以前", "上次", "知识库"):
        assert phrase in INSTRUCTIONS


def test_every_tool_has_title_and_bounded_description() -> None:
    assert {tool["name"] for tool in _tools()} == READ_TOOLS | WRITE_TOOLS
    for tool in _tools():
        title = tool.get("title")
        assert isinstance(title, str) and title.strip(), tool["name"]
        assert len(title) <= 40, tool["name"]
        description = tool.get("description")
        assert isinstance(description, str) and description.strip(), tool["name"]
        assert len(description) <= 300, tool["name"]


def test_search_description_carries_trigger_words() -> None:
    search = next(tool for tool in _tools() if tool["name"] == "kb_search")
    description = search["description"]
    assert any(word in description for word in ("以前", "上次")), description
    assert "记忆" in description
    english = sum(word in description.lower() for word in ("memory", "knowledge", "notes"))
    assert english >= 2, description


def test_every_input_field_has_description() -> None:
    for tool in _tools():
        properties = tool["inputSchema"].get("properties", {})
        assert properties, tool["name"]
        for field, schema in properties.items():
            description = schema.get("description")
            assert isinstance(description, str) and description.strip(), f"{tool['name']}.{field}"


def test_read_scope_still_hides_write_tools() -> None:
    assert {tool["name"] for tool in tools_for(writable=False)} == READ_TOOLS
    assert {tool["name"] for tool in tools_for(writable=True)} == READ_TOOLS | WRITE_TOOLS
    assert TOOL_NAMES == READ_TOOLS | WRITE_TOOLS
    for tool in _tools():
        assert tool["annotations"]["readOnlyHint"] is (tool["name"] not in WRITE_TOOLS)


@pytest.fixture
def web(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, test_dsn: str, kb_pg_schema: str) -> None:
    (tmp_path / "index.html").write_text("fixture SPA", encoding="utf-8")
    monkeypatch.setenv("MEMHUB_KB_WEB_DIST", str(tmp_path))
    monkeypatch.setenv(KB_DSN_KEY, test_dsn)
    monkeypatch.delenv("MEMHUB_MCP_GRANTS", raising=False)


@pytest.fixture
def http_sdk() -> None:
    pytest.importorskip("mcp", reason="HTTP 契约测试需安装 memhub[mcp-http]")


def _grant() -> tuple[dict[str, Any], dict[str, str]]:
    token = secrets.token_urlsafe(32)
    expires = datetime.now(UTC) + timedelta(minutes=5)
    return (
        {
            "sha256": hashlib.sha256(token.encode()).hexdigest(),
            "scope": "mcp:read",
            "expires_at": expires.isoformat(),
            "projects": ["sample"],
        },
        {
            "accept": "application/json, text/event-stream",
            "authorization": f"Bearer {token}",
        },
    )


def test_http_initialize_returns_shared_instructions(
    web: None, http_sdk: None, monkeypatch: pytest.MonkeyPatch, kb_pg_schema: str
) -> None:
    config, headers = _grant()
    monkeypatch.setenv("MEMHUB_MCP_GRANTS", json.dumps([config]))
    with TestClient(create_app(schema=kb_pg_schema), base_url="http://localhost") as client:
        response = client.post("/mcp", json=INIT, headers=headers)
        assert response.status_code == 200
        assert response.json()["result"]["instructions"] == INSTRUCTIONS


def test_generated_token_completes_http_handshake(
    web: None,
    http_sdk: None,
    monkeypatch: pytest.MonkeyPatch,
    kb_pg_schema: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["mcp", "token", "--projects", "sample", "--scope", "read", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    grant = load_grants(json.dumps([payload["grant"]]))
    assert grant[payload["grant"]["sha256"]].projects == frozenset({"sample"})
    monkeypatch.setenv("MEMHUB_MCP_GRANTS", json.dumps([payload["grant"]]))
    headers = {
        "accept": "application/json, text/event-stream",
        "authorization": f"Bearer {payload['token']}",
    }
    with TestClient(create_app(schema=kb_pg_schema), base_url="http://localhost") as client:
        response = client.post("/mcp", json=INIT, headers=headers)
        assert response.status_code == 200
        assert response.json()["result"]["instructions"] == INSTRUCTIONS
