#!/usr/bin/env python3
"""跨平台 Markdown 结构检查。

只判定可机械裁决的结构问题：控制字符、制表符、H1 数量、标题跳级、
加粗伪标题、相对链接存在性、绝对路径链接、CLAUDE.md 与 AGENTS.md 镜像一致。

不判定内容是否正确、事实归属是否唯一——那些是人工评审。
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

LINK_RE = re.compile(r"\]\(([^)#\s]+)(#[^)]*)?\)")
ABSOLUTE_PATH_RE = re.compile(r"\]\((<?)(?:[A-Za-z]:[\\/]|/home/|/Users/)")


def markdown_files() -> list[str]:
    paths: set[str] = set()
    for command in (
        ["git", "ls-files", "-z", "--", "*.md"],
        ["git", "ls-files", "--others", "--exclude-standard", "-z", "--", "*.md"],
    ):
        result = subprocess.run(
            command, cwd=REPO_ROOT, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False
        )
        paths.update(
            name for name in result.stdout.decode("utf-8", "surrogateescape").split("\0") if name
        )
    # knowledge/ 是 worker 产出的知识真源（标题由抽取内容决定），
    # prompts/ 是抽取 profile（非治理文档）：两者不适用文档结构规则。
    return sorted(p for p in paths if not p.startswith(("knowledge/", "prompts/")))


def report(message: str, failed: list[bool]) -> None:
    print(f"文档格式错误：{message}", file=sys.stderr)
    failed[0] = True


def check_structure(relative_path: str, failed: list[bool]) -> None:
    try:
        text = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        report(f"{relative_path} 不可读或非 UTF-8（{exc}）", failed)
        return
    lines = text.split("\n")

    for line_number, line in enumerate(lines, 1):
        if any((ord(c) < 32 and c not in "\r\n") or ord(c) == 127 for c in line):
            report(f"{relative_path}:{line_number} 含控制字符", failed)
        if "\t" in line:
            report(f"{relative_path}:{line_number} 含制表符；Markdown 使用空格缩进", failed)

    fence = False
    h1_count = 0
    previous_level = 0
    for line_number, raw in enumerate(lines, 1):
        line = raw.rstrip("\r")
        if line.startswith("```"):
            fence = not fence
            continue
        if fence:
            continue
        heading = re.match(r"^(#+) ", line)
        if heading:
            level = len(heading.group(1))
            if level == 1:
                h1_count += 1
            if previous_level > 0 and level > previous_level + 1:
                report(
                    f"{relative_path}:{line_number} 标题层级从 H{previous_level} 跳到 H{level}",
                    failed,
                )
            previous_level = level
        if re.fullmatch(r"\*\*[^*]+\*\*[:：]?", line):
            report(f"{relative_path}:{line_number} 不得用加粗段首模拟标题", failed)

    if h1_count != 1:
        report(f"{relative_path} 应有且仅有一个 H1，实际 {h1_count} 个", failed)


def check_links(markdown_files_list: list[str], failed: list[bool]) -> None:
    for relative_path in markdown_files_list:
        try:
            text = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for line_number, line in enumerate(text.split("\n"), 1):
            if ABSOLUTE_PATH_RE.search(line):
                report(
                    f"{relative_path}:{line_number} 引用了绝对路径；仓库内链接必须用相对路径",
                    failed,
                )
            for match in LINK_RE.finditer(line):
                target = match.group(1)
                if target.startswith(("http://", "https://", "mailto:", "/", "#")):
                    continue
                resolved = (
                    REPO_ROOT / Path(relative_path).parent / target.split("#", 1)[0]
                ).resolve()
                try:
                    resolved.relative_to(REPO_ROOT)
                except ValueError:
                    report(f"{relative_path} 引用了仓库外相对路径 {target}", failed)
                    continue
                if not resolved.exists():
                    report(f"{relative_path} 引用了不存在的相对路径 {target}", failed)


def check_mirror(failed: list[bool]) -> None:
    agents = REPO_ROOT / "AGENTS.md"
    claude = REPO_ROOT / "CLAUDE.md"
    if agents.exists() and claude.exists() and agents.read_bytes() != claude.read_bytes():
        report("AGENTS.md 与 CLAUDE.md 不一致", failed)


def main() -> int:
    files = markdown_files()
    failed = [False]
    for relative_path in files:
        if (REPO_ROOT / relative_path).exists():
            check_structure(relative_path, failed)
    check_links(files, failed)
    check_mirror(failed)
    if failed[0]:
        return 1
    print("文档格式检查通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
