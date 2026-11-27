"""`memory-aggregate` 与 worker/ingest 记忆接线的 CLI 验收（规格 §5.5、§7、§10）。"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from memhub.cli import main as cli
from memhub.cli.main import _ingest, _memory_aggregate, _memory_client, _worker
from memhub.kb import catalog
from memhub.kb.models import (
    Base,
    KbMemoryEntry,
    KbMemorySnapshot,
    KbNode,
    KbWriteAudit,
)
from memhub.kb.pgstore import PgKnowledgeStore
from memhub.kb.session import RT_DSN_KEY, create_sessionmaker

SESSION_TEXT = "失败后的重试要带指数退避。"
MEMORY_CONCLUSION = "重试必须带指数退避"


@pytest.fixture
async def store(kb_engine: AsyncEngine) -> PgKnowledgeStore:
    async with kb_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return PgKnowledgeStore(create_sessionmaker(kb_engine))


class FakeClient:
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.prompts: list[str] = []
        self.closed = False

    async def complete(self, prompt: str, *, model: str, max_tokens: int | None = None) -> str:
        self.prompts.append(prompt)
        return self.responses.pop(0)

    async def aclose(self) -> None:
        self.closed = True


def _aggregate_args(store: PgKnowledgeStore | None, **overrides: object) -> argparse.Namespace:
    data: dict[str, object] = {
        "since_days": 7,
        "min_sessions": 1,
        "min_projects": 1,
        "max_nodes": 100,
        "dry_run": False,
        "publish": False,
    }
    if store is not None:
        data["store"] = store
    data.update(overrides)
    return argparse.Namespace(**data)


async def _seed_node(
    engine: AsyncEngine,
    *,
    project: str,
    node_id: str,
    session_ref: str,
    title: str = "重试要退避",
    body: str = "失败后的重试要带指数退避。",
) -> None:
    now = datetime.now(UTC)
    maker = create_sessionmaker(engine)
    async with maker() as session:
        session.add(
            KbNode(
                id=node_id,
                project=project,
                kind="fact",
                title=title,
                body=body,
                tier="canonical",
                revision="a" * 16,
                source=[{"type": "session", "ref": session_ref, "device": "test"}],
                created_at=now,
                updated_at=now,
            )
        )
        await session.commit()


def _memory_response(slug: str, node_id: str) -> str:
    return json.dumps(
        {
            "memories": [
                {
                    "slug": slug,
                    "title": "重试要退避",
                    "conclusion": MEMORY_CONCLUSION,
                    "boundary": "适用于可重放操作。",
                    "invalidation": "",
                    "confidence": 0.8,
                    "evidence": [node_id],
                    "contradicts": [],
                }
            ]
        },
        ensure_ascii=False,
    )


async def _count(engine: AsyncEngine, model: type[object]) -> int:
    maker = create_sessionmaker(engine)
    async with maker() as session:
        return int(await session.scalar(select(func.count()).select_from(model)) or 0)


async def test_memory_aggregate_reports_no_nodes_without_calling_model(
    store: PgKnowledgeStore,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeClient([])
    monkeypatch.setattr(cli, "_memory_client", lambda: (client, "memory-model"))

    assert await _memory_aggregate(_aggregate_args(store)) == 0

    assert "没有可聚合节点" in capsys.readouterr().out
    assert client.prompts == []
    assert client.closed is True


async def test_memory_aggregate_requires_kb_dsn(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv(RT_DSN_KEY, raising=False)

    assert await _memory_aggregate(_aggregate_args(None)) == 2
    assert RT_DSN_KEY in capsys.readouterr().err


async def test_memory_aggregate_requires_llm_config(
    store: PgKnowledgeStore,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for key in (
        "MEMHUB_LLM_BASE_URL",
        "ANTHROPIC_BASE_URL",
        "MEMHUB_LLM_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
    ):
        monkeypatch.delenv(key, raising=False)

    assert await _memory_aggregate(_aggregate_args(store)) == 2
    assert "MEMHUB_LLM_BASE_URL" in capsys.readouterr().err


async def test_memory_aggregate_requires_memory_or_extract_model(
    store: PgKnowledgeStore,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("MEMHUB_LLM_BASE_URL", "http://llm.invalid")
    monkeypatch.setenv("MEMHUB_LLM_API_KEY", "test-key")
    monkeypatch.delenv("MEMHUB_LLM_MODEL_MEMORY", raising=False)
    monkeypatch.delenv("MEMHUB_LLM_MODEL_EXTRACT", raising=False)

    assert await _memory_aggregate(_aggregate_args(store)) == 2
    assert "MEMHUB_LLM_MODEL_MEMORY" in capsys.readouterr().err


def test_memory_model_falls_back_to_extract_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEMHUB_LLM_BASE_URL", "http://llm.invalid")
    monkeypatch.setenv("MEMHUB_LLM_API_KEY", "test-key")
    monkeypatch.delenv("MEMHUB_LLM_MODEL_MEMORY", raising=False)
    monkeypatch.setenv("MEMHUB_LLM_MODEL_EXTRACT", "extract-model")

    _client, model = _memory_client()

    assert model == "extract-model"


async def test_memory_aggregate_dry_run_prints_plan_without_writes(
    kb_engine: AsyncEngine,
    store: PgKnowledgeStore,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await catalog.create_kb(store, kb_id="proj-a")
    await _seed_node(
        kb_engine, project="proj-a", node_id="proj-a/fact/retry", session_ref="a.jsonl"
    )
    client = FakeClient([_memory_response("retry-backoff", "proj-a/fact/retry")])
    monkeypatch.setattr(cli, "_memory_client", lambda: (client, "memory-model"))

    assert await _memory_aggregate(_aggregate_args(store, dry_run=True, publish=True)) == 0

    output = capsys.readouterr().out
    assert "[create] retry-backoff" in output
    assert "sessions=1" in output and "projects=1" in output
    assert len(client.prompts) == 1
    assert "proj-a/fact/retry" in client.prompts[0]
    assert await _count(kb_engine, KbMemoryEntry) == 0
    assert await _count(kb_engine, KbMemorySnapshot) == 0


async def test_memory_aggregate_publish_writes_entry_and_snapshot(
    kb_engine: AsyncEngine,
    store: PgKnowledgeStore,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await catalog.create_kb(store, kb_id="proj-a")
    await _seed_node(
        kb_engine, project="proj-a", node_id="proj-a/fact/retry", session_ref="a.jsonl"
    )
    client = FakeClient([_memory_response("retry-backoff", "proj-a/fact/retry")])
    monkeypatch.setattr(cli, "_memory_client", lambda: (client, "memory-model"))

    assert await _memory_aggregate(_aggregate_args(store, publish=True)) == 0

    assert "已发布快照 v1" in capsys.readouterr().out
    maker = create_sessionmaker(kb_engine)
    async with maker() as session:
        entry = await session.get(KbMemoryEntry, "retry-backoff")
        snapshot = await session.scalar(
            select(KbMemorySnapshot).where(KbMemorySnapshot.status == "published")
        )
        audit = await session.scalar(
            select(KbWriteAudit).where(KbWriteAudit.action == "memory_snapshot_publish")
        )
    assert entry is not None and entry.status == "active"
    assert snapshot is not None and snapshot.note == "aggregate since=7d"
    assert audit is not None and audit.memory_snapshot == snapshot.version


def _ingest_args(
    tmp_path: Path, store: PgKnowledgeStore, **overrides: object
) -> argparse.Namespace:
    source = tmp_path / "source"
    source.mkdir(exist_ok=True)
    event = {"type": "user", "message": {"role": "user", "content": SESSION_TEXT}}
    (source / "a.jsonl").write_text(json.dumps(event, ensure_ascii=False) + "\n", encoding="utf-8")
    data: dict[str, object] = {
        "path": str(source),
        "profile": "sessions",
        "project": "demo",
        "limit": 0,
        "max_chars": 12000,
        "max_input_chars": 0,
        "dry_run": False,
        "create_project": False,
        "store": store,
    }
    data.update(overrides)
    return argparse.Namespace(**data)


def _worker_args(tmp_path: Path, store: PgKnowledgeStore) -> argparse.Namespace:
    return argparse.Namespace(
        data_dir=str(tmp_path),
        dry_run=True,
        window="",
        once=True,
        interval=60.0,
        limit=1,
        store=store,
    )


async def test_ingest_rejects_invalid_memory_settings(
    tmp_path: Path,
    store: PgKnowledgeStore,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    await catalog.create_kb(store, kb_id="demo")
    monkeypatch.setenv("MEMHUB_MEMORY_TOP_K", "11")

    def boom() -> tuple[object, str]:
        raise AssertionError("配置非法时不应构造 LLM 客户端")

    monkeypatch.setattr(cli, "_llm_client", boom)

    assert await _ingest(_ingest_args(tmp_path, store)) == 2
    assert "MEMHUB_MEMORY_TOP_K" in capsys.readouterr().err


async def test_worker_rejects_invalid_memory_settings(
    tmp_path: Path,
    store: PgKnowledgeStore,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("MEMHUB_MEMORY_TOP_K", "0")

    assert await _worker(_worker_args(tmp_path, store)) == 2
    assert "MEMHUB_MEMORY_TOP_K" in capsys.readouterr().err


async def _publish_snapshot(store: PgKnowledgeStore, kb_engine: AsyncEngine) -> int:
    now = datetime.now(UTC)
    maker = create_sessionmaker(kb_engine)
    async with maker() as session:
        session.add(
            KbMemoryEntry(
                slug="retry-with-backoff",
                title="重试要退避",
                conclusion=MEMORY_CONCLUSION,
                boundary="适用于可重放操作。",
                invalidation="",
                revision="b" * 16,
                created_at=now,
                updated_at=now,
            )
        )
        await session.commit()
    snapshot = await store.publish_memory_snapshot(actor="test", note="seed")
    return int(snapshot["version"])


async def test_ingest_injects_memory_and_records_audit(
    tmp_path: Path,
    kb_engine: AsyncEngine,
    store: PgKnowledgeStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await catalog.create_kb(store, kb_id="demo")
    version = await _publish_snapshot(store, kb_engine)
    client = FakeClient(
        [
            json.dumps(
                {
                    "nodes": [
                        {
                            "kind": "fact",
                            "title": "重试要退避",
                            "slug": "retry-backoff",
                            "body": SESSION_TEXT,
                            "evidence": [{"block": "b0001", "quote": SESSION_TEXT}],
                        }
                    ],
                    "edges": [],
                },
                ensure_ascii=False,
            )
        ]
    )
    monkeypatch.setattr(cli, "_llm_client", lambda: (client, "extract-model"))

    assert await _ingest(_ingest_args(tmp_path, store)) == 0

    assert "长期记忆" in client.prompts[0]
    assert "retry-with-backoff" in client.prompts[0]
    maker = create_sessionmaker(kb_engine)
    async with maker() as session:
        audit = await session.scalar(
            select(KbWriteAudit).where(KbWriteAudit.action == "extract_session")
        )
    assert audit is not None
    assert (audit.actor, audit.project, audit.result) == ("worker", "demo", "ok")
    assert audit.memory_snapshot == version


async def test_ingest_audits_empty_extraction(
    tmp_path: Path,
    kb_engine: AsyncEngine,
    store: PgKnowledgeStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await catalog.create_kb(store, kb_id="demo")
    version = await _publish_snapshot(store, kb_engine)
    client = FakeClient([json.dumps({"nodes": [], "edges": []})])
    monkeypatch.setattr(cli, "_llm_client", lambda: (client, "extract-model"))

    assert await _ingest(_ingest_args(tmp_path, store)) == 0

    maker = create_sessionmaker(kb_engine)
    async with maker() as session:
        audit = await session.scalar(
            select(KbWriteAudit).where(KbWriteAudit.action == "extract_session")
        )
    assert audit is not None and audit.result == "empty"
    assert audit.memory_snapshot == version
