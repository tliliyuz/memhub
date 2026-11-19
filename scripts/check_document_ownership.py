#!/usr/bin/env python3
"""Markdown 文档权威归属与增量影响检查（与评测仓同源，按本仓文档矩阵参数化）。

这个检查器故意只自动化可确定的边界，不尝试用正则表达式替代负责人对
产品语义的裁决。`--staged` 用于 pre-commit：只检查本次新增的行，避免
把历史债务伪装成当前提交引入的问题；`--all` 用于全量归属重构；
`--changed` 输出修改权威文档后的反向引用候选，始终不阻断提交。

本仓参数：`AUTHORITY_DOCS` 取自根入口 §3「权威文档矩阵」；权威文档的
「适用范围 / 不负责」既接受表格行，也接受本仓沿用的引用块写法
（`> 适用范围：…`）。
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

AUTHORITY_DOCS = {
    "docs/architecture.md",
    "docs/contracts/README.md",
    "docs/contracts/ingest-api.md",
    "docs/contracts/kb-admin-api.md",
    "docs/contracts/mcp-tools.md",
    "docs/contracts/node-schema.md",
    "docs/contracts/source-registry.md",
    "docs/tech/ENVIRONMENT.md",
    "docs/guides/DEVELOPMENT.md",
    "docs/decisions/README.md",
}

DEPRECATED_DOCS: set[str] = set()
HISTORY_DOCS = {"docs/CHANGELOG.md"}
ADR_PREFIX = "docs/decisions/ADR-"

# 知识真源与抽取 profile 不是治理文档：标题与正文由抽取内容决定，不在此检查。
EXCLUDED_PREFIXES = ("knowledge/", "prompts/")


def _keep(path: str) -> bool:
    return not path.startswith(EXCLUDED_PREFIXES)


LINK_RE = re.compile(r"\]\(([^)#\s]+)(?:#[^)]*)?\)")
DIFF_FILE_RE = re.compile(r"^\+\+\+ b/(.+)$")
HISTORY_RE = re.compile(
    r"(?:\b20\d{2}-\d{2}-\d{2}\b.*(?:RED|GREEN|passed|failed|通过|失败)|"
    r"(?:commit|提交|hash|哈希)\s*[:：]?\s*[0-9a-f]{7,})"
)

# 密钥类事实不得进入团队共享文档：只允许出现键名，不允许出现「值」的形态。
# 这条规则针对文档，不针对 `.env`（`.env` 本身被 .gitignore 排除）。
SECRET_LINE_RE = re.compile(
    r"(?:password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key)\s*[:=]\s*[^\s`'\"<>)]{6,}",
    re.IGNORECASE,
)


def run_git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.stdout.decode("utf-8", "surrogateescape")


def markdown_files() -> list[str]:
    tracked = run_git("ls-files", "-z", "--", "*.md").split("\0")
    untracked = run_git("ls-files", "--others", "--exclude-standard", "-z", "--", "*.md").split(
        "\0"
    )
    return sorted({path for path in [*tracked, *untracked] if path and _keep(path)})


def staged_added_lines() -> dict[str, list[tuple[int, str]]]:
    text = run_git(
        "diff", "--cached", "--no-color", "--unified=0", "--diff-filter=ACMR", "--", "*.md"
    )
    return {path: lines for path, lines in parse_added_diff(text).items() if _keep(path)}


def working_added_lines() -> dict[str, list[tuple[int, str]]]:
    text = run_git("diff", "--no-color", "--unified=0", "--diff-filter=ACMR", "--", "*.md")
    result = staged_added_lines()
    for path, lines in parse_added_diff(text).items():
        result.setdefault(path, []).extend(lines)
    for path in run_git("ls-files", "--others", "--exclude-standard", "--", "*.md").split("\0"):
        if path:
            try:
                lines = (REPO_ROOT / path).read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeError):
                continue
            result[path] = list(enumerate(lines, 1))
    return result


def parse_added_diff(diff: str) -> dict[str, list[tuple[int, str]]]:
    additions: dict[str, list[tuple[int, str]]] = {}
    current: str | None = None
    new_line = 0
    for raw in diff.splitlines():
        file_match = DIFF_FILE_RE.match(raw)
        if file_match:
            current = file_match.group(1)
            additions.setdefault(current, [])
            continue
        if current is None:
            continue
        if raw.startswith("@@"):
            hunk = re.search(r"\+(\d+)(?:,(\d+))?", raw)
            if hunk:
                new_line = int(hunk.group(1))
            continue
        if raw.startswith("+") and not raw.startswith("+++"):
            additions[current].append((new_line, raw[1:]))
            new_line += 1
        elif not raw.startswith("-"):
            new_line += 1
    return additions


def report(message: str, failures: list[str]) -> None:
    failures.append(message)
    print(f"文档归属检查：{message}", file=sys.stderr)


def has_field(head: str, label: str) -> bool:
    """表格行 `| 适用范围 | …|` 或引用块 `> 适用范围：…` 都算声明。"""
    return any(
        f"| {label} |" in line or line.startswith((f"> {label}：", f"> {label}:"))
        for line in head.split("\n")
    )


def check_metadata(path: str, lines: list[str], failures: list[str], *, strict: bool) -> None:
    if path not in AUTHORITY_DOCS or not strict:
        return
    text = "\n".join(lines[:40])
    if not has_field(text, "适用范围"):
        report(f"{path} 缺少权威文档元数据「适用范围」", failures)
    if not has_field(text, "不负责"):
        report(f"{path} 缺少权威文档元数据「不负责」", failures)


def check_lines(
    path: str, lines: list[tuple[int, str]], failures: list[str], *, strict: bool
) -> None:
    is_adr = path.startswith(ADR_PREFIX)
    is_changelog = path in HISTORY_DOCS or is_adr
    for line_number, line in lines:
        if path in DEPRECATED_DOCS:
            report(f"{path}:{line_number} 弃用文档不得新增内容", failures)
        if not is_changelog and HISTORY_RE.search(line):
            report(
                f"{path}:{line_number} 当前文档新增了实施历史或提交证据；历史应进入 ADR/CHANGELOG",
                failures,
            )
        if SECRET_LINE_RE.search(line):
            report(
                f"{path}:{line_number} 疑似写入密钥值；文档只能写键名与读取方，值只进 .env",
                failures,
            )
    if strict and path in AUTHORITY_DOCS:
        try:
            content = (REPO_ROOT / path).read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError):
            content = []
        check_metadata(path, content, failures, strict=True)


def resolve_link(source: str, target: str) -> str | None:
    if target.startswith(("http://", "https://", "mailto:", "/", "#")):
        return None
    resolved = (REPO_ROOT / Path(source).parent / target).resolve()
    try:
        relative = resolved.relative_to(REPO_ROOT)
    except ValueError:
        return None
    return relative.as_posix()


def inbound_references(changed: set[str]) -> dict[str, set[str]]:
    inbound = {path: set() for path in changed}
    for source in markdown_files():
        try:
            text = (REPO_ROOT / source).read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        for match in LINK_RE.finditer(text):
            target = resolve_link(source, match.group(1))
            if target in inbound and source != target:
                inbound[target].add(source)
    return inbound


def print_impact(changed: set[str]) -> None:
    authorities = changed & AUTHORITY_DOCS
    if not authorities:
        return
    print("文档归属影响候选：")
    for authority in sorted(authorities):
        print(f"- {authority}")
        refs = inbound_references({authority}).get(authority, set())
        if refs:
            for ref in sorted(refs):
                print(f"  - 检查反向引用：{ref}")
        else:
            print("  - 未发现 Markdown 反向链接；仍需检查稳定文档名/章节引用")


def full_scan() -> tuple[dict[str, list[tuple[int, str]]], list[str]]:
    additions: dict[str, list[tuple[int, str]]] = {}
    failures: list[str] = []
    for path in markdown_files():
        try:
            content = (REPO_ROOT / path).read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError) as exc:
            report(f"{path} 无法读取：{exc}", failures)
            continue
        additions[path] = list(enumerate(content, 1))
    return additions, failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--staged", action="store_true", help="只检查暂存区新增内容，供 pre-commit 使用"
    )
    mode.add_argument("--all", action="store_true", help="扫描全部 Markdown，供全量治理审计使用")
    mode.add_argument("--changed", action="store_true", help="输出当前改动权威文档的反向影响候选")
    args = parser.parse_args()

    failures: list[str] = []
    if args.all:
        additions, failures = full_scan()
        for path, lines in additions.items():
            check_lines(path, lines, failures, strict=True)
    elif args.staged:
        additions = staged_added_lines()
        new_files = {
            path
            for path in run_git(
                "diff", "--cached", "--name-only", "--diff-filter=A", "--", "*.md"
            ).splitlines()
            if path
        }
        for path, lines in additions.items():
            check_lines(path, lines, failures, strict=path in AUTHORITY_DOCS or path in new_files)
    else:
        additions = working_added_lines()
        print_impact(set(additions))
        return 0

    if failures:
        return 1
    print("文档归属检查通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
