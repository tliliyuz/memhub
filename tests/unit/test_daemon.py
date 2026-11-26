"""worker 守护进程：窗口门控、待处理扫描、单轮提炼、退避退出码（异步 IO）。"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta, timezone
from datetime import time as dtime
from pathlib import Path

import anyio
import pytest
from anyio import Path as AsyncPath
from sqlalchemy.ext.asyncio import AsyncEngine

from memhub.contract import BatchFile, IngestRequest, Tier
from memhub.ingest.store import MemoryStore
from memhub.kb import catalog, manage
from memhub.kb.models import Base, KbArchive
from memhub.kb.pgstore import PgKnowledgeStore
from memhub.kb.session import create_sessionmaker
from memhub.kb.store import KnowledgeStore
from memhub.kb.target_access import TargetRegistry
from memhub.queue.rawstore import batch_dir, save_batch
from memhub.worker.daemon import (
    RoundReport,
    WorkerConfig,
    in_window,
    iter_pending,
    parse_window,
    parse_window_tz,
    probe_endpoint,
    prune_processed_raw,
    purge_pending_review,
    run_forever,
    run_round,
)
from memhub.worker.llm import LLMError

NOW = datetime(2026, 11, 19, 2, 0, tzinfo=UTC)
EVIDENCE = "网络重试需要指数退避。"

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


async def _config(tmp_path: Path, **kwargs: object) -> WorkerConfig:
    knowledge_dir = tmp_path / "knowledge"
    projects = ["cc-sessions", "sdp-tag", "archived", "active", "demo"]
    for project in projects:
        await catalog.create_kb(KnowledgeStore(knowledge_dir), kb_id=project)
    state = MemoryStore()
    await state.register_device("dev-1")
    kwargs.setdefault("is_registered", state.is_registered)
    kwargs.setdefault("target_registry", TargetRegistry(KnowledgeStore(knowledge_dir)))
    return WorkerConfig(
        data_dir=tmp_path,
        store=KnowledgeStore(knowledge_dir),
        model="test-model",
        **kwargs,  # type: ignore[arg-type]
    )


async def _push(
    tmp_path: Path,
    content: str,
    *,
    path: str = "sessions/a.txt",
    project: str = "cc-sessions",
    device_id: str = "dev-1",
    source_id: str = "cc-sessions",
    source_type: str = "sessions",
    legacy: bool = False,
) -> Path:
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
                to_offset=len(content),
                mtime=NOW,
                sha256=sha,
                content=content,
            )
        ],
    )
    target = batch_dir(tmp_path, device_id, source_id) / sha[:2] / f"{sha}.json"
    if legacy:
        # Seed the former raw envelope directly: the current producer rejects old ambiguous inputs.
        await AsyncPath(target.parent).mkdir(parents=True, exist_ok=True)
        payload = {
            **request.model_dump(
                mode="json",
                include={"batch_id", "device_id", "source_id", "source_type", "project"},
            ),
            **request.files[0].model_dump(mode="json"),
        }
        await AsyncPath(target).write_text(json.dumps(payload), encoding="utf-8")
    else:
        await save_batch(
            tmp_path, request, producer="console" if device_id == "kb-console" else "collector"
        )
    return target


def _knowledge_dir(config: WorkerConfig) -> Path:
    """本文件的 worker 用例跑文件夹具；真源目录只存在于文件实现。"""
    assert isinstance(config.store, KnowledgeStore)
    return config.store.root


@pytest.fixture
async def pg_store(kb_engine: AsyncEngine) -> PgKnowledgeStore:
    async with kb_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return PgKnowledgeStore(create_sessionmaker(kb_engine))


def _pg_config(tmp_path: Path, store: PgKnowledgeStore, **kwargs: object) -> WorkerConfig:
    kwargs.setdefault("is_registered", _always_registered)
    kwargs.setdefault("target_registry", TargetRegistry(store))
    return WorkerConfig(data_dir=tmp_path, store=store, model="test-model", **kwargs)  # type: ignore[arg-type]


async def _always_registered(_device: str) -> bool:
    return True


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
    await _push(tmp_path, "hello")
    beijing = timezone(timedelta(hours=8))
    config = await _config(tmp_path, window="21:00-02:00", window_tz=beijing, interval=60.0)

    sleeps: list[float] = []
    inside = datetime(2026, 11, 19, 13, 30, tzinfo=UTC)
    assert (
        await run_forever(
            FakeClient(), config, now=lambda: inside, sleep=_sleeper(sleeps), max_rounds=1
        )
        == 0
    )
    assert sleeps == [], "窗口内必须直接处理，不能睡"

    outside = datetime(2026, 11, 19, 10, 0, tzinfo=UTC)
    assert (
        await run_forever(
            FakeClient(), config, now=lambda: outside, sleep=_sleeper(sleeps), max_rounds=1
        )
        == 0
    )
    assert sleeps == [60.0], "窗口外只睡 interval，不去碰 LLM"


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
    await _push(tmp_path, _session_line(EVIDENCE), path="sessions/a.jsonl")
    config = await _config(tmp_path)
    client = FakeClient()
    report = await run_round(client, config)

    assert (report.processed, report.failed, report.created) == (1, 0, 1)
    assert client.calls == 1
    knowledge_files = [item async for item in AsyncPath(_knowledge_dir(config)).rglob("*.md")]
    assert len(knowledge_files) == 1
    assert await iter_pending(config.raw_root, config.processed_root) == []
    processed = [item async for item in AsyncPath(config.processed_root).rglob("*.json")]
    assert len(processed) == 1


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
    await _push(tmp_path, line, path="sessions/a.jsonl")
    config = await _config(tmp_path)
    client = FakeClient()

    report = await run_round(client, config)

    assert report.processed == 1
    assert client.calls == 0, "没有真实对话就不该调用模型"


async def test_archived_inputs_quarantined_without_starving_active_projects(tmp_path: Path) -> None:
    await _push(tmp_path, "blocked", project="archived")
    config = await _config(tmp_path, limit=1, max_attempts=2)
    [blocked] = await iter_pending(config.raw_root, config.processed_root)
    original = await AsyncPath(blocked).read_bytes()
    attempts = {str(blocked.relative_to(config.raw_root)): 1}
    await AsyncPath(config.failures_path.parent).mkdir(parents=True, exist_ok=True)
    await AsyncPath(config.failures_path).write_text(json.dumps(attempts), encoding="utf-8")
    await _set_mtime(blocked, 1)
    await _push(tmp_path, EVIDENCE, project="active")
    marker = AsyncPath(_knowledge_dir(config) / "_kb_archives" / "blocked" / "archived")
    await marker.parent.mkdir(parents=True)
    await marker.touch()
    client = FakeClient()

    report = await run_round(client, config)

    assert (report.processed, report.failed, report.created) == (1, 0, 1)
    assert client.calls == 1
    assert report.quarantined == 1
    assert report.errors == ["target_inactive"]
    assert await iter_pending(config.raw_root, config.processed_root) == []
    assert (config.pending_root / blocked.relative_to(config.raw_root)).read_bytes() == original
    assert json.loads(config.failures_path.read_text(encoding="utf-8")) == {}
    assert not list((_knowledge_dir(config) / "archived").iterdir())


@pytest.mark.parametrize(
    "archive_state", ["_kb_archives/pending.json", "_kb_archives/blocked/demo"]
)
async def test_archive_started_during_extraction_blocks_worker_merge(
    tmp_path: Path, archive_state: str
) -> None:
    raw = await _push(tmp_path, EVIDENCE, project="demo")
    original = raw.read_bytes()
    config = await _config(tmp_path, max_attempts=1)
    marker = AsyncPath(_knowledge_dir(config) / archive_state)

    class ArchivingClient(FakeClient):
        async def complete(self, prompt: str, *, model: str, max_tokens: int = 32000) -> str:
            async with manage.write_lock(_knowledge_dir(config)):
                await marker.parent.mkdir(parents=True)
                await marker.touch()
            return await super().complete(prompt, model=model, max_tokens=max_tokens)

    client = ArchivingClient()
    report = await run_round(client, config)

    assert client.calls == 1
    assert (report.processed, report.failed, report.created) == (0, 0, 0)
    assert not list((_knowledge_dir(config) / "demo").iterdir())
    assert not config.failures_path.exists()
    if archive_state.endswith("pending.json"):
        assert not config.pending_root.exists()
        assert raw.read_bytes() == original
        assert report.quarantined == 0
    else:
        assert not raw.exists()
        assert (config.pending_root / raw.relative_to(config.raw_root)).read_bytes() == original
        assert report.errors == ["target_inactive"]
    # 已知日志或标记存在时不应再次付费抽取。
    assert (await run_round(client, config)).processed == 0
    assert client.calls == 1


async def test_busy_writer_defers_worker_before_extraction(tmp_path: Path) -> None:
    await _push(tmp_path, "input")
    config = await _config(tmp_path, max_attempts=1)
    client = FakeClient()

    async with manage.write_lock(_knowledge_dir(config)):
        with anyio.fail_after(2):
            report = await run_round(client, config)

    assert (report.processed, report.failed) == (0, 0)
    assert client.calls == 0
    assert len(await iter_pending(config.raw_root, config.processed_root)) == 1
    assert not await AsyncPath(config.failures_path).exists()


async def test_round_passes_configured_max_tokens(tmp_path: Path) -> None:
    """输出预算必须从 WorkerConfig 透传到 LLM 调用（MEMHUB_LLM_MAX_TOKENS 的落点）。"""
    await _push(tmp_path, _session_line(EVIDENCE), path="sessions/a.jsonl")
    config = await _config(tmp_path, max_tokens=12345)
    client = FakeClient()

    assert (await run_round(client, config)).processed == 1
    assert client.max_tokens_seen == [12345]


async def test_round_writes_into_the_project_chosen_by_the_client(tmp_path: Path) -> None:
    """桌面端按目录选了知识库，worker 必须写进 knowledge/<project>/。"""
    await _push(tmp_path, EVIDENCE, project="sdp-tag", legacy=True)
    config = await _config(tmp_path)

    assert (await run_round(FakeClient(), config)).processed == 1
    files = [item async for item in AsyncPath(_knowledge_dir(config)).rglob("*.md")]
    assert len(files) == 1
    parts = Path(files[0]).relative_to(_knowledge_dir(config)).parts
    assert parts[0] == "sdp-tag", "选了库就不能再写到 source_id 目录下"


@pytest.mark.parametrize("project", ["auto", "../../etc"])
async def test_legacy_ambiguous_or_invalid_target_is_quarantined(
    tmp_path: Path, project: str
) -> None:
    await _push(tmp_path, _session_line("private session material"), project=project, legacy=True)
    config = await _config(tmp_path)
    [raw] = await iter_pending(config.raw_root, config.processed_root)
    original = raw.read_bytes()
    client = FakeClient()

    report = await run_round(client, config)

    assert client.calls == 0
    assert (report.processed, report.created) == (0, 0)
    assert not raw.exists()
    assert (config.pending_root / raw.relative_to(config.raw_root)).read_bytes() == original
    assert not config.processed_root.exists()
    assert not list((_knowledge_dir(config) / "cc-sessions").iterdir())
    assert report.errors == ["project_required"]
    assert not config.failures_path.exists()


async def test_unapproved_target_even_with_no_session_text_is_not_processed(tmp_path: Path) -> None:
    await _push(tmp_path, "", project="auto", legacy=True)
    config = await _config(tmp_path)
    client = FakeClient()

    assert (await run_round(client, config)).processed == 0
    assert client.calls == 0
    assert len(list(config.pending_root.rglob("*.json"))) == 1
    assert not config.processed_root.exists()


async def test_legacy_unknown_device_is_not_authorized_by_explicit_project(tmp_path: Path) -> None:
    await _push(tmp_path, "private session material", device_id="unknown", legacy=True)
    config = await _config(tmp_path)
    client = FakeClient()

    assert (await run_round(client, config)).processed == 0
    assert client.calls == 0
    assert len(list(config.pending_root.rglob("*.json"))) == 1
    assert not (_knowledge_dir(config) / "unapproved").exists()


@pytest.mark.parametrize("legacy", [False, True])
async def test_console_is_independent_of_device_registry(tmp_path: Path, legacy: bool) -> None:
    await _push(tmp_path, EVIDENCE, device_id="kb-console", source_type="docs", legacy=legacy)
    config = await _config(tmp_path, is_registered=None)
    # Wiki extraction is deliberately unchanged and does not require session evidence.
    reply = json.loads(LLM_REPLY)
    del reply["nodes"][0]["evidence"]
    client = FakeClient(reply=json.dumps(reply))

    report = await run_round(client, config)

    assert (report.processed, report.created, client.calls) == (1, 1, 1)


@pytest.mark.parametrize("marker", ["rogue", None, {}])
async def test_present_unknown_producer_is_not_legacy(tmp_path: Path, marker: object) -> None:
    raw = await _push(tmp_path, EVIDENCE, device_id="kb-console", source_type="docs")
    payload = json.loads(raw.read_text(encoding="utf-8"))
    payload["producer"] = marker
    raw.write_text(json.dumps(payload), encoding="utf-8")
    config = await _config(tmp_path)
    client = FakeClient()

    report = await run_round(client, config)

    assert (report.processed, report.quarantined, client.calls) == (0, 1, 0)
    assert report.errors == ["producer_unrecognized"]


async def test_legacy_console_identity_requires_source_equal_to_project(tmp_path: Path) -> None:
    await _push(
        tmp_path, EVIDENCE, project="demo", device_id="kb-console", source_type="docs", legacy=True
    )
    config = await _config(tmp_path)
    client = FakeClient()

    report = await run_round(client, config)

    assert (report.processed, report.quarantined, client.calls) == (0, 1, 0)
    assert report.errors == ["console_identity_invalid"]


async def test_queue_path_identity_mismatch_is_permanent_denial(tmp_path: Path) -> None:
    raw = await _push(tmp_path, EVIDENCE)
    payload = json.loads(raw.read_text(encoding="utf-8"))
    payload["source_id"] = "different-source"
    raw.write_text(json.dumps(payload), encoding="utf-8")
    config = await _config(tmp_path)
    client = FakeClient()

    report = await run_round(client, config)

    assert (report.processed, report.quarantined, client.calls) == (0, 1, 0)
    assert report.errors == ["queue_identity_mismatch"]


@pytest.mark.parametrize("invalid_bytes", [b'{"content": "private', b"\xffprivate"])
async def test_invalid_raw_encoding_or_json_is_quarantined_once(
    tmp_path: Path, invalid_bytes: bytes
) -> None:
    raw = await _push(tmp_path, EVIDENCE)
    raw.write_bytes(invalid_bytes)
    config = await _config(tmp_path)
    client = FakeClient()

    report = await run_round(client, config)

    assert (report.processed, report.failed, report.quarantined, client.calls) == (0, 0, 1, 0)
    assert report.errors == ["queue_payload_invalid"]
    assert not raw.exists()
    assert (config.pending_root / raw.relative_to(config.raw_root)).read_bytes() == invalid_bytes
    assert not config.failures_path.exists()


@pytest.mark.parametrize("problem", ["registry", "registration"])
async def test_registry_unavailability_preserves_raw_and_existing_failures(
    tmp_path: Path, problem: str
) -> None:
    async def unavailable(_device: str) -> bool:
        raise RuntimeError("private DB error")

    raw = await _push(tmp_path, EVIDENCE)
    original = raw.read_bytes()
    kwargs = {"is_registered": unavailable} if problem == "registration" else {}
    config = await _config(tmp_path, max_attempts=1, **kwargs)
    if problem == "registry":
        (_knowledge_dir(config) / ".kbs.json").write_text("broken JSON", encoding="utf-8")
    config.failures_path.parent.mkdir()
    failures = json.dumps({str(raw.relative_to(config.raw_root)): 1}).encode()
    config.failures_path.write_bytes(failures)
    client = FakeClient()

    assert await run_round(client, config) == RoundReport()
    assert client.calls == 0
    assert raw.read_bytes() == original
    assert config.failures_path.read_bytes() == failures
    assert not config.pending_root.exists()
    assert not config.processed_root.exists()


async def test_registered_directory_without_catalog_entry_is_denied(tmp_path: Path) -> None:
    raw = await _push(tmp_path, EVIDENCE, project="orphan")
    config = await _config(tmp_path)
    orphan = _knowledge_dir(config) / "orphan"
    orphan.mkdir()
    client = FakeClient()

    report = await run_round(client, config)

    assert (report.processed, report.failed, report.quarantined, client.calls) == (0, 0, 1, 0)
    assert report.errors == ["target_inactive"]
    assert not raw.exists()
    assert not list(orphan.iterdir())


async def test_target_archived_during_model_call_is_quarantined_without_merge(
    tmp_path: Path,
) -> None:
    raw = await _push(tmp_path, EVIDENCE)
    original = raw.read_bytes()
    config = await _config(tmp_path)

    class ArchivingClient(FakeClient):
        async def complete(self, prompt: str, *, model: str, max_tokens: int = 32000) -> str:
            await catalog.delete_kb(KnowledgeStore(_knowledge_dir(config)), "cc-sessions")
            return await super().complete(prompt, model=model, max_tokens=max_tokens)

    client = ArchivingClient()
    report = await run_round(client, config)

    assert (report.processed, report.failed, report.quarantined, client.calls) == (0, 0, 1, 1)
    assert report.errors == ["target_inactive"]
    # 库已归档：既不能写进新节点，也不能把目录重建回来。
    assert not await AsyncPath(_knowledge_dir(config) / "cc-sessions").exists()
    assert (config.pending_root / raw.relative_to(config.raw_root)).read_bytes() == original
    assert not config.processed_root.exists()
    assert not config.failures_path.exists()


async def test_unparseable_jsonl_and_unevidenced_output_do_not_merge(tmp_path: Path) -> None:
    await _push(tmp_path, '"tail of an event', path="broken.JSONL")
    await _push(tmp_path, EVIDENCE)
    config = await _config(tmp_path)
    reply = json.loads(LLM_REPLY)
    del reply["nodes"][0]["evidence"]
    client = FakeClient(reply=json.dumps(reply))

    report = await run_round(client, config)

    assert (report.processed, report.created, client.calls) == (2, 0, 1)
    assert not list((_knowledge_dir(config) / "cc-sessions").iterdir())


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
    await _push(tmp_path, _session_line(EVIDENCE), path="sessions/a.jsonl")
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


# -- 运行入口接线（规格 §9.2.4）：worker 写 PG 真源，不写 markdown ----------


async def test_round_writes_canonical_into_pg(tmp_path: Path, pg_store: PgKnowledgeStore) -> None:
    await pg_store.register_project("cc-sessions", name="会话提炼")
    await _push(tmp_path, _session_line(EVIDENCE), path="sessions/a.jsonl")
    config = _pg_config(tmp_path, pg_store)

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
    raw = await _push(tmp_path, _session_line(EVIDENCE), path="sessions/a.jsonl")
    original = raw.read_bytes()
    config = _pg_config(tmp_path, pg_store)

    report = await run_round(FakeClient(), config)

    assert (report.processed, report.failed, report.quarantined) == (0, 0, 1)
    assert report.errors == ["target_inactive"]
    assert (config.pending_root / raw.relative_to(config.raw_root)).read_bytes() == original
    assert not await pg_store.exists("cc-sessions/fact/retry-backoff")


async def test_pending_archive_in_pg_defers_worker_without_quarantine(
    tmp_path: Path, pg_store: PgKnowledgeStore
) -> None:
    """归档事务未完成（`kb_archives.status=pending`）时整轮暂缓，原始文件保留。"""
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
    raw = await _push(tmp_path, _session_line(EVIDENCE), path="sessions/a.jsonl")
    config = _pg_config(tmp_path, pg_store)
    client = FakeClient()

    report = await run_round(client, config)

    assert report == RoundReport()
    assert client.calls == 0
    assert raw.exists()
    assert not config.pending_root.exists()
    assert not config.failures_path.exists()


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
    await state.register_device("dev-1")
    parent = "\n".join([_event("m1", EVIDENCE), _event("m2", SECOND_OLD)])
    await _push(tmp_path, parent, path="sessions/parent.jsonl")
    config = await _config(tmp_path, state=state)
    assert (await run_round(FakeClient(), config)).created == 1

    fork = "\n".join(
        [
            _event("m1", EVIDENCE, session_id="fork"),
            _event("m2", SECOND_OLD, session_id="fork"),
            _event("m3", NEW_EVIDENCE, session_id="fork"),
        ]
    )
    await _push(tmp_path, fork, path="sessions/fork.jsonl")
    fork_client = FakeClient(reply=_reply_for("b0003", NEW_EVIDENCE))
    report = await run_round(fork_client, config)

    assert (report.processed, report.created, report.failed) == (1, 1, 0)
    assert fork_client.calls == 1, "复制过来的旧消息不应再付费抽取"
    assert SECOND_OLD not in fork_client.prompts[0]
    assert NEW_EVIDENCE in fork_client.prompts[0]


async def test_fully_duplicate_fork_file_skips_the_model(tmp_path: Path) -> None:
    state = MemoryStore()
    await state.register_device("dev-1")
    parent = "\n".join([_event("m1", EVIDENCE), _event("m2", SECOND_OLD)])
    await _push(tmp_path, parent, path="sessions/parent.jsonl")
    config = await _config(tmp_path, state=state)
    assert (await run_round(FakeClient(), config)).created == 1

    fork = "\n".join(
        [
            _event("m1", EVIDENCE, session_id="fork"),
            _event("m2", SECOND_OLD, session_id="fork"),
        ]
    )
    await _push(tmp_path, fork, path="sessions/fork.jsonl")
    client = FakeClient()
    report = await run_round(client, config)

    assert client.calls == 0
    assert (report.processed, report.deduped) == (1, 1)
    processed = [item async for item in AsyncPath(config.processed_root).rglob("*.json")]
    assert len(processed) == 2


async def test_failed_extraction_does_not_mark_messages_seen(tmp_path: Path) -> None:
    state = MemoryStore()
    await state.register_device("dev-1")
    await _push(tmp_path, _event("m1", EVIDENCE), path="sessions/a.jsonl")
    config = await _config(tmp_path, state=state)

    failed = await run_round(FakeClient(error=LLMError("boom")), config)
    assert failed.failed == 1
    assert await state.seen_messages("cc-sessions", "cc-sessions", ["m1"]) == set()

    retry = FakeClient()
    assert (await run_round(retry, config)).processed == 1
    assert retry.calls == 1
    assert await state.seen_messages("cc-sessions", "cc-sessions", ["m1"]) == {"m1"}


async def test_same_uuid_in_another_project_is_extracted(tmp_path: Path) -> None:
    state = MemoryStore()
    await state.register_device("dev-1")
    await _push(tmp_path, _event("m1", EVIDENCE), path="sessions/a.jsonl", project="cc-sessions")
    await _push(
        tmp_path,
        _event("m1", EVIDENCE, session_id="other"),
        path="sessions/b.jsonl",
        project="sdp-tag",
    )
    config = await _config(tmp_path, state=state)
    client = FakeClient()

    report = await run_round(client, config)

    assert (report.processed, report.created, client.calls) == (2, 2, 2)


async def test_dedupe_is_off_without_a_state_store(tmp_path: Path) -> None:
    """dev / 管理台上传没有运行态 DSN 时保持原行为。"""
    parent = _event("m1", EVIDENCE)
    await _push(tmp_path, parent, path="sessions/parent.jsonl")
    config = await _config(tmp_path)
    assert (await run_round(FakeClient(), config)).created == 1

    await _push(
        tmp_path,
        _event("m1", EVIDENCE, session_id="fork"),
        path="sessions/fork.jsonl",
    )
    client = FakeClient()

    report = await run_round(client, config)
    # 断言「没有被去重跳过」；重复内容 merge 后可能是更新而非新建，不在这里钉死。
    assert (report.processed, report.deduped, client.calls) == (1, 0, 1)


async def test_message_index_unavailable_defers_without_spending_llm(tmp_path: Path) -> None:
    await _push(tmp_path, _event("m1", EVIDENCE), path="sessions/a.jsonl")
    config = await _config(tmp_path, state=_BrokenState())
    client = FakeClient()

    report = await run_round(client, config)

    assert (report.processed, report.failed, report.quarantined) == (0, 0, 0)
    assert client.calls == 0
    assert len(await iter_pending(config.raw_root, config.processed_root)) == 1
    assert not config.failures_path.exists()


async def test_mark_failure_after_merge_keeps_file_complete(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """merge 已成功；记账失败只记 ERROR，不能让同一文件再次付费抽取。"""
    await _push(tmp_path, _event("m1", EVIDENCE), path="sessions/a.jsonl")
    config = await _config(tmp_path, state=_MarkFailsState())
    client = FakeClient()

    report = await run_round(client, config)

    assert (report.processed, report.failed, report.created) == (1, 0, 1)
    assert await iter_pending(config.raw_root, config.processed_root) == []
    assert "mark-seen failed" in capsys.readouterr().err
