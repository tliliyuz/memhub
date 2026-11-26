"""CLI 运行入口的存储接线（规格 §9.2.4）：一律 PG，缺 DSN 直接失败。

ingest 与采集共用同一写边界：只写已登记且活动的库。
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from memhub.cli import main as cli
from memhub.cli.main import _ingest, _kb, _mcp, _worker
from memhub.kb import catalog
from memhub.kb.models import Base
from memhub.kb.pgstore import PgKnowledgeStore
from memhub.kb.session import KB_DSN_KEY, KbDsnMissing, create_sessionmaker


@pytest.fixture
async def store(kb_engine: AsyncEngine) -> PgKnowledgeStore:
    async with kb_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return PgKnowledgeStore(create_sessionmaker(kb_engine))


def _args(
    tmp_path: Path, store: PgKnowledgeStore | None, **overrides: object
) -> argparse.Namespace:
    source = tmp_path / "source"
    source.mkdir(exist_ok=True)
    (source / "a.jsonl").write_text('{"text": "合成样本"}\n', encoding="utf-8")
    data: dict[str, object] = {
        "path": str(source),
        "profile": "sessions",
        "project": "ghost",
        "limit": 0,
        "max_chars": 12000,
        "max_input_chars": 0,
        "dry_run": True,
        "create_project": False,
    }
    if store is not None:
        data["store"] = store
    data.update(overrides)
    return argparse.Namespace(**data)


async def test_unknown_project_is_refused_without_creating_a_library(
    tmp_path: Path, store: PgKnowledgeStore
) -> None:
    code = await _ingest(_args(tmp_path, store))

    assert code == 2
    assert await store.project_status("ghost") == "unregistered"


async def test_dry_run_accepts_registered_active_project(
    tmp_path: Path, store: PgKnowledgeStore
) -> None:
    await catalog.create_kb(store, kb_id="demo")

    assert await _ingest(_args(tmp_path, store, project="demo")) == 0


async def test_ingest_requires_dsn_without_injected_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(KB_DSN_KEY, raising=False)
    args = _args(tmp_path, None)

    with pytest.raises(KbDsnMissing):
        await _ingest(args)


def test_projection_subcommands_are_removed(capsys: pytest.CaptureFixture[str]) -> None:
    """投影子系统已下线：`project` / `serve` 不再是合法子命令。"""
    for command in ("project", "serve"):
        with pytest.raises(SystemExit) as exc:
            cli.main([command])
        assert exc.value.code == 2
        assert "invalid choice" in capsys.readouterr().err


def test_kb_console_rejects_removed_projection_flags(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`kb` 不再接受投影/explorer 相关参数。"""

    async def fake_server(target: str, *, host: str, port: int, log_level: str) -> None:
        raise AssertionError("参数应在解析阶段被拒绝")

    monkeypatch.setattr(cli, "_run_server", fake_server)
    for flag in (
        ("--graph-out", "kg.json"),
        ("--spawn-graph",),
        ("--graph-port", "8703"),
    ):
        with pytest.raises(SystemExit) as exc:
            cli.main(["kb", *flag])
        assert exc.value.code == 2
        assert "unrecognized arguments" in capsys.readouterr().err


async def test_mcp_requires_dsn_without_injected_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(KB_DSN_KEY, raising=False)

    with pytest.raises(KbDsnMissing):
        await _mcp(argparse.Namespace())


def _worker_args(tmp_path: Path, store: PgKnowledgeStore | None = None) -> argparse.Namespace:
    data: dict[str, object] = {
        "data_dir": str(tmp_path),
        "dry_run": True,
        "window": "",
        "once": True,
        "interval": 60.0,
        "limit": 1,
    }
    if store is not None:
        data["store"] = store
    return argparse.Namespace(**data)


async def test_worker_requires_dsn_without_injected_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(KB_DSN_KEY, raising=False)

    with pytest.raises(KbDsnMissing):
        await _worker(_worker_args(tmp_path))


async def test_worker_requires_data_dir(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("MEMHUB_DATA_DIR", raising=False)

    assert await _worker(argparse.Namespace(data_dir="", dry_run=True)) == 2
    assert "MEMHUB_DATA_DIR" in capsys.readouterr().err


async def test_worker_dry_run_reports_pg_truth(
    tmp_path: Path,
    store: PgKnowledgeStore,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """worker 入口不再要求/读取 `MEMHUB_KNOWLEDGE_DIR`，冒烟即报 PG 真源。"""
    monkeypatch.delenv("MEMHUB_KNOWLEDGE_DIR", raising=False)

    assert await _worker(_worker_args(tmp_path, store)) == 0
    assert "真源=PG" in capsys.readouterr().out


async def test_kb_console_starts_without_knowledge_dir(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """管理台真源是 PG：不再要求也不读取 `MEMHUB_KNOWLEDGE_DIR`。"""
    monkeypatch.delenv("MEMHUB_KNOWLEDGE_DIR", raising=False)
    monkeypatch.delenv("MEMHUB_KB_WEB_DIST", raising=False)
    calls: list[tuple[str, str, int]] = []

    async def fake_server(target: str, *, host: str, port: int, log_level: str) -> None:
        calls.append((target, host, port))

    monkeypatch.setattr(cli, "_run_server", fake_server)
    code = await _kb(
        argparse.Namespace(
            web_dist="",
            data_dir="",
            port=8799,
        )
    )

    assert code == 0
    assert calls == [("memhub.kb.api:create_app", "127.0.0.1", 8799)]
    assert "真源=PG（schema kb）" in capsys.readouterr().out
