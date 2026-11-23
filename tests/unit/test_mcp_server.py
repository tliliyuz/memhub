"""MCP stdio 传输与工具调度（异步实现）。"""

from __future__ import annotations

import io
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from anyio import Path as AsyncPath

from memhub.contract import Kind, NodeFrontmatter
from memhub.kb.store import KnowledgeStore
from memhub.mcp.server import (
    JSONRPC_INVALID_PARAMS,
    JSONRPC_METHOD_NOT_FOUND,
    JSONRPC_PARSE_ERROR,
    TOOLS,
    handle_message,
    serve,
)

NOW = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)


@pytest.fixture
async def store(tmp_path: Path) -> KnowledgeStore:
    kb = KnowledgeStore(tmp_path)
    # 存储层不再隐式建库：夹具先显式建库目录。
    await AsyncPath(tmp_path / "memhub").mkdir()
    node = NodeFrontmatter(
        id="memhub/fact/proxy",
        kind=Kind.FACT,
        title="HTTPX 代理 502",
        project="memhub",
        created_at=NOW,
        updated_at=NOW,
    )
    await kb.write("memhub/fact/proxy", node, "代理失败时先看 trust_env。")
    return kb


async def _call(
    store: KnowledgeStore, name: str, arguments: dict[str, object]
) -> dict[str, object]:
    response = await handle_message(
        {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
        store,
    )
    assert response is not None
    return response


def _payload(response: dict[str, object]) -> dict[str, object]:
    result = response["result"]
    assert isinstance(result, dict)
    content = result["content"]
    assert isinstance(content, list)
    return json.loads(content[0]["text"])


async def test_initialize_echoes_the_requested_protocol(store: KnowledgeStore) -> None:
    response = await handle_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-03-26"},
        },
        store,
    )
    assert response is not None
    assert response["result"]["protocolVersion"] == "2025-03-26"
    assert response["result"]["capabilities"]["tools"]["listChanged"] is False


async def test_tools_list_exposes_the_retrieval_group(store: KnowledgeStore) -> None:
    response = await handle_message({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, store)
    assert response is not None
    names = [tool["name"] for tool in response["result"]["tools"]]
    # stdio 是本机全库权限，写工具也可见。
    assert names == [
        "kb_search",
        "kb_read",
        "kb_related",
        "kb_audit_list",
        "kb_write_candidate",
        "kb_update_candidate",
        "kb_deprecate",
    ]
    assert [tool["name"] for tool in TOOLS] == names


async def test_kb_search_returns_candidates_when_asked(store: KnowledgeStore) -> None:
    payload = _payload(await _call(store, "kb_search", {"query": "代理", "tier": "all"}))
    assert payload["results"][0]["id"] == "memhub/fact/proxy"


async def test_tool_errors_carry_a_business_code(store: KnowledgeStore) -> None:
    response = await _call(store, "kb_read", {"id": "memhub/fact/missing"})
    assert response["result"]["isError"] is True
    assert _payload(response)["code"] == 3001


async def test_unknown_tool_and_method_are_protocol_errors(store: KnowledgeStore) -> None:
    unknown_tool = await _call(store, "kb_delete", {})
    assert unknown_tool["error"]["code"] == JSONRPC_INVALID_PARAMS

    response = await handle_message({"jsonrpc": "2.0", "id": 3, "method": "nope"}, store)
    assert response is not None
    assert response["error"]["code"] == JSONRPC_METHOD_NOT_FOUND


async def test_serve_writes_one_line_per_request_and_ignores_notifications(
    store: KnowledgeStore,
) -> None:
    incoming = io.StringIO(
        "\n".join(
            [
                json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
                json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
                "{not json",
                "",
            ]
        )
    )
    outgoing = io.StringIO()
    assert await serve(store, incoming, outgoing) == 0
    lines = [json.loads(line) for line in outgoing.getvalue().splitlines()]
    assert len(lines) == 2
    assert lines[0]["id"] == 1
    assert "result" in lines[0]
    assert lines[1]["id"] is None
    assert lines[1]["error"]["code"] == JSONRPC_PARSE_ERROR


async def test_serve_pins_stdio_to_utf8(store: KnowledgeStore) -> None:
    class Recording(io.StringIO):
        def __init__(self) -> None:
            super().__init__()
            self.reconfigured: list[dict[str, object]] = []

        def reconfigure(self, **kwargs: object) -> None:
            self.reconfigured.append(kwargs)

    incoming, outgoing = Recording(), Recording()
    await serve(store, incoming, outgoing)
    for stream in (incoming, outgoing):
        assert stream.reconfigured == [{"encoding": "utf-8", "errors": "replace", "newline": "\n"}]
