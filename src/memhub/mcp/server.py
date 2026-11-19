"""MCP 服务：把检索组暴露给 agent（`docs/contracts/mcp-tools.md`）。

传输是 MCP stdio——每行一个 JSON-RPC 2.0 消息；工具定义只在这里，检索算法在
`memhub.kb.query`。以后接 Streamable HTTP（`/mcp`）时复用 `handle_message`，
只换传输层。

启动：`memhub mcp --knowledge-dir ./knowledge`
"""

from __future__ import annotations

import json
import sys
from typing import Any, TextIO

import anyio

from memhub import __version__
from memhub.contract import Kind, Predicate
from memhub.kb import query
from memhub.kb.store import KnowledgeStore

SERVER_NAME = "memhub"
DEFAULT_PROTOCOL = "2025-06-18"

JSONRPC_PARSE_ERROR = -32700
JSONRPC_INVALID_REQUEST = -32600
JSONRPC_METHOD_NOT_FOUND = -32601
JSONRPC_INVALID_PARAMS = -32602

TOOLS: list[dict[str, Any]] = [
    {
        "name": "kb_search",
        "description": (
            "在本机 memhub 知识库里检索。默认只返回 canonical 节点；"
            '传 tier="all" 才看 candidate。无结果时返回空列表和 hint，不报错。'
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["query"],
            "properties": {
                "query": {"type": "string", "description": "概念、报错、命令或项目名"},
                "project": {"type": "string", "description": "限定项目（knowledge 下的一级目录）"},
                "kinds": {
                    "type": "array",
                    "items": {"type": "string", "enum": [kind.value for kind in Kind]},
                    "description": "限定节点类型",
                },
                "tier": {
                    "type": "string",
                    "enum": ["canonical", "candidate", "all"],
                    "default": "canonical",
                },
                "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 8},
            },
        },
    },
    {
        "name": "kb_read",
        "description": "按 id 读取一条知识的真源全文、frontmatter、出入边与来源。",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["id"],
            "properties": {"id": {"type": "string", "description": "节点 id，如 memhub/fact/foo"}},
        },
    },
    {
        "name": "kb_related",
        "description": "读邻接子图，用于按关系扩展上下文；depth 上限 2。",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["id"],
            "properties": {
                "id": {"type": "string"},
                "depth": {"type": "integer", "minimum": 1, "maximum": 2, "default": 1},
                "predicates": {
                    "type": "array",
                    "items": {"type": "string", "enum": [item.value for item in Predicate]},
                },
                "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 30},
            },
        },
    },
    {
        "name": "kb_audit_list",
        "description": (
            "只读列出治理问题：contradiction / broken_link / orphan / low_confidence / stale。"
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 50},
                "offset": {"type": "integer", "minimum": 0, "default": 0},
            },
        },
    },
]

TOOL_NAMES = {tool["name"] for tool in TOOLS}


def _content(payload: dict[str, Any], *, is_error: bool = False) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, indent=2)}],
        "isError": is_error,
    }


async def call_tool(name: str, arguments: dict[str, Any], store: KnowledgeStore) -> dict[str, Any]:
    try:
        match name:
            case "kb_search":
                return _content(
                    await query.search(
                        store,
                        str(arguments.get("query", "")),
                        project=arguments.get("project"),
                        kinds=arguments.get("kinds"),
                        tier=str(arguments.get("tier", "canonical")),
                        limit=int(arguments.get("limit", 8)),
                    )
                )
            case "kb_read":
                return _content(await query.read_node(store, str(arguments.get("id", ""))))
            case "kb_related":
                return _content(
                    await query.related(
                        store,
                        str(arguments.get("id", "")),
                        depth=int(arguments.get("depth", 1)),
                        predicates=arguments.get("predicates"),
                        limit=int(arguments.get("limit", 30)),
                    )
                )
            case "kb_audit_list":
                return _content(
                    await query.audit_list(
                        store,
                        limit=int(arguments.get("limit", 50)),
                        offset=int(arguments.get("offset", 0)),
                    )
                )
            case _:
                return _content(
                    {"code": JSONRPC_INVALID_PARAMS, "message": f"unknown tool: {name}"},
                    is_error=True,
                )
    except query.QueryError as exc:
        return _content({"code": exc.code, "message": str(exc)}, is_error=True)
    except (TypeError, ValueError) as exc:
        return _content({"code": query.QueryError.code, "message": str(exc)}, is_error=True)


