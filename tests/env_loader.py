"""测试入口的 `.env` 读取。

规格见 `docs/tech/ENVIRONMENT.md` 的 `MEMHUB_TEST_DB_URL` 行：进程环境变量优先；
未设置或为空时依次读仓库根 `.env` 与 worktree 主 checkout 的 `.env`；只读这一个键，
不加载整份文件（避免覆盖 `MEMHUB_DB_URL`、`PG*` 等运行态变量）。
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

KEY = "MEMHUB_TEST_DB_URL"


def read_env_value(path: Path, key: str) -> str | None:
    """从 `.env` 读取一个键；文件缺失、无该键或值为空时返回 `None`。"""
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for raw in content.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line.removeprefix("export ").lstrip()
        name, separator, value = line.partition("=")
        if not separator or name.strip() != key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        return value or None
    return None


def find_main_checkout(root: Path) -> Path | None:
    """返回 worktree 对应的主 checkout 根；`root` 本身是主 checkout 或非 Git 仓库时返回 `None`。"""
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    common_dir = Path(completed.stdout.strip())
    if common_dir.name != ".git":
        return None
    main_root = common_dir.parent
    if main_root.resolve() == root.resolve():
        return None
    return main_root


def resolve_test_db_url(root: Path) -> str | None:
    """按「环境变量 > `root/.env` > 主 checkout 的 `.env`」解析测试库 DSN。"""
    from_environment = os.environ.get(KEY, "").strip()
    if from_environment:
        return from_environment
    value = read_env_value(root / ".env", KEY)
    if value:
        return value
    main_root = find_main_checkout(root)
    if main_root is None:
        return None
    return read_env_value(main_root / ".env", KEY)
