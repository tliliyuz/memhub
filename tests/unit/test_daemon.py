"""worker 守护进程：窗口门控、队列领取、单轮提炼、退避退出码（异步 IO）。"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from datetime import time as dtime
from pathlib import Path
from typing import Any

import anyio
import pytest
from anyio import Path as AsyncPath
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from memhub.contract import BatchFile, IngestRequest, Tier
from memhub.ingest.store import MemoryStore
from memhub.kb import catalog, manage
from memhub.kb.models import Base, KbArchive, KbWriteAudit
from memhub.kb.pgstore import PgKnowledgeStore
from memhub.kb.session import create_sessionmaker
from memhub.kb.store import KnowledgeStore
from memhub.kb.target_access import TargetRegistry
from memhub.queue.content import LocalContentStore
from memhub.queue.flow import enqueue_batch
from memhub.queue.tasks import DEFAULT_LEASE, MemoryQueue
from memhub.worker.daemon import (
    RoundReport,
    WorkerConfig,
    in_window,
    parse_window,
    parse_window_tz,
    probe_endpoint,
    run_forever,
    run_round,
)
from memhub.worker.llm import LLMError
from memhub.worker.memory import MemoryContext, MemorySettings

NOW = datetime(2026, 11, 27, 2, 0, tzinfo=UTC)
EVIDENCE = "网络重试需要指数退避。"
PROJECTS = ("cc-sessions", "sdp-tag", "archived", "active", "demo")

LLM_REPLY = json.dumps(
    {
        "nodes": [
            {
                "kind": "fact",
                "slug": "retry-backoff",
                "title": "重试需要退避",
                "body": "失败后指数退避，避免打爆下游。",
                "evidence": [{"block": "b0001", "quote": EVIDENCE}],
            }
        ],
        "edges": [],
    },
    ensure_ascii=False,
)

_UNSET = object()


class FakeClient:
    def __init__(self, reply: str = LLM_REPLY, error: Exception | None = None) -> None:
        self.reply = reply
        self.error = error
        self.calls = 0
        self.max_tokens_seen: list[int] = []
        self.prompts: list[str] = []

    async def complete(self, prompt: str, *, model: str, max_tokens: int = 32000) -> str:
        self.calls += 1
        self.max_tokens_seen.append(max_tokens)
        self.prompts.append(prompt)
        if self.error is not None:
            raise self.error
        return self.reply


def _session_line(text: str) -> str:
    """一行合法的 Claude Code 会话事件，render_jsonl 能抽出文本。"""
    return json.dumps(
        {"type": "user", "message": {"role": "user", "content": text}}, ensure_ascii=False
    )


@dataclass
class Env:
    """一轮提炼需要的三件事：队列（谁待处理）、正文（读什么）、真源（写哪里）。"""

    root: Path
    knowledge: Path
    state: MemoryStore
    queue: MemoryQueue
    content: LocalContentStore
    config: WorkerConfig


async def _env(tmp_path: Path, **kwargs: Any) -> Env:
    knowledge_dir = tmp_path / "knowledge"
    for project in PROJECTS:
        await catalog.create_kb(KnowledgeStore(knowledge_dir), kb_id=project)

    state = MemoryStore()
    await state.register_device("dev-1")
    worker_state = kwargs.pop("state", _UNSET)
    registered = kwargs.pop("is_registered", _UNSET)
    kwargs.setdefault("state", state if worker_state is _UNSET else worker_state)
    kwargs.setdefault("is_registered", state.is_registered if registered is _UNSET else registered)
    kwargs.setdefault("target_registry", TargetRegistry(KnowledgeStore(knowledge_dir)))
    queue = MemoryQueue()
    content_store = LocalContentStore(tmp_path / "content_store")
    config = WorkerConfig(
        queue=queue,
        content=content_store,
        store=KnowledgeStore(knowledge_dir),
        model="test-model",
        **kwargs,
    )
    return Env(tmp_path, knowledge_dir, state, queue, content_store, config)


async def _push(
    env: Env,
    content: str,
    *,
    path: str = "sessions/a.txt",
    project: str = "cc-sessions",
    device_id: str = "dev-1",
    source_id: str = "cc-sessions",
    source_type: str = "sessions",
) -> str:
    """走真实入队路径：正文进存储、队列行入队、游标推进。返回 sha。"""
    sha = hashlib.sha256(content.encode()).hexdigest()
    request = IngestRequest(
        batch_id=f"b-{sha[:6]}",
        device_id=device_id,
        source_id=source_id,
        source_type=source_type,
        project=project,
        files=[
            BatchFile(
                path=path,
                from_offset=0,
                to_offset=len(content.encode()),
                mtime=NOW,
                sha256=sha,
                content=content,
            )
        ],
    )
    producer = "console" if device_id == "kb-console" else "collector"
    await enqueue_batch(env.state, env.queue, env.content, request, producer=producer, limit=10**9)
    return sha


def _row(env: Env, sha: str, project: str = "cc-sessions") -> Any:
    return env.queue.rows[(project, sha)]


def _retarget(env: Env, sha: str, *, old: str = "cc-sessions", **changes: object) -> Any:
    """改写队列行，模拟旧版文件队列里可能出现的异常行。"""
    row = env.queue.rows.pop((old, sha))
    for key, value in changes.items():
        setattr(row, key, value)
    env.queue.rows[(row.project, row.sha256)] = row
    return row


def _knowledge_files(env: Env) -> list[Path]:
    return [Path(item) for item in env.knowledge.rglob("*.md")]


def _pg_config(env: Env, store: PgKnowledgeStore, **kwargs: object) -> WorkerConfig:
    return WorkerConfig(
        queue=env.queue,
        content=env.content,
        store=store,
        model="test-model",
        is_registered=env.state.is_registered,
        target_registry=TargetRegistry(store),
        **kwargs,  # type: ignore[arg-type]
    )


@pytest.fixture
async def pg_store(kb_engine: AsyncEngine) -> PgKnowledgeStore:
    async with kb_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return PgKnowledgeStore(create_sessionmaker(kb_engine))


def _sleeper(sleeps: list[float]) -> Callable[[float], Awaitable[None]]:
    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    return sleep


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


def test_parse_window_tz() -> None:
    assert parse_window_tz("") is None
    assert parse_window_tz("UTC") is UTC
    assert parse_window_tz("+08:00") == timezone(timedelta(hours=8))
    assert parse_window_tz("-0530") == timezone(-timedelta(hours=5, minutes=30))
    with pytest.raises(ValueError):
        parse_window_tz("+15:00")
    with pytest.raises(ValueError):
        parse_window_tz("Mars/Olympus")


async def test_window_uses_configured_timezone(tmp_path: Path) -> None:
    """容器默认 UTC：13:30Z 是北京 21:30（窗口内），10:00Z 是北京 18:00（窗口外）。"""
    env = await _env(tmp_path, window="21:00-02:00", window_tz=timezone(timedelta(hours=8)))
    await _push(env, "hello")

    sleeps: list[float] = []
    inside = datetime(2026, 11, 19, 13, 30, tzinfo=UTC)
    assert (
        await run_forever(
            FakeClient(), env.config, now=lambda: inside, sleep=_sleeper(sleeps), max_rounds=1
        )
        == 0
    )
    assert sleeps == [], "窗口内不能睡"

    outside = datetime(2026, 11, 19, 10, 0, tzinfo=UTC)
    assert (
        await run_forever(
            FakeClient(), env.config, now=lambda: outside, sleep=_sleeper(sleeps), max_rounds=1
        )
        == 0
    )
    assert sleeps == [env.config.interval], "窗口外只睡 interval，不去碰 LLM"


async def test_round_extracts_and_marks_processed(tmp_path: Path) -> None:
    env = await _env(tmp_path)
    sha = await _push(env, _session_line(EVIDENCE), path="sessions/a.jsonl")
    client = FakeClient()

    report = await run_round(client, env.config)

    assert (report.processed, report.failed, report.created) == (1, 0, 1)
    assert client.calls == 1
    assert len(_knowledge_files(env)) == 1
    row = _row(env, sha)
    assert (row.status, row.error, row.processed_at is not None) == ("processed", None, True)


async def test_meta_only_session_is_not_sent_to_the_model(tmp_path: Path) -> None:
    """只有 isMeta 注入时保持空文本，不能以原文兜底绕过过滤。"""
    line = json.dumps(
        {
            "type": "user",
            "isMeta": True,
            "message": {"role": "user", "content": "Base directory for this skill: ..."},
        },
        ensure_ascii=False,
    )
    env = await _env(tmp_path)
    await _push(env, line, path="sessions/a.jsonl")
    client = FakeClient()

    report = await run_round(client, env.config)

    assert report.processed == 1
    assert client.calls == 0, "没有真实对话就不该调用模型"


async def test_archived_input_is_quarantined_without_starving_active_projects(
    tmp_path: Path,
) -> None:
    env = await _env(tmp_path, limit=2)
    blocked_sha = await _push(env, "blocked", project="archived")
    _row(env, blocked_sha, "archived").created_at = NOW - timedelta(hours=1)
    active_sha = await _push(env, EVIDENCE, project="active", path="sessions/b.txt")
    marker = AsyncPath(env.knowledge / "_kb_archives" / "blocked" / "archived")
    await marker.parent.mkdir(parents=True)
    await marker.touch()
    client = FakeClient()

    report = await run_round(client, env.config)

    assert (report.processed, report.failed, report.created) == (1, 0, 1)
    assert client.calls == 1
    assert report.quarantined == 1
    assert report.errors == ["target_inactive"]
    assert _row(env, blocked_sha, "archived").status == "pending_review"
    assert _row(env, active_sha, "active").status == "processed"
    assert not list((env.knowledge / "archived").iterdir())


@pytest.mark.parametrize(
    "archive_state", ["_kb_archives/pending.json", "_kb_archives/blocked/demo"]
)
async def test_archive_started_during_extraction_blocks_worker_merge(
    tmp_path: Path, archive_state: str
) -> None:
    env = await _env(tmp_path, max_attempts=1)
    sha = await _push(env, EVIDENCE, project="demo")
    marker = AsyncPath(env.knowledge / archive_state)

    class ArchivingClient(FakeClient):
        async def complete(self, prompt: str, *, model: str, max_tokens: int = 32000) -> str:
            async with manage.write_lock(env.knowledge):
                await marker.parent.mkdir(parents=True)
                await marker.touch()
            return await super().complete(prompt, model=model, max_tokens=max_tokens)

    client = ArchivingClient()
    report = await run_round(client, env.config)

    assert client.calls == 1
    assert (report.processed, report.failed, report.created) == (0, 0, 0)
    assert not list((env.knowledge / "demo").iterdir())
    row = _row(env, sha, "demo")
    if archive_state.endswith("pending.json"):
        # 归档事务未完成：退回队列且不消耗失败次数，下一轮再试。
        assert (row.status, row.attempts) == ("queued", 0)
        assert report.quarantined == 0
    else:
        assert row.status == "pending_review"
        assert report.errors == ["target_inactive"]
    # 归档未结束时不应再次付费抽取。
    assert (await run_round(client, env.config)).processed == 0


async def test_busy_writer_defers_worker_before_extraction(tmp_path: Path) -> None:
    env = await _env(tmp_path, max_attempts=1)
    sha = await _push(env, "input")
    client = FakeClient()

    async with manage.write_lock(env.knowledge):
        with anyio.fail_after(2):
            report = await run_round(client, env.config)

    assert (report.processed, report.failed) == (0, 0)
    assert client.calls == 0
    assert (await env.queue.pending_bytes()) > 0
    row = _row(env, sha)
    assert (row.status, row.attempts) == ("queued", 0), "临时不可用不消耗失败次数"


async def test_round_passes_configured_max_tokens(tmp_path: Path) -> None:
    """输出预算必须从 WorkerConfig 透传到 LLM 调用（MEMHUB_LLM_MAX_TOKENS 的落点）。"""
    env = await _env(tmp_path, max_tokens=12345)
    await _push(env, _session_line(EVIDENCE), path="sessions/a.jsonl")
    client = FakeClient()

    assert (await run_round(client, env.config)).processed == 1
    assert client.max_tokens_seen == [12345]


async def test_round_writes_into_the_project_chosen_by_the_client(tmp_path: Path) -> None:
    """桌面端按目录选了知识库，worker 必须写进 knowledge/<project>/。"""
    env = await _env(tmp_path)
    await _push(env, EVIDENCE, project="sdp-tag")

    assert (await run_round(FakeClient(), env.config)).processed == 1
    files = _knowledge_files(env)
    assert len(files) == 1
    assert Path(files[0]).relative_to(env.knowledge).parts[0] == "sdp-tag"


@pytest.mark.parametrize("project", ["auto", "../../etc"])
async def test_legacy_ambiguous_or_invalid_target_is_quarantined(
    tmp_path: Path, project: str
) -> None:
    env = await _env(tmp_path)
    sha = await _push(env, _session_line("private session material"))
    _retarget(env, sha, project=project)
    client = FakeClient()

    report = await run_round(client, env.config)

    assert client.calls == 0
    assert (report.processed, report.created) == (0, 0)
    assert _row(env, sha, project).status == "pending_review"
    assert not list((env.knowledge / "cc-sessions").iterdir())
    assert report.errors == ["project_required"]


async def test_unknown_device_is_not_authorized_by_explicit_project(tmp_path: Path) -> None:
    env = await _env(tmp_path)
    sha = await _push(env, "private session material", device_id="unknown")
    client = FakeClient()

    report = await run_round(client, env.config)

    assert report.processed == 0
    assert client.calls == 0
    assert _row(env, sha).status == "pending_review"
    assert report.errors == ["device_not_registered"]


async def test_console_is_independent_of_device_registry(tmp_path: Path) -> None:
    env = await _env(tmp_path, is_registered=None)
    await _push(
        env,
        EVIDENCE,
        project="cc-sessions",
        device_id="kb-console",
        source_id="cc-sessions",
        source_type="docs",
        path="note.md",
    )
    # Wiki/docs 抽取有意不需要会话证据。
    reply = json.loads(LLM_REPLY)
    del reply["nodes"][0]["evidence"]
    client = FakeClient(reply=json.dumps(reply))

    report = await run_round(client, env.config)

    assert (report.processed, report.created, client.calls) == (1, 1, 1)


@pytest.mark.parametrize("producer", ["rogue", None, {}])
async def test_present_unknown_producer_is_quarantined(tmp_path: Path, producer: object) -> None:
    env = await _env(tmp_path)
    sha = await _push(env, EVIDENCE, project="demo")
    _retarget(env, sha, old="demo", producer=producer)
    client = FakeClient()

    report = await run_round(client, env.config)

    assert (report.processed, report.quarantined, client.calls) == (0, 1, 0)
    assert report.errors == ["producer_unrecognized"]


async def test_console_identity_requires_source_equal_to_project(tmp_path: Path) -> None:
    env = await _env(tmp_path)
    sha = await _push(
        env,
        EVIDENCE,
        project="demo",
        device_id="kb-console",
        source_id="demo",
        source_type="docs",
        path="note.md",
    )
    _retarget(env, sha, old="demo", source_id="cc-sessions")
    client = FakeClient()

    report = await run_round(client, env.config)

    assert (report.processed, report.quarantined, client.calls) == (0, 1, 0)
    assert report.errors == ["console_identity_invalid"]


async def test_invalid_queue_sha_is_permanent_denial(tmp_path: Path) -> None:
    env = await _env(tmp_path)
    sha = await _push(env, EVIDENCE)
    _retarget(env, sha, sha256="not-a-sha")
    client = FakeClient()

    report = await run_round(client, env.config)

    assert (report.processed, report.quarantined, client.calls) == (0, 1, 0)
    assert report.errors == ["queue_identity_invalid"]


async def test_content_store_failure_defers_without_spending_attempts(tmp_path: Path) -> None:
    env = await _env(tmp_path)
    sha = await _push(env, EVIDENCE)
    target = env.content._path("cc-sessions", sha)
    await AsyncPath(target).write_text("{not json", encoding="utf-8")
    client = FakeClient()

    report = await run_round(client, env.config)

    assert (report.processed, report.failed, client.calls) == (0, 0, 0)
    row = _row(env, sha)
    assert (row.status, row.attempts) == ("queued", 0)


async def test_missing_content_is_quarantined_not_retried(tmp_path: Path) -> None:
    env = await _env(tmp_path)
    sha = await _push(env, EVIDENCE)
    await AsyncPath(env.content._path("cc-sessions", sha)).unlink()
    client = FakeClient()

    report = await run_round(client, env.config)

    assert (report.quarantined, client.calls) == (1, 0)
    assert report.errors == ["content_missing"]
    assert _row(env, sha).status == "pending_review"


@pytest.mark.parametrize("problem", ["registry", "registration"])
async def test_registry_unavailability_keeps_task_queued(tmp_path: Path, problem: str) -> None:
    async def unavailable(_device: str) -> bool:
        raise RuntimeError("private DB error")

    env = await _env(tmp_path, max_attempts=1)
    sha = await _push(env, EVIDENCE)
    if problem == "registration":
        env.config.is_registered = unavailable
    else:
        (env.knowledge / ".kbs.json").write_text("broken JSON", encoding="utf-8")
    client = FakeClient()

    assert await run_round(client, env.config) == RoundReport()
    assert client.calls == 0
    row = _row(env, sha)
    assert (row.status, row.attempts) == ("queued", 0)


async def test_registered_directory_without_catalog_entry_is_denied(tmp_path: Path) -> None:
    env = await _env(tmp_path)
    sha = await _push(env, EVIDENCE, project="orphan")
    orphan = env.knowledge / "orphan"
    orphan.mkdir()
    client = FakeClient()

    report = await run_round(client, env.config)

    assert (report.processed, report.failed, report.quarantined, client.calls) == (0, 0, 1, 0)
    assert report.errors == ["target_inactive"]
    assert not list(orphan.iterdir())
    assert _row(env, sha, "orphan").status == "pending_review"


async def test_target_archived_during_model_call_is_quarantined_without_merge(
    tmp_path: Path,
) -> None:
    env = await _env(tmp_path)
    sha = await _push(env, EVIDENCE)

    class ArchivingClient(FakeClient):
        async def complete(self, prompt: str, *, model: str, max_tokens: int = 32000) -> str:
            await catalog.delete_kb(KnowledgeStore(env.knowledge), "cc-sessions")
            return await super().complete(prompt, model=model, max_tokens=max_tokens)

    client = ArchivingClient()
    report = await run_round(client, env.config)

    assert (report.processed, report.failed, report.quarantined, client.calls) == (0, 0, 1, 1)
    assert report.errors == ["target_inactive"]
    # 库已归档：既不能写进新节点，也不能把目录重建回来。
    assert not await AsyncPath(env.knowledge / "cc-sessions").exists()
    assert _row(env, sha).status == "pending_review"


async def test_unparseable_jsonl_and_unevidenced_output_do_not_merge(tmp_path: Path) -> None:
    env = await _env(tmp_path, limit=2)
    await _push(env, '"tail of an event', path="broken.JSONL")
    await _push(env, EVIDENCE, path="sessions/a.txt")
    reply = json.loads(LLM_REPLY)
    del reply["nodes"][0]["evidence"]
    client = FakeClient(reply=json.dumps(reply))

    report = await run_round(client, env.config)

    assert (report.processed, report.created, client.calls) == (2, 0, 1)
    assert not list((env.knowledge / "cc-sessions").iterdir())


async def test_round_keeps_failed_task_queued_for_retry(tmp_path: Path) -> None:
    env = await _env(tmp_path)
    sha = await _push(env, "hello")
    report = await run_round(FakeClient(error=LLMError("boom")), env.config)

    assert (report.processed, report.failed) == (0, 1)
    assert len(report.errors) == 1
    row = _row(env, sha)
    assert (row.status, row.attempts) == ("queued", 1), "失败留在队列，下一轮重试"


async def test_forever_respects_window_and_backs_off(tmp_path: Path) -> None:
    env = await _env(tmp_path, window="21:00-02:00", interval=60.0)
    await _push(env, "hello")
    sleeps: list[float] = []
    # 本地时间 12:00 在窗口外。
    outside = datetime(2026, 11, 19, 4, 0, tzinfo=UTC).astimezone()
    report = await run_round(FakeClient(error=LLMError("boom")), env.config)
    assert report.failed == 1
    code = await run_forever(
        FakeClient(error=LLMError("boom")),
        env.config,
        now=lambda: outside,
        sleep=_sleeper(sleeps),
        max_rounds=1,
    )
    assert code == 0
    assert sleeps == [60.0], "窗口外只睡 interval，不去碰 LLM"


async def test_probe_endpoint_rejects_unreachable_host() -> None:
    with pytest.raises(LLMError, match="不可达"):
        await probe_endpoint("http://127.0.0.1:1", timeout=0.2)


async def test_empty_round_reports_nothing(tmp_path: Path) -> None:
    env = await _env(tmp_path)
    report = await run_round(FakeClient(), env.config)
    assert report == RoundReport()


async def test_backoff_grows_on_repeated_failure(tmp_path: Path) -> None:
    env = await _env(tmp_path, window="", interval=60.0)
    await _push(env, "hello")
    sleeps: list[float] = []
    inside = datetime.now(UTC).astimezone() + timedelta(seconds=1)
    code = await run_forever(
        FakeClient(error=LLMError("boom")),
        env.config,
        now=lambda: inside,
        sleep=_sleeper(sleeps),
        max_rounds=3,
    )
    assert code == 1
    assert sleeps == [120.0, 240.0, 480.0]


async def test_repeated_failure_quarantines_task(tmp_path: Path) -> None:
    """连续失败到上限就转 pending_review：毒内容不能每轮都重新付费重试。"""
    env = await _env(tmp_path, max_attempts=3)
    sha = await _push(env, "hello")

    for _ in range(3):
        report = await run_round(FakeClient(error=LLMError("boom")), env.config)
        assert report.failed == 1

    row = _row(env, sha)
    assert (row.status, row.attempts) == ("pending_review", 3)
    assert row.error is not None and "LLMError" in row.error

    # 隔离后不再占用队列，后续轮次也不该再调模型。
    client = FakeClient(error=LLMError("boom"))
    assert await run_round(client, env.config) == RoundReport()
    assert client.calls == 0


async def test_failure_counter_resets_after_success(tmp_path: Path) -> None:
    env = await _env(tmp_path, max_attempts=2)
    sha = await _push(env, _session_line(EVIDENCE), path="sessions/a.jsonl")

    assert (await run_round(FakeClient(error=LLMError("boom")), env.config)).failed == 1
    assert (await run_round(FakeClient(), env.config)).processed == 1
    assert _row(env, sha).status == "processed"


# -- 运行入口接线（规格 §9.2.4）：worker 写 PG 真源，不写 markdown ----------


async def test_round_writes_canonical_into_pg(tmp_path: Path, pg_store: PgKnowledgeStore) -> None:
    await pg_store.register_project("cc-sessions", name="会话提炼")
    env = await _env(tmp_path)
    await _push(env, _session_line(EVIDENCE), path="sessions/a.jsonl")
    config = _pg_config(env, pg_store)

    report = await run_round(FakeClient(), config)

    assert (report.processed, report.failed, report.created) == (1, 0, 1)
    node, body = await pg_store.read("cc-sessions/fact/retry-backoff")
    assert node.tier is Tier.CANONICAL
    assert "指数退避" in body
    assert not (tmp_path / "knowledge").exists(), "不得再落 markdown 真源"


async def test_archived_project_in_pg_is_quarantined(
    tmp_path: Path, pg_store: PgKnowledgeStore
) -> None:
    await pg_store.register_project("cc-sessions", name="会话提炼")
    await pg_store.archive_project("cc-sessions")
    env = await _env(tmp_path)
    sha = await _push(env, _session_line(EVIDENCE), path="sessions/a.jsonl")
    config = _pg_config(env, pg_store)

    report = await run_round(FakeClient(), config)

    assert (report.processed, report.failed, report.quarantined) == (0, 0, 1)
    assert report.errors == ["target_inactive"]
    assert _row(env, sha).status == "pending_review"
    assert not await pg_store.exists("cc-sessions/fact/retry-backoff")


async def test_pending_archive_in_pg_defers_worker_without_quarantine(
    tmp_path: Path, pg_store: PgKnowledgeStore
) -> None:
    """归档事务未完成（`kb_archives.status=pending`）时整轮暂缓，任务留在队列。"""
    await pg_store.register_project("cc-sessions", name="会话提炼")
    async with pg_store.sessions() as session:
        session.add(
            KbArchive(
                archive_id="p" * 32,
                project="cc-sessions",
                status="pending",
                snapshot=b"",
                archived_count=0,
                removed_edges=0,
                created_at=datetime.now(UTC),
            )
        )
        await session.commit()
    env = await _env(tmp_path)
    sha = await _push(env, _session_line(EVIDENCE), path="sessions/a.jsonl")
    config = _pg_config(env, pg_store)
    client = FakeClient()

    report = await run_round(client, config)

    assert report == RoundReport()
    assert client.calls == 0
    assert _row(env, sha).status == "queued"


# ---- 消息 uuid 去重（ADR-0017 / 规格 T1–T6、T9、T10） -------------------

NEW_EVIDENCE = "fork 后新增：提交前必须跑全量测试。"
SECOND_OLD = "第二条旧消息：发布只从 main 出。"


def _event(uuid: str, text: str, *, session_id: str = "session-a") -> str:
    """一行带消息 uuid 的 Claude Code 会话事件；fork 只改 sessionId。"""
    return json.dumps(
        {
            "type": "user",
            "uuid": uuid,
            "sessionId": session_id,
            "message": {"role": "user", "content": text},
        },
        ensure_ascii=False,
    )


def _reply_for(block: str, quote: str) -> str:
    return json.dumps(
        {
            "nodes": [
                {
                    "kind": "fact",
                    "slug": "fork-new-message",
                    "title": "提交前跑全量测试",
                    "body": "fork 之后补充的新知识。",
                    "evidence": [{"block": block, "quote": quote}],
                }
            ],
            "edges": [],
        },
        ensure_ascii=False,
    )


class _BrokenState:
    async def seen_messages(self, project: str, source_id: str, uuids: list[str]) -> set[str]:
        raise RuntimeError("state down")

    async def mark_messages_seen(self, project: str, source_id: str, uuids: list[str]) -> None:
        raise RuntimeError("state down")


class _MarkFailsState:
    async def seen_messages(self, project: str, source_id: str, uuids: list[str]) -> set[str]:
        return set()

    async def mark_messages_seen(self, project: str, source_id: str, uuids: list[str]) -> None:
        raise RuntimeError("write down")


async def test_fork_copy_is_not_extracted_again(tmp_path: Path) -> None:
    state = MemoryStore()
    parent = "\n".join([_event("m1", EVIDENCE), _event("m2", SECOND_OLD)])
    env = await _env(tmp_path, state=state)
    await _push(env, parent, path="sessions/parent.jsonl")
    assert (await run_round(FakeClient(), env.config)).created == 1

    fork = "\n".join(
        [
            _event("m1", EVIDENCE, session_id="fork"),
            _event("m2", SECOND_OLD, session_id="fork"),
            _event("m3", NEW_EVIDENCE, session_id="fork"),
        ]
    )
    await _push(env, fork, path="sessions/fork.jsonl")
    fork_client = FakeClient(reply=_reply_for("b0003", NEW_EVIDENCE))
    report = await run_round(fork_client, env.config)

    assert (report.processed, report.created, report.failed) == (1, 1, 0)
    assert fork_client.calls == 1, "复制过来的旧消息不应再付费抽取"
    assert SECOND_OLD not in fork_client.prompts[0]
    assert NEW_EVIDENCE in fork_client.prompts[0]


async def test_fully_duplicate_fork_file_skips_the_model(tmp_path: Path) -> None:
    state = MemoryStore()
    parent = "\n".join([_event("m1", EVIDENCE), _event("m2", SECOND_OLD)])
    env = await _env(tmp_path, state=state)
    await _push(env, parent, path="sessions/parent.jsonl")
    assert (await run_round(FakeClient(), env.config)).created == 1

    fork = "\n".join(
        [
            _event("m1", EVIDENCE, session_id="fork"),
            _event("m2", SECOND_OLD, session_id="fork"),
        ]
    )
    await _push(env, fork, path="sessions/fork.jsonl")
    client = FakeClient()
    report = await run_round(client, env.config)

    assert client.calls == 0
    assert (report.processed, report.deduped) == (1, 1)
    statuses = sorted(row.status for row in env.queue.rows.values())
    assert statuses == ["processed", "processed"]


async def test_failed_extraction_does_not_mark_messages_seen(tmp_path: Path) -> None:
    state = MemoryStore()
    env = await _env(tmp_path, state=state)
    await _push(env, _event("m1", EVIDENCE), path="sessions/a.jsonl")

    failed = await run_round(FakeClient(error=LLMError("boom")), env.config)
    assert failed.failed == 1
    assert await state.seen_messages("cc-sessions", "cc-sessions", ["m1"]) == set()

    retry = FakeClient()
    assert (await run_round(retry, env.config)).processed == 1
    assert retry.calls == 1
    assert await state.seen_messages("cc-sessions", "cc-sessions", ["m1"]) == {"m1"}


async def test_same_uuid_in_another_project_is_extracted(tmp_path: Path) -> None:
    state = MemoryStore()
    env = await _env(tmp_path, state=state, limit=2)
    await _push(env, _event("m1", EVIDENCE), path="sessions/a.jsonl", project="cc-sessions")
    await _push(
        env,
        _event("m1", EVIDENCE, session_id="other"),
        path="sessions/b.jsonl",
        project="sdp-tag",
    )
    client = FakeClient()

    report = await run_round(client, env.config)

    assert (report.processed, report.created, client.calls) == (2, 2, 2)


async def test_dedupe_is_off_without_a_state_store(tmp_path: Path) -> None:
    """dev / 管理台上传没有运行态 DSN 时保持原行为。"""
    parent = _event("m1", EVIDENCE)
    env = await _env(tmp_path, state=None)
    await _push(env, parent, path="sessions/parent.jsonl")
    assert (await run_round(FakeClient(), env.config)).created == 1

    await _push(
        env,
        _event("m1", EVIDENCE, session_id="fork"),
        path="sessions/fork.jsonl",
    )
    client = FakeClient()

    report = await run_round(client, env.config)
    # 断言「没有被去重跳过」；重复内容 merge 后可能是更新而非新建，不在这里钉死。
    assert (report.processed, report.deduped, client.calls) == (1, 0, 1)


async def test_message_index_unavailable_defers_without_spending_llm(tmp_path: Path) -> None:
    env = await _env(tmp_path, state=_BrokenState())
    sha = await _push(env, _event("m1", EVIDENCE), path="sessions/a.jsonl")
    client = FakeClient()

    report = await run_round(client, env.config)

    assert (report.processed, report.failed, report.quarantined) == (0, 0, 0)
    assert client.calls == 0
    row = _row(env, sha)
    assert (row.status, row.attempts) == ("queued", 0)


async def test_mark_failure_after_merge_keeps_file_complete(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """merge 已成功；记账失败只记 ERROR，不能让同一文件再次付费抽取。"""
    env = await _env(tmp_path, state=_MarkFailsState())
    sha = await _push(env, _event("m1", EVIDENCE), path="sessions/a.jsonl")
    client = FakeClient()

    report = await run_round(client, env.config)

    assert (report.processed, report.failed, report.created) == (1, 0, 1)
    assert _row(env, sha).status == "processed"
    assert "mark-seen failed" in capsys.readouterr().err


# -- 会话抽取注入与审计（规格 §7） ------------------------------------------


def _memory(disabled: frozenset[str] = frozenset()) -> MemoryContext:
    return MemoryContext(
        version=9,
        entries=(
            {
                "slug": "retry-backoff",
                "title": "重试退避",
                "conclusion": "网络重试需要指数退避。",
                "boundary": "幂等操作",
                "invalidation": "",
                "confidence": 0.9,
            },
        ),
        settings=MemorySettings(disabled_projects=disabled),
    )


async def _session_audits(pg_store: PgKnowledgeStore) -> list[KbWriteAudit]:
    async with pg_store.sessions() as session:
        rows = await session.scalars(
            select(KbWriteAudit)
            .where(KbWriteAudit.action == "extract_session")
            .order_by(KbWriteAudit.id)
        )
        return list(rows)


async def test_session_round_records_audit_with_frozen_snapshot(
    tmp_path: Path, pg_store: PgKnowledgeStore
) -> None:
    await pg_store.register_project("cc-sessions", name="会话提炼")
    env = await _env(tmp_path)
    await _push(env, _session_line(EVIDENCE), path="sessions/a.jsonl")
    config = _pg_config(env, pg_store, memory=_memory())

    report = await run_round(FakeClient(), config)

    assert report.processed == 1
    [audit] = await _session_audits(pg_store)
    assert audit.actor == "worker"
    assert audit.project == "cc-sessions"
    assert audit.node_id is None
    assert audit.result == "ok"
    assert audit.memory_snapshot == 9


async def test_empty_session_extraction_is_audited_as_empty(
    tmp_path: Path, pg_store: PgKnowledgeStore
) -> None:
    await pg_store.register_project("cc-sessions", name="会话提炼")
    env = await _env(tmp_path)
    await _push(env, _session_line(EVIDENCE), path="sessions/a.jsonl")
    config = _pg_config(env, pg_store, memory=_memory())
    empty = json.dumps({"nodes": [], "edges": []})

    report = await run_round(FakeClient(reply=empty), config)

    assert (report.processed, report.created) == (1, 0)
    [audit] = await _session_audits(pg_store)
    assert audit.result == "empty"
    assert audit.memory_snapshot == 9


async def test_disabled_project_injects_nothing_and_audits_null(
    tmp_path: Path, pg_store: PgKnowledgeStore
) -> None:
    await pg_store.register_project("cc-sessions", name="会话提炼")
    env = await _env(tmp_path)
    await _push(env, _session_line(EVIDENCE), path="sessions/a.jsonl")
    config = _pg_config(env, pg_store, memory=_memory(frozenset({"cc-sessions"})))
    client = FakeClient()

    await run_round(client, config)

    assert client.calls == 1
    [audit] = await _session_audits(pg_store)
    assert audit.memory_snapshot is None
    assert audit.result == "ok"


def test_adaptive_interval_scales_with_backlog() -> None:
    from memhub.worker.daemon import adaptive_interval

    # 空积压回到 base 慢轮询；积压超过阈值用 fast；≤阈值时积压越少间隔越长。
    assert adaptive_interval(0, base=300.0) == 300.0
    assert adaptive_interval(51, base=300.0) == 60.0
    assert adaptive_interval(500, base=300.0) == 60.0
    assert adaptive_interval(50, base=300.0) == 60.0
    assert adaptive_interval(25, base=300.0) == 120.0
    assert adaptive_interval(10, base=300.0) == 300.0
    assert adaptive_interval(51, base=30.0) == 30.0, "base 比 fast 还短时不得反向变慢"


async def test_run_forever_sleeps_shorter_when_backlog_remains(tmp_path: Path) -> None:
    class BacklogQueue(MemoryQueue):
        async def claim(self, *, limit: int = 20, lease: timedelta = DEFAULT_LEASE):
            return []

        async def backlog(self) -> int:
            return 51

    env = await _env(tmp_path)
    env.config.queue = BacklogQueue()
    env.config.interval = 300.0

    sleeps: list[float] = []
    await run_forever(
        FakeClient(),
        env.config,
        now=lambda: datetime.now(UTC),
        sleep=_sleeper(sleeps),
        max_rounds=1,
    )

    assert sleeps == [60.0], "本轮无产出但队列仍有积压时用短轮询间隔（60s），而不是 base"


async def test_run_forever_returns_to_base_interval_when_idle(tmp_path: Path) -> None:
    env = await _env(tmp_path)
    env.config.interval = 300.0

    sleeps: list[float] = []
    await run_forever(
        FakeClient(),
        env.config,
        now=lambda: datetime.now(UTC),
        sleep=_sleeper(sleeps),
        max_rounds=1,
    )

    assert sleeps == [300.0]
