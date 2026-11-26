"""CLI 重抽入口：清理已见消息索引（规格 §6、T11）。

命令只清运行态索引，不动游标与 raw；缺 `MEMHUB_DB_URL` 属配置错误，退出 2。
"""

from __future__ import annotations

import argparse

import pytest

from memhub.cli import main as cli
from memhub.cli.main import _forget_messages
from memhub.ingest.store import MemoryStore


async def test_forget_messages_requires_dsn(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MEMHUB_DB_URL", raising=False)
    args = argparse.Namespace(project="p", source_id=None)

    assert await _forget_messages(args) == 2


async def test_forget_messages_clears_injected_state(
    capsys: pytest.CaptureFixture[str],
) -> None:
    state = MemoryStore()
    await state.mark_messages_seen("p", "s", ["u1", "u2"])
    await state.mark_messages_seen("p", "t", ["u3"])
    args = argparse.Namespace(project="p", source_id="s", state=state)

    assert await _forget_messages(args) == 0

    assert "2" in capsys.readouterr().out
    assert await state.seen_messages("p", "s", ["u1", "u2"]) == set()
    assert await state.seen_messages("p", "t", ["u3"]) == {"u3"}


async def test_forget_messages_without_source_clears_the_project(
    capsys: pytest.CaptureFixture[str],
) -> None:
    state = MemoryStore()
    await state.mark_messages_seen("p", "s", ["u1"])
    await state.mark_messages_seen("p", "t", ["u2"])
    args = argparse.Namespace(project="p", source_id=None, state=state)

    assert await _forget_messages(args) == 0

    assert "2" in capsys.readouterr().out
    assert await state.seen_messages("p", "s", ["u1"]) == set()
    assert await state.seen_messages("p", "t", ["u2"]) == set()


def test_forget_messages_command_is_wired(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MEMHUB_DB_URL", raising=False)

    assert cli.main(["forget-messages", "--project", "p"]) == 2
