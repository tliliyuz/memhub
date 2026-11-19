"""LLM 客户端（Anthropic 协议，异步 HTTP）与 JSON 解析。

注意：httpx 默认读取环境代理变量，`NO_PROXY` 里含 `[::1]` 时会抛
`InvalidURL: Invalid port: ':1]'`。这里默认 `trust_env=False`，代理需显式传入。
"""

from __future__ import annotations

import asyncio
import json
import random
from typing import Protocol

import httpx


class LLMError(RuntimeError):
    pass


class LLMClient(Protocol):
    async def complete(self, prompt: str, *, model: str, max_tokens: int = 8000) -> str: ...


def _messages_url(base_url: str) -> str:
    """拼出 `/v1/messages`；base_url 已经以 `/v1` 结尾时不重复拼接。

    两种写法都常见（`https://host`、`https://host/v1`），拼错会得到
    `/v1/v1/messages` 这种 404，而报错信息看起来像凭据或路径问题。
    """
    base = base_url.rstrip("/")
    return base + ("/messages" if base.endswith("/v1") else "/v1/messages")


class AnthropicClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout: float = 300.0,
        attempts: int = 3,
        trust_env: bool = False,
    ) -> None:
        self._url = _messages_url(base_url)
        self._api_key = api_key
        self._timeout = timeout
        self._attempts = attempts
        self._http = httpx.AsyncClient(timeout=timeout, trust_env=trust_env)

    async def complete(self, prompt: str, *, model: str, max_tokens: int = 8000) -> str:
        payload = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        last_error = ""
        for attempt in range(self._attempts):
            try:
                response = await self._http.post(self._url, headers=headers, json=payload)
            except httpx.HTTPError as exc:
                last_error = f"{type(exc).__name__}: {exc}"
            else:
                if response.status_code == 200:
                    body = response.json()
                    parts = [
                        block.get("text", "")
                        for block in body.get("content", [])
                        if block.get("type") == "text"
                    ]
                    text = "".join(parts).strip()
                    if text:
                        return text
                    # 200 但没有 text 块：可能是上游偶发空响应，也可能是
                    # max_tokens 全被 thinking 吃掉。带上 stop_reason 重试，
                    # 两种情况在日志里才能区分开。
                    kinds = ",".join(str(block.get("type")) for block in body.get("content", []))
                    last_error = (
                        f"模型返回空内容（stop_reason={body.get('stop_reason')}, blocks=[{kinds}]）"
                    )
                else:
                    last_error = f"HTTP {response.status_code}: {response.text[:200]}"
                    if response.status_code < 500 and response.status_code != 429:
                        raise LLMError(last_error)
            if attempt + 1 < self._attempts:
                await asyncio.sleep(min(30.0, 2.0**attempt + random.random()))
        raise LLMError(f"调用失败（{self._attempts} 次）: {last_error}")

    async def aclose(self) -> None:
        await self._http.aclose()


def parse_json(raw: str) -> dict[str, object]:
    """剥离代码块与前后说明，取第一个完整 JSON 对象。"""
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise LLMError("返回内容中找不到 JSON 对象")
    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise LLMError(f"JSON 解析失败: {exc}") from exc
    if not isinstance(parsed, dict):
        raise LLMError("JSON 顶层不是对象")
    return parsed
