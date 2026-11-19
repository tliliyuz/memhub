"""worker 守护进程：窗口门控、待处理扫描、单轮提炼、退避退出码（异步 IO）。"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from datetime import time as dtime
from pathlib import Path

import anyio
import pytest
from anyio import Path as AsyncPath

from memhub.contract import BatchFile, IngestRequest
from memhub.ingest.rawstore import save_batch
from memhub.worker.daemon import (
    RoundReport,
    WorkerConfig,
    in_window,
    iter_pending,
    parse_window,
    probe_endpoint,
    prune_processed_raw,
    purge_pending_review,
    run_forever,
    run_round,
)
from memhub.worker.llm import LLMError

NOW = datetime(2026, 11, 19, 2, 0, tzinfo=UTC)

LLM_REPLY = json.dumps(
    {
        "nodes": [
            {
                "kind": "fact",
                "slug": "retry-backoff",
                "title": "重试需要退避",
                "body": "失败后指数退避，避免打爆下游。",
            }
        ],
        "edges": [],
    },
    ensure_ascii=False,
)


class FakeClient:
    def __init__(self, reply: str = LLM_REPLY, error: Exception | None = None) -> None:
        self.reply = reply
        self.error = error
        self.calls = 0

    async def complete(self, prompt: str, *, model: str, max_tokens: int = 8000) -> str:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.reply


def _session_line(text: str) -> str:
    """一行合法的 Claude Code 会话事件，render_jsonl 能抽出文本。"""
    return json.dumps(
        {"type": "user", "message": {"role": "user", "content": text}}, ensure_ascii=False
    )


async def _config(tmp_path: Path, **kwargs: object) -> WorkerConfig:
    await AsyncPath(tmp_path / "knowledge").mkdir(exist_ok=True)
    return WorkerConfig(
        data_dir=tmp_path,
        knowledge_dir=tmp_path / "knowledge",
        model="test-model",
        **kwargs,  # type: ignore[arg-type]
    )


async def _push(tmp_path: Path, content: str, *, path: str = "sessions/a.jsonl") -> None:
    sha = hashlib.sha256(content.encode()).hexdigest()
    request = IngestRequest(
        batch_id=f"b-{sha[:6]}",
        device_id="dev-1",
        source_id="cc-sessions",
        source_type="sessions",
        files=[
            BatchFile(
                path=path,
                from_offset=0,
                to_offset=len(content),
                mtime=NOW,
                sha256=sha,
                content=content,
            )
        ],
    )
    await save_batch(tmp_path, request)


def _sleeper(sleeps: list[float]) -> Callable[[float], Awaitable[None]]:
    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    return sleep


async def _set_mtime(path: Path, stamp: float) -> None:
    await anyio.to_thread.run_sync(os.utime, path, (stamp, stamp))


def test_parse_window_rejects_bad_format() -> None:
    assert parse_window("21:00-02:00") == (dtime(21, 0), dtime(2, 0))
    with pytest.raises(ValueError, match="HH:MM-HH:MM"):
        parse_window("21-2")


def test_cross_midnight_window() -> None:
    window = parse_window("21:00-02:00")
    assert in_window(dtime(21, 0), window)
    assert in_window(dtime(23, 59), window)
    assert in_window(dtime(1, 59), window)
    assert not in_window(dtime(2, 0), window)
    assert not in_window(dtime(12, 0), window)


async def test_iter_pending_skips_processed(tmp_path: Path) -> None:
    await _push(tmp_path, "hello")
    config = await _config(tmp_path)
    pending = await iter_pending(config.raw_root, config.processed_root)
    assert len(pending) == 1
    target = config.processed_root / pending[0].relative_to(config.raw_root)
    await AsyncPath(target.parent).mkdir(parents=True, exist_ok=True)
    await AsyncPath(target).write_text("{}", encoding="utf-8")
    assert await iter_pending(config.raw_root, config.processed_root) == []


async def test_round_extracts_and_marks_processed(tmp_path: Path) -> None:
    await _push(tmp_path, _session_line("用户说：网络重试需要退避。"))
    config = await _config(tmp_path)
    client = FakeClient()
    report = await run_round(client, config)

    assert (report.processed, report.failed, report.created) == (1, 0, 1)
    assert client.calls == 1
    knowledge_files = [item async for item in AsyncPath(config.knowledge_dir).rglob("*.md")]
    assert len(knowledge_files) == 1
    assert await iter_pending(config.raw_root, config.processed_root) == []
    processed = [item async for item in AsyncPath(config.processed_root).rglob("*.json")]
    assert len(processed) == 1


async def test_round_keeps_failed_file_for_retry(tmp_path: Path) -> None:
    await _push(tmp_path, "hello")
    config = await _config(tmp_path)
    report = await run_round(FakeClient(error=LLMError("boom")), config)

    assert (report.processed, report.failed) == (0, 1)
    assert len(report.errors) == 1
    # 失败文件留在原地，下一轮重试；不能移进 processed。
    assert len(await iter_pending(config.raw_root, config.processed_root)) == 1


async def test_forever_respects_window_and_backs_off(tmp_path: Path) -> None:
    await _push(tmp_path, "hello")
    config = await _config(tmp_path, window="21:00-02:00", interval=60.0)
    sleeps: list[float] = []
    # 本地时间 12:00 在窗口外。
    outside = datetime(2026, 11, 19, 4, 0, tzinfo=UTC).astimezone()
    report = await run_round(FakeClient(error=LLMError("boom")), config)
    assert report.failed == 1
    code = await run_forever(
        FakeClient(error=LLMError("boom")),
        config,
        now=lambda: outside,
        sleep=_sleeper(sleeps),
        max_rounds=1,
    )
    assert code == 0
    assert sleeps == [60.0]  # 窗口外只睡 interval，不去碰 LLM


async def test_probe_endpoint_rejects_unreachable_host() -> None:
    with pytest.raises(LLMError, match="不可达"):
        await probe_endpoint("http://127.0.0.1:1", timeout=0.2)


async def test_empty_round_reports_nothing(tmp_path: Path) -> None:
    config = await _config(tmp_path)
    report = await run_round(FakeClient(), config)
    assert report == RoundReport()


async def test_backoff_grows_on_repeated_failure(tmp_path: Path) -> None:
    await _push(tmp_path, "hello")
    config = await _config(tmp_path, window="", interval=60.0)
    sleeps: list[float] = []
    inside = datetime.now(UTC).astimezone() + timedelta(seconds=1)
    code = await run_forever(
        FakeClient(error=LLMError("boom")),
        config,
        now=lambda: inside,
        sleep=_sleeper(sleeps),
        max_rounds=3,
    )
    assert code == 1
    assert sleeps == [120.0, 240.0, 480.0]


async def test_repeated_failure_quarantines_file(tmp_path: Path) -> None:
    """连续失败到上限就移进 pending_review：毒文件不能每轮都重新付费重试。"""
    await _push(tmp_path, "hello")
    config = await _config(tmp_path, max_attempts=3)

    for _ in range(3):
        report = await run_round(FakeClient(error=LLMError("boom")), config)
        assert report.failed == 1

    assert await iter_pending(config.raw_root, config.processed_root) == []
    quarantined = [item async for item in AsyncPath(config.pending_root).rglob("*.json")]
    assert len(quarantined) == 1, "原始字节要留下来给人排查"
    failures = json.loads(await AsyncPath(config.failures_path).read_text(encoding="utf-8"))
    assert failures == {}

    # 隔离后不再占用队列，后续轮次也不该再调模型。
    client = FakeClient(error=LLMError("boom"))
    assert await run_round(client, config) == RoundReport()
    assert client.calls == 0


async def test_failure_counter_resets_after_success(tmp_path: Path) -> None:
    await _push(tmp_path, _session_line("用户说：重试要退避。"))
    config = await _config(tmp_path, max_attempts=2)

    assert (await run_round(FakeClient(error=LLMError("boom")), config)).failed == 1
    assert (await run_round(FakeClient(), config)).processed == 1
    failures = json.loads(await AsyncPath(config.failures_path).read_text(encoding="utf-8"))
    assert failures == {}


async def test_purge_pending_review_removes_only_expired(tmp_path: Path) -> None:
    """隔离区必须有人清理：毒文件不清理就是无限占盘。"""
    root = tmp_path / "pending_review" / "dev" / "cc-sessions"
    await AsyncPath(root).mkdir(parents=True)
    old = root / "old.json"
    fresh = root / "fresh.json"
    await AsyncPath(old).write_text("old-bytes", encoding="utf-8")
    await AsyncPath(fresh).write_text("new", encoding="utf-8")
    stale = (datetime.now(UTC) - timedelta(days=40)).timestamp()
    await _set_mtime(old, stale)

    removed, size = await purge_pending_review(tmp_path, older_than=timedelta(days=30))

    assert (removed, size) == (1, len("old-bytes"))
    assert not await AsyncPath(old).exists()
    assert await AsyncPath(fresh).exists()
    missing = tmp_path / "missing"
    assert await purge_pending_review(missing, older_than=timedelta(days=30)) == (0, 0)


async def test_purge_pending_review_reclaims_empty_dirs(tmp_path: Path) -> None:
    root = tmp_path / "pending_review" / "dev" / "cc-sessions"
    await AsyncPath(root).mkdir(parents=True)
    stale_file = root / "old.json"
    await AsyncPath(stale_file).write_text("x", encoding="utf-8")
    stale = (datetime.now(UTC) - timedelta(days=40)).timestamp()
    await _set_mtime(stale_file, stale)

    await purge_pending_review(tmp_path, older_than=timedelta(days=30))

    assert not await AsyncPath(tmp_path / "pending_review").exists()


async def test_prune_processed_raw_drops_oldest_until_under_cap(tmp_path: Path) -> None:
    """processed_raw 是 raw_store 的副本，不受配额约束，必须按总量裁剪。"""
    root = tmp_path / "processed_raw" / "dev" / "cc-sessions"
    await AsyncPath(root).mkdir(parents=True)
    now = datetime.now(UTC)
    for index, size in enumerate([200, 300, 500]):
        path = root / f"{index}.json"
        await AsyncPath(path).write_bytes(b"x" * size)
        stamp = (now - timedelta(days=3 - index)).timestamp()
        await _set_mtime(path, stamp)

    removed, removed_bytes = await prune_processed_raw(
        tmp_path, max_bytes=600, older_than=timedelta(days=7)
    )

    assert (removed, removed_bytes) == (2, 500)
    names = sorted([item.name async for item in AsyncPath(root).iterdir()])
    assert names == ["2.json"]


async def test_prune_processed_raw_drops_files_past_retention(tmp_path: Path) -> None:
    root = tmp_path / "processed_raw" / "dev" / "cc-sessions"
    await AsyncPath(root).mkdir(parents=True)
    old = root / "old.json"
    fresh = root / "fresh.json"
    await AsyncPath(old).write_bytes(b"old")
    await AsyncPath(fresh).write_bytes(b"new")
    stamp = (datetime.now(UTC) - timedelta(days=10)).timestamp()
    await _set_mtime(old, stamp)

    removed, _ = await prune_processed_raw(
        tmp_path, max_bytes=1 << 20, older_than=timedelta(days=7)
    )

    assert removed == 1
    assert not await AsyncPath(old).exists()
    assert await AsyncPath(fresh).exists()