def _ok(message_id: object, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "result": result}


def _error(message_id: object, code: int, text: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "error": {"code": code, "message": text}}


async def handle_message(message: dict[str, Any], store: KnowledgeStore) -> dict[str, Any] | None:
    """一条 JSON-RPC 消息 → 响应；通知返回 None。"""
    message_id = message.get("id")
    method = message.get("method")
    if not isinstance(method, str):
        return _error(message_id, JSONRPC_INVALID_REQUEST, "missing method")

    if method == "initialize":
        requested = message.get("params", {}).get("protocolVersion")
        return _ok(
            message_id,
            {
                "protocolVersion": requested or DEFAULT_PROTOCOL,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": __version__},
                "instructions": (
                    "memhub 知识库检索。先用 kb_search 找 id，再 kb_read 看全文，"
                    '需要上下文时 kb_related。默认只看 canonical，候选知识传 tier="all"。'
                ),
            },
        )
    if method in {"notifications/initialized", "notifications/cancelled"}:
        return None
    if method == "ping":
        return _ok(message_id, {})
    if method == "tools/list":
        return _ok(message_id, {"tools": TOOLS})
    if method == "tools/call":
        params = message.get("params") or {}
        name = params.get("name")
        if not isinstance(name, str):
            return _error(message_id, JSONRPC_INVALID_PARAMS, "tools/call needs a tool name")
        if name not in TOOL_NAMES:
            return _error(
                message_id,
                JSONRPC_INVALID_PARAMS,
                f"unknown tool {name!r}; available: {sorted(TOOL_NAMES)}",
            )
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            return _error(message_id, JSONRPC_INVALID_PARAMS, "arguments must be an object")
        return _ok(message_id, await call_tool(name, arguments, store))
    return _error(message_id, JSONRPC_METHOD_NOT_FOUND, f"unknown method: {method}")


async def _write(stdout: TextIO, payload: dict[str, Any]) -> None:
    text = json.dumps(payload, ensure_ascii=False) + "\n"
    await anyio.to_thread.run_sync(stdout.write, text)
    await anyio.to_thread.run_sync(stdout.flush)


def _use_utf8(stream: TextIO) -> None:
    """协议固定 UTF-8；Windows 上管道默认编码常是 cp936，中文会乱码或直接报错。"""
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is None:
        return
    try:
        reconfigure(encoding="utf-8", errors="replace", newline="\n")
    except (ValueError, OSError):
        pass


async def serve(
    store: KnowledgeStore,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
) -> int:
    """跑 stdio 传输，直到 stdin 关闭。普通日志一律走 stderr，stdout 只放协议。

    stdin 是阻塞读，放到线程里执行；协议处理本身是 async。
    """
    source = stdin or sys.stdin
    sink = stdout or sys.stdout
    _use_utf8(source)
    _use_utf8(sink)
    while True:
        raw = await anyio.to_thread.run_sync(source.readline)
        if not raw:
            break
        line = raw.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError as exc:
            await _write(sink, _error(None, JSONRPC_PARSE_ERROR, f"invalid JSON: {exc.msg}"))
            continue
        if not isinstance(message, dict):
            await _write(sink, _error(None, JSONRPC_INVALID_REQUEST, "expected a JSON object"))
            continue
        response = await handle_message(message, store)
        if response is not None:
            await _write(sink, response)
    return 0


__all__ = ["TOOLS", "call_tool", "handle_message", "serve"]
