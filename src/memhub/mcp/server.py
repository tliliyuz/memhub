"""MCP stdio 传输：UTF-8，每行一条 JSON-RPC 2.0 消息。"""

from __future__ import annotations

import json
import sys
from typing import Any, TextIO

import anyio

from memhub import __version__
from memhub.kb.pgstore import PgKnowledgeStore
from memhub.kb.store import KnowledgeStore
from memhub.mcp.discovery import INSTRUCTIONS
from memhub.mcp.tools import TOOL_NAMES, TOOLS, call_tool

SERVER_NAME = "memhub"
DEFAULT_PROTOCOL = "2025-06-18"

JSONRPC_PARSE_ERROR = -32700
JSONRPC_INVALID_REQUEST = -32600
JSONRPC_METHOD_NOT_FOUND = -32601
JSONRPC_INVALID_PARAMS = -32602


def _ok(message_id: object, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "result": result}


def _error(message_id: object, code: int, text: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "error": {"code": code, "message": text}}


async def handle_message(
    message: dict[str, Any], store: KnowledgeStore | PgKnowledgeStore
) -> dict[str, Any] | None:
    """一条 JSON-RPC 消息 → 响应；已知通知返回 None。"""
    message_id = message.get("id")
    method = message.get("method")
    if not isinstance(method, str):
        return _error(message_id, JSONRPC_INVALID_REQUEST, "missing method")
    params = message.get("params", {})
    if not isinstance(params, dict):
        return _error(message_id, JSONRPC_INVALID_PARAMS, "params must be an object")

    if method == "initialize":
        requested = params.get("protocolVersion")
        return _ok(
            message_id,
            {
                "protocolVersion": requested or DEFAULT_PROTOCOL,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": __version__},
                "instructions": INSTRUCTIONS,
            },
        )
    if method in {"notifications/initialized", "notifications/cancelled"}:
        return None
    if method == "ping":
        return _ok(message_id, {})
    if method == "tools/list":
        return _ok(message_id, {"tools": TOOLS})
    if method == "tools/call":
        name = params.get("name")
        if not isinstance(name, str) or name not in TOOL_NAMES:
            return _error(message_id, JSONRPC_INVALID_PARAMS, "unknown or missing tool name")
        arguments = params.get("arguments", {})
        if not isinstance(arguments, dict):
            return _error(message_id, JSONRPC_INVALID_PARAMS, "arguments must be an object")
        # stdio 是本机全库权限，写工具可用；凭据标识固定为 "stdio"。
        return _ok(
            message_id,
            await call_tool(name, arguments, store, writable=True, memory=True, grant_id="stdio"),
        )
    return _error(message_id, JSONRPC_METHOD_NOT_FOUND, f"unknown method: {method}")


async def _write(stdout: TextIO, payload: dict[str, Any]) -> None:
    text = json.dumps(payload, ensure_ascii=False) + "\n"
    await anyio.to_thread.run_sync(stdout.write, text)
    await anyio.to_thread.run_sync(stdout.flush)


def _use_utf8(stream: TextIO) -> None:
    """协议固定 UTF-8，避免 Windows 管道默认编码损坏中文。"""
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is not None:
        try:
            reconfigure(encoding="utf-8", errors="replace", newline="\n")
        except (ValueError, OSError):
            pass


async def serve(
    store: KnowledgeStore | PgKnowledgeStore,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
) -> int:
    """跑 stdio 直到 stdin 关闭。日志走 stderr，stdout 只放协议。"""
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
