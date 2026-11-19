"""worker 守护进程：窗口门控、待处理扫描、单轮提炼、退避退出码。"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from datetime import time as dtime
from pathlib import Path

import pytest

from memhub.contract import BatchFile, IngestRequest
from memhub.ingest.rawstore import save_batch
from memhub.worker.daemon import (
    RoundReport,
    WorkerConfig,
    in_window,
    iter_pending,
    parse_window,
    probe_endpoint,
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

    def complete(self, prompt: str, *, model: str, max_tokens: int = 8000) -> str:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.reply


def _session_line(text: str) -> str:
    """一行合法的 Claude Code 会话事件，render_jsonl 能抽出文本。"""
    return json.dumps(
        {"type": "user", "message": {"role": "user", "content": text}}, ensure_ascii=False
    )


def _config(tmp_path: Path, **kwargs: object) -> WorkerConfig:
    (tmp_path / "knowledge").mkdir(exist_ok=True)
    return WorkerConfig(
        data_dir=tmp_path,
        knowledge_dir=tmp_path / "knowledge",
        model="test-model",
        **kwargs,  # type: ignore[arg-type]
    )


def _push(tmp_path: Path, content: str, *, path: str = "sessions/a.jsonl") -> None:
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
    save_batch(tmp_path, request)


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


def test_iter_pending_skips_processed(tmp_path: Path) -> None:
    _push(tmp_path, "hello")
    config = _config(tmp_path)
    pending = iter_pending(config.raw_root, config.processed_root)
    assert len(pending) == 1
    target = config.processed_root / pending[0].relative_to(config.raw_root)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("{}", encoding="utf-8")
    assert iter_pending(config.raw_root, config.processed_root) == []


def test_round_extracts_and_marks_processed(tmp_path: Path) -> None:
    _push(tmp_path, _session_line("用户说：网络重试需要退避。"))
    config = _config(tmp_path)
    client = FakeClient()
    report = run_round(client, config)

    assert (report.processed, report.failed, report.created) == (1, 0, 1)
    assert client.calls == 1
    knowledge_files = list(config.knowledge_dir.rglob("*.md"))
    assert len(knowledge_files) == 1
    assert iter_pending(config.raw_root, config.processed_root) == []
    assert len(list(config.processed_root.rglob("*.json"))) == 1


def test_round_keeps_failed_file_for_retry(tmp_path: Path) -> None:
    _push(tmp_path, "hello")
    config = _config(tmp_path)
    report = run_round(FakeClient(error=LLMError("boom")), config)

    assert (report.processed, report.failed) == (0, 1)
    assert len(report.errors) == 1
    # 失败文件留在原地，下一轮重试；不能移进 processed。
    assert len(iter_pending(config.raw_root, config.processed_root)) == 1


def test_forever_respects_window_and_backs_off(tmp_path: Path) -> None:
    _push(tmp_path, "hello")
    config = _config(tmp_path, window="21:00-02:00", interval=60.0)
    sleeps: list[float] = []
    # 本地时间 12:00 在窗口外。
    outside = datetime(2026, 11, 19, 4, 0, tzinfo=UTC).astimezone()
    report = run_round(FakeClient(error=LLMError("boom")), config)
    assert report.failed == 1
    code = run_forever(
        FakeClient(error=LLMError("boom")),
        config,
        now=lambda: outside,
        sleep=lambda seconds: sleeps.append(seconds),
        max_rounds=1,
    )
    assert code == 0
    assert sleeps == [60.0]  # 窗口外只睡 interval，不去碰 LLM


def test_probe_endpoint_rejects_unreachable_host() -> None:
    with pytest.raises(LLMError, match="不可达"):
        probe_endpoint("http://127.0.0.1:1", timeout=0.2)


def test_empty_round_reports_nothing(tmp_path: Path) -> None:
    config = _config(tmp_path)
    report = run_round(FakeClient(), config)
    assert report == RoundReport()


def test_backoff_grows_on_repeated_failure(tmp_path: Path) -> None:
    _push(tmp_path, "hello")
    config = _config(tmp_path, window="", interval=60.0)
    sleeps: list[float] = []
    inside = datetime.now(UTC).astimezone() + timedelta(seconds=1)
    code = run_forever(
        FakeClient(error=LLMError("boom")),
        config,
        now=lambda: inside,
        sleep=lambda seconds: sleeps.append(seconds),
        max_rounds=3,
    )
    assert code == 1
    assert sleeps == [120.0, 240.0, 480.0]


def test_repeated_failure_quarantines_file(tmp_path: Path) -> None:
    """连续失败到上限就移进 pending_review：毒文件不能每轮都重新付费重试。"""
    _push(tmp_path, "hello")
    config = _config(tmp_path, max_attempts=3)

    for _ in range(3):
        report = run_round(FakeClient(error=LLMError("boom")), config)
        assert report.failed == 1

    assert iter_pending(config.raw_root, config.processed_root) == []
    quarantined = list(config.pending_root.rglob("*.json"))
    assert len(quarantined) == 1, "原始字节要留下来给人排查"
    assert json.loads(config.failures_path.read_text(encoding="utf-8")) == {}

    # 隔离后不再占用队列，后续轮次也不该再调模型。
    client = FakeClient(error=LLMError("boom"))
    assert run_round(client, config) == RoundReport()
    assert client.calls == 0


def test_failure_counter_resets_after_success(tmp_path: Path) -> None:
    _push(tmp_path, _session_line("用户说：重试要退避。"))
    config = _config(tmp_path, max_attempts=2)

    assert run_round(FakeClient(error=LLMError("boom")), config).failed == 1
    assert run_round(FakeClient(), config).processed == 1
    assert json.loads(config.failures_path.read_text(encoding="utf-8")) == {}


def test_purge_pending_review_removes_only_expired(tmp_path: Path) -> None:
    """隔离区必须有人清理：毒文件不清理就是无限占盘。"""
    root = tmp_path / "pending_review" / "dev" / "cc-sessions"
    root.mkdir(parents=True)
    old = root / "old.json"
    fresh = root / "fresh.json"
    old.write_text("old-bytes", encoding="utf-8")
    fresh.write_text("new", encoding="utf-8")
    stale = (datetime.now(UTC) - timedelta(days=40)).timestamp()
    os.utime(old, (stale, stale))

    removed, size = purge_pending_review(tmp_path, older_than=timedelta(days=30))

    assert (removed, size) == (1, len("old-bytes"))
    assert not old.exists()
    assert fresh.exists()
    assert purge_pending_review(tmp_path / "missing", older_than=timedelta(days=30)) == (0, 0)


def test_purge_pending_review_reclaims_empty_dirs(tmp_path: Path) -> None:
    root = tmp_path / "pending_review" / "dev" / "cc-sessions"
    root.mkdir(parents=True)
    stale_file = root / "old.json"
    stale_file.write_text("x", encoding="utf-8")
    stale = (datetime.now(UTC) - timedelta(days=40)).timestamp()
    os.utime(stale_file, (stale, stale))

    purge_pending_review(tmp_path, older_than=timedelta(days=30))

    assert not (tmp_path / "pending_review").exists()
