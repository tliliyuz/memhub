#!/usr/bin/env python3
"""机械门禁：全仓 I/O 必须异步（ADR-0005 / 用户指令）。

扫描 `src/` 与 `alembic/` 下 Python 文件，命中以下任一即失败：

- 同步子进程 / 磁盘 / 网络 / 睡眠原语：`subprocess.*`、`os.walk|stat|utime|...`、
  `time.sleep`、`shutil.*`、内置 `open(...)`、`httpx.Client(...)`；
- 在 Windows SelectorEventLoop 上必然失败的子进程 API：`anyio.run_process`、
  `anyio.open_process`、`asyncio.create_subprocess_*`；
- 对同步 `Path(...)` 直接调用阻塞方法（`read_text` / `is_file` / `rglob` …）。

`alembic/` 在 `src/` 之外，但迁移体同样不能塞同步 I/O 绕过门禁。

放行名单只有 `src/memhub/kb/proc.py`：Windows 的 SelectorEventLoop 不支持
asyncio 子进程，唯一的替代是把它放进 anyio 工作线程；该文件是这条规则的
收敛点，其余代码一律通过 `proc.run_command` / `proc.spawn` 调用。

用法：
    python scripts/check_async_io.py
"""

from __future__ import annotations

import argparse
import ast
from collections.abc import Iterator
from pathlib import Path

# 每个文件允许出现的「同步原语键」；键形如 "subprocess.run" / "builtins.open"。
ALLOWED: dict[str, set[str]] = {
    "src/memhub/kb/proc.py": {"subprocess", "builtins.open"},
}

# 扫描根：`alembic/` 不存在时跳过（未引入 Alembic 的分支不受影响）。
SCAN_ROOTS = ("src", "alembic")

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


def _annotation_is_sync_path(node: ast.expr | None) -> bool:
    """参数注解是同步 `pathlib.Path`（含别名 `Path`）时为真；`AsyncPath` 等不算。"""
    if node is None:
        return False
    if isinstance(node, ast.Name):
        return node.id == "Path"
    if isinstance(node, ast.Attribute):
        return node.attr == "Path" and not (
            isinstance(node.value, ast.Name) and node.value.id in {"AsyncPath", "anyio"}
        )
    return False


def _scope_nodes(stmts: list[ast.stmt]) -> Iterator[ast.AST]:
    """作用域内的全部节点（含嵌套语句），但不进入内层函数/类体。

    内层函数有自己的作用域，变量绑定不能互相污染；函数节点本身仍产出，
    由调用方单独作为一个作用域处理。
    """
    stack: list[ast.AST] = list(stmts)
    while stack:
        node = stack.pop()
        yield node
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue
        stack.extend(ast.iter_child_nodes(node))


def _path_bindings(
    stmts: list[ast.stmt], initial: dict[str, bool] | None = None
) -> dict[str, bool]:
    """单个作用域内：变量名 → 是否为同步 `pathlib.Path`。

    `Path(...)` 好认，但 `root / "x"`、`Path(...).resolve()`、`path = 前者` 同样产出
    同步 Path。按源码顺序推最后绑定；`for ... in Path(...).iterdir()` 与
    `AsyncPath(...).rglob()` 由迭代表达式本身决定，返回值同类。
    """
    bindings: dict[str, bool] = dict(initial or {})

    def value_is_sync(node: ast.expr | None) -> bool:
        return node is not None and _is_sync_path_expr(node, bindings)

    ordered = sorted(
        (node for node in _scope_nodes(stmts) if isinstance(node, ast.stmt)),
        key=lambda node: (node.lineno, node.col_offset),
    )
    for node in ordered:
        if isinstance(node, (ast.For, ast.AsyncFor)) and isinstance(node.target, ast.Name):
            bindings[node.target.id] = value_is_sync(node.iter)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            bindings[node.target.id] = value_is_sync(node.value) or _annotation_is_sync_path(
                node.annotation
            )
        elif isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name):
                bindings[target.id] = value_is_sync(node.value)
    return bindings


def _is_sync_path_expr(node: ast.expr, bindings: dict[str, bool]) -> bool:
    """`Path(...)` 及其直接派生物（`/` 拼接、属性、同类方法调用、同作用域变量）。"""
    if _is_sync_path_ctor(node):
        return True
    if isinstance(node, ast.BinOp):
        return _is_sync_path_expr(node.left, bindings) or _is_sync_path_expr(node.right, bindings)
    if isinstance(node, ast.Name):
        return bindings.get(node.id, False)
    if isinstance(node, ast.Attribute):
        return _is_sync_path_expr(node.value, bindings)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        # `Path(...).resolve()` 之类返回同类对象；`AsyncPath(...)` 的接收者不成立。
        return _is_sync_path_expr(node.func.value, bindings)
    return False


def _is_sync_path_receiver(node: ast.expr, bindings: dict[str, bool]) -> bool:
    return _is_sync_path_expr(node, bindings)


def _scopes(
    stmts: list[ast.stmt], inherited: dict[str, bool] | None = None
) -> Iterator[tuple[dict[str, bool], list[ast.AST]]]:
    """递归产出 (作用域绑定, 该作用域的节点)；内层函数不继承外层变量推断。"""
    bindings = _path_bindings(stmts, inherited)
    nodes = list(_scope_nodes(stmts))
    yield bindings, nodes
    for node in nodes:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)
            initial = {arg.arg: True for arg in args if _annotation_is_sync_path(arg.annotation)}
            yield from _scopes(node.body, initial)


def find_violations(source: str, filename: str) -> list[tuple[int, str]]:
    """返回 (行号, 说明)；语法错误交给 ruff/pytest，不在这里报。"""
    tree = ast.parse(source, filename=filename)
    allowed = ALLOWED.get(filename, set())
    violations: list[tuple[int, str]] = []
    seen_lines: set[tuple[int, str]] = set()
    for bindings, nodes in _scopes(tree.body):
        for node in nodes:
            if not isinstance(node, ast.Call):
                continue
            for lineno, message in _call_violation(node, bindings, allowed):
                if (lineno, message) not in seen_lines:
                    seen_lines.add((lineno, message))
                    violations.append((lineno, message))
    return violations


def _call_violation(
    node: ast.Call, bindings: dict[str, bool], allowed: set[str]
) -> list[tuple[int, str]]:
    func = node.func
    if isinstance(func, ast.Name) and func.id == "open" and "builtins.open" not in allowed:
        return [(node.lineno, "直接调用 open()：请用 anyio.Path 异步读写")]
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        name = func.value.id
        if func.attr in SYNC_ATTRS.get(name, set()):
            dotted = f"{name}.{func.attr}"
            allowed_key = "subprocess" if name == "subprocess" else dotted
            if name not in allowed and allowed_key not in allowed:
                return [
                    (node.lineno, f"{dotted}() 是同步阻塞调用；请用异步替代（进程走 proc 模块）")
                ]
            return []
    if (
        isinstance(func, ast.Attribute)
        and func.attr in SYNC_PATH_METHODS
        and _is_sync_path_receiver(func.value, bindings)
    ):
        return [(node.lineno, f"同步 Path.{func.attr}() 是阻塞文件 IO；请改用 anyio.Path 并 await")]
    return []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="仓库根目录（默认当前目录）")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    failed = False
    for scan_root in SCAN_ROOTS:
        base = root / scan_root
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
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
