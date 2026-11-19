"""Anthropic 协议客户端的 URL 拼接（base_url 带不带 `/v1` 都要正确）。"""

from __future__ import annotations

import pytest

from memhub.worker.llm import _messages_url


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
