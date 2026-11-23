"""CLI ingest 与采集共用同一写边界：只写已登记且活动的库。"""

from __future__ import annotations

import argparse
from pathlib import Path

from anyio import Path as AsyncPath

from memhub.cli.main import _ingest
from memhub.kb import catalog
from memhub.kb.store import KnowledgeStore


def _args(tmp_path: Path, **overrides: object) -> argparse.Namespace:
    source = tmp_path / "source"
    source.mkdir(exist_ok=True)
    (source / "a.jsonl").write_text('{"text": "合成样本"}\n', encoding="utf-8")
    data: dict[str, object] = {
        "path": str(source),
        "profile": "sessions",
        "project": "ghost",
        "limit": 0,
        "knowledge_dir": str(tmp_path / "knowledge"),
        "max_chars": 12000,
        "max_input_chars": 0,
        "dry_run": True,
        "create_project": False,
    }
    data.update(overrides)
    return argparse.Namespace(**data)


async def test_unknown_project_is_refused_without_creating_a_library(
    tmp_path: Path,
) -> None:
    args = _args(tmp_path)
    code = await _ingest(args)

    assert code == 2
    assert not await AsyncPath(tmp_path / "knowledge" / "ghost").exists()


async def test_dry_run_accepts_registered_active_project(tmp_path: Path) -> None:
    knowledge = tmp_path / "knowledge"
    await catalog.create_kb(KnowledgeStore(knowledge), kb_id="demo")
    args = _args(tmp_path, project="demo", dry_run=True)

    assert await _ingest(args) == 0
