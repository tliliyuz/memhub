"""导入与正文存储自检命令的入口校验与接线。"""

from __future__ import annotations

from pathlib import Path

import pytest

from memhub.cli import main as cli


def test_import_refuses_two_modes_at_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MEMHUB_DATA_DIR", raising=False)
    code = cli.main(["import-raw-store", "--data-dir", str(tmp_path), "--dry-run", "--verify-only"])

    assert code == 2


def test_import_requires_data_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MEMHUB_DATA_DIR", raising=False)
    assert cli.main(["import-raw-store"]) == 2


@pytest.mark.parametrize(
    ("flags", "expect_migrate"),
    [([], True), (["--dry-run"], False), (["--verify-only"], False)],
)
def test_import_migrates_only_when_writing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    flags: list[str],
    expect_migrate: bool,
) -> None:
    from memhub.ingest import app as ingest_app
    from memhub.ingest.store import MemoryStore

    calls: list[str] = []

    class SpyStore(MemoryStore):
        async def migrate(self) -> list[str]:
            calls.append("migrate")
            return []

        async def close(self) -> None:
            calls.append("close")

    monkeypatch.setenv("MEMHUB_DB_URL", "postgresql://memhub_app@127.0.0.1:5432/memhub_test")
    monkeypatch.delenv("MEMHUB_CH_URL", raising=False)
    monkeypatch.setattr(ingest_app, "build_store", lambda: SpyStore())

    assert cli.main(["import-raw-store", "--data-dir", str(tmp_path), *flags]) == 0
    # 导入会直接写 ingest_queue：写模式必须先建表/补迁移；盘点与核验保持只读。
    assert ("migrate" in calls) is expect_migrate


def test_check_content_store_passes_for_local_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("MEMHUB_CH_URL", raising=False)
    monkeypatch.delenv("MEMHUB_DATA_DIR", raising=False)

    assert cli.main(["check-content-store", "--data-dir", str(tmp_path)]) == 0


def test_check_content_store_needs_a_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MEMHUB_CH_URL", raising=False)
    monkeypatch.delenv("MEMHUB_DATA_DIR", raising=False)

    assert cli.main(["check-content-store"]) == 2
