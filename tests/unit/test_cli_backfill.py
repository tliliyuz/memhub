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
