"""Anthropic 协议客户端：URL 拼接与空响应重试。"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from memhub.worker.llm import AnthropicClient, LLMError, _messages_url


@pytest.mark.parametrize(
    ("base_url", "expected"),
    [
        ("https://api.example.com", "https://api.example.com/v1/messages"),
        ("https://api.example.com/", "https://api.example.com/v1/messages"),
        ("https://api.example.com/v1", "https://api.example.com/v1/messages"),
        ("https://api.example.com/v1/", "https://api.example.com/v1/messages"),
    ],
)
def test_messages_url(base_url: str, expected: str) -> None:
    assert _messages_url(base_url) == expected


def _client(handler: httpx.AsyncBaseTransport, *, attempts: int = 2) -> AnthropicClient:
    client = AnthropicClient("https://api.example.com", "test-key", attempts=attempts)
    client._http = httpx.AsyncClient(transport=handler)
    return client


async def test_default_max_tokens_leaves_room_for_thinking() -> None:
    """8000 会被 thinking 吃光（线上首跑 stop_reason=max_tokens），默认必须更宽。"""
    payloads: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payloads.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={"stop_reason": "end_turn", "content": [{"type": "text", "text": "ok"}]},
        )

    client = _client(httpx.MockTransport(handler))
    try:
        assert await client.complete("hi", model="m") == "ok"
    finally:
        await client.aclose()
    assert payloads[0]["max_tokens"] == 32000


async def test_empty_text_is_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(
                200,
                json={
                    "stop_reason": "end_turn",
                    "content": [{"type": "thinking"}, {"type": "text", "text": "  "}],
                },
            )
        return httpx.Response(
            200,
            json={"stop_reason": "end_turn", "content": [{"type": "text", "text": "ok"}]},
        )

    async def no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", no_sleep)
    client = _client(httpx.MockTransport(handler))
    try:
        assert await client.complete("hi", model="m") == "ok"
    finally:
        await client.aclose()
    assert len(calls) == 2


async def test_empty_text_error_includes_stop_reason() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "stop_reason": "max_tokens",
                "content": [{"type": "thinking"}, {"type": "text", "text": ""}],
            },
        )

    client = _client(httpx.MockTransport(handler), attempts=1)
    try:
        with pytest.raises(LLMError) as excinfo:
            await client.complete("hi", model="m")
    finally:
        await client.aclose()
    message = str(excinfo.value)
    assert "max_tokens" in message
    assert "thinking" in message
