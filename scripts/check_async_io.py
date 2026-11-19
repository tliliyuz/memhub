#!/usr/bin/env python3
"""机械门禁：全仓 I/O 必须异步（ADR-0005 / 用户指令）。

扫描 `src/` 下 Python 文件，命中以下任一即失败：

- 同步子进程 / 磁盘 / 网络 / 睡眠原语：`subprocess.*`、`os.walk|stat|utime|...`、
  `time.sleep`、`shutil.*`、内置 `open(...)`、`httpx.Client(...)`；
- 在 Windows SelectorEventLoop 上必然失败的子进程 API：`anyio.run_process`、
  `anyio.open_process`、`asyncio.create_subprocess_*`；
- 对同步 `Path(...)` 直接调用阻塞方法（`read_text` / `is_file` / `rglob` …）。

放行名单只有 `src/memhub/kb/proc.py`：Windows 的 SelectorEventLoop 不支持
asyncio 子进程，唯一的替代是把它放进 anyio 工作线程；该文件是这条规则的
收敛点，其余代码一律通过 `proc.run_command` / `proc.spawn` 调用。

用法：
    python scripts/check_async_io.py
"""

from __future__ import annotations

import argparse
import ast
from pathlib import Path

# 每个文件允许出现的「同步原语键」；键形如 "subprocess.run" / "builtins.open"。
ALLOWED: dict[str, set[str]] = {
    "src/memhub/kb/proc.py": {"subprocess", "builtins.open"},
}

SYNC_ATTRS: dict[str, set[str]] = {
    "subprocess": {
        "run",
        "call",
        "check_call",
        "check_output",
        "Popen",
    },
    "os": {
        "walk",
        "stat",
        "utime",
        "listdir",
        "scandir",
        "remove",
        "unlink",
        "rename",
        "replace",
        "mkdir",
        "rmdir",
        "makedirs",
    },
    "time": {"sleep"},
    "shutil": {"copy", "copy2", "copyfile", "copytree", "move", "rmtree"},
    "httpx": {"Client"},
    "anyio": {"run_process", "open_process"},
    "asyncio": {"create_subprocess_exec", "create_subprocess_shell"},
}

SYNC_PATH_METHODS = {
    "read_text",
    "write_text",
    "read_bytes",
    "write_bytes",
    "open",
    "is_file",
    "is_dir",
    "exists",
    "stat",
    "rglob",
    "glob",
    "iterdir",
    "mkdir",
    "unlink",
    "replace",
    "rename",
    "rmdir",
    "touch",
    "resolve",
}


def _dotted(func: ast.expr) -> str | None:
    """`subprocess.run` / `anyio.run_process` 这类两级属性名。"""
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        return f"{func.value.id}.{func.attr}"
    return None


def _is_sync_path_ctor(node: ast.expr) -> bool:
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Path"


def find_violations(source: str, filename: str) -> list[tuple[int, str]]:
    """返回 (行号, 说明)；语法错误交给 ruff/pytest，不在这里报。"""
    tree = ast.parse(source, filename=filename)
    allowed = ALLOWED.get(filename, set())
    violations: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id == "open" and "builtins.open" not in allowed:
            violations.append((node.lineno, "直接调用 open()：请用 anyio.Path 异步读写"))
            continue
        dotted = _dotted(func)
        if dotted is not None:
            name, attr = dotted.split(".", 1)
            if attr in SYNC_ATTRS.get(name, set()):
                allowed_key = "subprocess" if name == "subprocess" else dotted
                if name not in allowed and allowed_key not in allowed:
                    violations.append(
                        (
                            node.lineno,
                            f"{dotted}() 是同步阻塞调用；请用异步替代（进程走 proc 模块）",
                        )
                    )
            continue
        if (
            isinstance(func, ast.Attribute)
            and func.attr in SYNC_PATH_METHODS
            and _is_sync_path_ctor(func.value)
        ):
            violations.append(
                (
                    node.lineno,
                    f"Path(...).{func.attr}() 是同步文件 IO；请改用 anyio.Path 并 await",
                )
            )
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="仓库根目录（默认当前目录）")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    failed = False
    for path in sorted((root / "src").rglob("*.py")):
        relative = path.relative_to(root).as_posix()
        for lineno, message in find_violations(path.read_text(encoding="utf-8"), relative):
            print(f"{relative}:{lineno}: {message}")
            failed = True
    if failed:
        print("同步 I/O：请改为 async 实现（例外需在 ADR 登记）", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
