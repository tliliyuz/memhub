"""`tests/env_loader.py` 的验收测试。

规格见 `docs/tech/ENVIRONMENT.md` 的 `MEMHUB_TEST_DB_URL` 行：进程环境变量优先；
未设置或为空时依次读仓库根 `.env` 与 worktree 主 checkout 的 `.env`；只读这一个键。
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

import env_loader

KEY = "MEMHUB_TEST_DB_URL"
GIT_AVAILABLE = shutil.which("git") is not None


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "a.txt").write_text("a\n", encoding="utf-8")
    _git(repo, "add", "a.txt")
    _git(
        repo,
        "-c",
        "user.email=test@example.invalid",
        "-c",
        "user.name=test",
        "commit",
        "-q",
        "-m",
        "init",
    )
    return repo


def test_read_env_value_handles_comments_quotes_and_crlf(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_bytes(
        b"# comment\r\nMEMHUB_DB_URL=\r\nexport MEMHUB_TEST_DB_URL='postgresql://a@h/db'\r\n"
    )
    assert env_loader.read_env_value(env, KEY) == "postgresql://a@h/db"
    assert env_loader.read_env_value(env, "MEMHUB_DB_URL") is None


def test_read_env_value_missing_file_or_key(tmp_path: Path) -> None:
    assert env_loader.read_env_value(tmp_path / "absent", KEY) is None
    env = tmp_path / ".env"
    env.write_text("OTHER=1\n", encoding="utf-8")
    assert env_loader.read_env_value(env, KEY) is None


def test_read_env_value_double_quotes_and_spaces(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text('  MEMHUB_TEST_DB_URL = "postgresql://b@h/db"  \n', encoding="utf-8")
    assert env_loader.read_env_value(env, KEY) == "postgresql://b@h/db"


def test_resolve_prefers_explicit_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(KEY, "postgresql://env/db")
    (tmp_path / ".env").write_text(f"{KEY}=postgresql://file/db\n", encoding="utf-8")
    assert env_loader.resolve_test_db_url(tmp_path) == "postgresql://env/db"


def test_resolve_reads_root_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(KEY, raising=False)
    (tmp_path / ".env").write_text(f"{KEY}=postgresql://file/db\n", encoding="utf-8")
    assert env_loader.resolve_test_db_url(tmp_path) == "postgresql://file/db"


def test_resolve_empty_value_counts_as_unset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(KEY, raising=False)
    monkeypatch.setattr(env_loader, "find_main_checkout", lambda root: None)
    (tmp_path / ".env").write_text(f"{KEY}=\n", encoding="utf-8")
    assert env_loader.resolve_test_db_url(tmp_path) is None


def test_resolve_falls_back_to_main_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(KEY, raising=False)
    main = tmp_path / "main"
    main.mkdir()
    (main / ".env").write_text(f"{KEY}=postgresql://main/db\n", encoding="utf-8")
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    monkeypatch.setattr(env_loader, "find_main_checkout", lambda root: main)
    assert env_loader.resolve_test_db_url(worktree) == "postgresql://main/db"


def test_resolve_never_raises_without_any_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(KEY, raising=False)
    monkeypatch.setattr(env_loader, "find_main_checkout", lambda root: None)
    assert env_loader.resolve_test_db_url(tmp_path) is None


def test_find_main_checkout_none_for_non_repo(tmp_path: Path) -> None:
    assert env_loader.find_main_checkout(tmp_path) is None


@pytest.mark.skipif(not GIT_AVAILABLE, reason="需要 git 可执行文件")
def test_find_main_checkout_none_for_main_checkout(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    assert env_loader.find_main_checkout(repo) is None


@pytest.mark.skipif(not GIT_AVAILABLE, reason="需要 git 可执行文件")
def test_find_main_checkout_detects_worktree(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    worktree = tmp_path / "worktree"
    _git(repo, "worktree", "add", "-q", str(worktree), "-b", "wt")
    assert env_loader.find_main_checkout(worktree) == repo.resolve()
