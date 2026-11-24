"""`memhub migrate-kb` 的只读入口：dry-run 统计、阻塞判定与删除守卫。

规格 `docs/plans/kb-pg-migration-spec.md` §5：
- 第 5 步 `--dry-run` 只解析与统计，不写库、不删文件；
- 第 8 步 `--delete-source` 仅在 `--verify-only` 通过且负责人授权时可用，默认不删。

写库半段需要 `MEMHUB_KB_DB_URL`，本模块的用例不连库，只验收「不写、不删、退出码正确」。
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
from pathlib import Path

import pytest

from memhub.cli.main import _migrate_kb

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "knowledge_tree"


def _tree(tmp_path: Path) -> Path:
    root = tmp_path / "knowledge"
    shutil.copytree(FIXTURE, root)
    return root


def _args(root: Path, **overrides: object) -> argparse.Namespace:
    data: dict[str, object] = {
        "knowledge_dir": str(root),
        "dsn": None,
        "schema": None,
        "dry_run": True,
        "verify_only": False,
        "delete_source": False,
        "archives": "skip",
    }
    data.update(overrides)
    return argparse.Namespace(**data)


def _snapshot(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


async def test_dry_run_reports_counts_and_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _tree(tmp_path)
    before = _snapshot(root)

    code = await _migrate_kb(_args(root))

    out = capsys.readouterr().out
    assert code == 0
    assert "nodes" in out.lower()
    assert _snapshot(root) == before, "dry-run 不得改动真源"


async def test_dry_run_lists_registry_differences(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _tree(tmp_path)

    await _migrate_kb(_args(root))

    out = capsys.readouterr().out
    assert "orphan" in out  # 目录存在但未登记
    assert "gone" in out  # 登记了但目录不在


async def test_dry_run_fails_when_pending_archive_blocks(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _tree(tmp_path)
    (root / "_kb_archives").mkdir(parents=True, exist_ok=True)
    (root / "_kb_archives" / "pending.json").write_text("{}\n", encoding="utf-8")

    code = await _migrate_kb(_args(root))

    assert code != 0
    assert "pending" in capsys.readouterr().err.lower() or "归档" in capsys.readouterr().err


async def test_missing_knowledge_dir_is_usage_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = await _migrate_kb(_args(tmp_path / "absent"))

    assert code == 2
    assert capsys.readouterr().err


async def test_delete_source_requires_verify_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--delete-source` 单独出现必须拒绝：没有校验通过就不允许删真源。"""
    root = _tree(tmp_path)

    code = await _migrate_kb(_args(root, dry_run=False, delete_source=True))

    assert code == 2
    assert "verify-only" in capsys.readouterr().err


async def test_verify_only_requires_dsn(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """校验要连库比对，没有 DSN 就必须显式失败，不能静默当作通过。"""
    root = _tree(tmp_path)

    code = await _migrate_kb(_args(root, dry_run=False, verify_only=True))

    assert code == 2
    assert "MEMHUB_KB_DB_URL" in capsys.readouterr().err


async def test_non_dry_run_without_dsn_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _tree(tmp_path)

    code = await _migrate_kb(_args(root, dry_run=False))

    assert code == 2
    assert "MEMHUB_KB_DB_URL" in capsys.readouterr().err
