#!/usr/bin/env python3
"""机械门禁：数据访问禁止手写 SQL（ADR-0005）。

扫描 `src/` 下 Python 文件，命中以下任一即失败：

- 调用 SQLAlchemy 的 `text(...)`（裸 SQL 片段）；
- 把 SQL 字符串/拼接串直接传给 `execute(...)` / `exec_driver_sql(...)`。

允许的例外只有 `src/memhub/ingest/migrations.py`——迁移 DDL 是冻结基线，
不是运行时数据访问。新增例外必须在 ADR 里说明理由，不能在这里悄悄放宽。

用法：
    python scripts/check_no_raw_sql.py
"""

from __future__ import annotations

import argparse
import ast
import re
from pathlib import Path

ALLOWED = {Path("src/memhub/ingest/migrations.py")}
SQL_KEYWORDS = re.compile(
    r"\b(SELECT|INSERT|UPDATE|DELETE|CREATE|ALTER|DROP|TRUNCATE|WITH)\b",
    re.IGNORECASE,
)
EXECUTE_METHODS = {"execute", "exec_driver_sql", "scalar", "scalars"}


def _sql_like(node: ast.expr) -> bool:
    """字符串常量或 f-string 里出现 SQL 关键字，即视为裸 SQL。"""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return bool(SQL_KEYWORDS.search(node.value))
    if isinstance(node, ast.JoinedStr):
        return any(
            isinstance(part, ast.Constant)
            and isinstance(part.value, str)
            and SQL_KEYWORDS.search(part.value)
            for part in node.values
        )
    return False


def _is_text_call(func: ast.expr) -> bool:
    if isinstance(func, ast.Name) and func.id == "text":
        return True
    return isinstance(func, ast.Attribute) and func.attr == "text"


def find_violations(source: str, filename: str) -> list[tuple[int, str]]:
    """返回 (行号, 说明)；语法错误交给 ruff/pytest，不在这里报。"""
    tree = ast.parse(source, filename=filename)
    violations: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if _is_text_call(node.func):
            violations.append((node.lineno, "使用了 sqlalchemy.text()，请改用 ORM/Core 构造"))
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr in EXECUTE_METHODS
            and any(_sql_like(argument) for argument in node.args)
        ):
            violations.append((node.lineno, f"{func.attr}() 收到 SQL 字符串，请改用 ORM/Core 语句"))
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="仓库根目录（默认当前目录）")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    failed = False
    for path in sorted((root / "src").rglob("*.py")):
        relative = path.relative_to(root)
        if relative in ALLOWED:
            continue
        for lineno, message in find_violations(path.read_text(encoding="utf-8"), str(relative)):
            print(f"{relative}:{lineno}: {message}")
            failed = True
    if failed:
        print("禁止手写 SQL：请用 ORM/Core 表达（例外需在 ADR 登记）", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
