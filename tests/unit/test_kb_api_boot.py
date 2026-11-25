"""kb-api 启动契约（规格 §9.2.4）：强制 PG，缺 DSN 直接失败，不退回文件存储。"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI

from memhub.kb.api import create_app
from memhub.kb.pgstore import PgKnowledgeStore
from memhub.kb.session import KB_DSN_KEY, KbDsnMissing

DSN = "postgresql://kb@127.0.0.1:5432/memhub_prod"


def _clean_env(monkeypatch: pytest.MonkeyPatch, knowledge: Path | None = None) -> None:
    for key in (
        KB_DSN_KEY,
        "MEMHUB_KB_WEB_DIST",
        "MEMHUB_MCP_GRANTS",
        "MEMHUB_DATA_DIR",
    ):
        monkeypatch.delenv(key, raising=False)
    if knowledge is not None:
        monkeypatch.setenv("MEMHUB_KNOWLEDGE_DIR", str(knowledge))
    else:
        monkeypatch.delenv("MEMHUB_KNOWLEDGE_DIR", raising=False)


def test_create_app_without_dsn_fails_instead_of_using_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """即使 `MEMHUB_KNOWLEDGE_DIR` 指向可用目录，也不允许退回文件真源。"""
    (tmp_path / "knowledge").mkdir()
    _clean_env(monkeypatch, tmp_path / "knowledge")
    with pytest.raises(KbDsnMissing):
        create_app()


def test_create_app_with_dsn_builds_pg_store(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clean_env(monkeypatch, tmp_path / "knowledge")
    monkeypatch.setenv(KB_DSN_KEY, DSN)
    app = create_app()
    assert isinstance(app, FastAPI)
    assert isinstance(app.state.kb.store, PgKnowledgeStore)
