#!/usr/bin/env python3
"""跨平台 Markdown 格式检查（与评测仓同源，按本仓文档矩阵参数化）。

只判定可机械裁决的结构问题：控制字符、制表符、H1 数量、标题跳级、
加粗伪标题、H2 连续编号、相对链接存在性、ADR 手工编号、ROADMAP 小数里程碑、
AGENTS.md 与 CLAUDE.md 镜像一致性、绝对路径链接。

不判定内容是否正确、事实归属是否唯一——那些是人工评审。

本仓参数：
- `EXCLUDED_PREFIXES`：`knowledge/` 是 worker 产出的知识真源（标题由抽取内容
  决定）、`prompts/` 是抽取 profile，都不适用治理文档结构规则；
- `NUMBERED_DOCS`：本仓用连续整数 H2 编号的文档。`docs/contracts/ingest-api.md`
  有意从 §0「通用约定」起编，未列入——它仍受其余结构规则约束。
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

EXCLUDED_PREFIXES = ("knowledge/", "prompts/")

# 必须使用连续整数 H2 编号的文档。
NUMBERED_DOCS = (
    "docs/tech/architecture.md",
    "docs/tech/ENVIRONMENT.md",
    "docs/guides/DEVELOPMENT.md",
    "docs/contracts/kb-admin-api.md",
    "docs/contracts/mcp-tools.md",
    "docs/contracts/node-schema.md",
    "docs/contracts/source-registry.md",
)

LINK_RE = re.compile(r"\]\(([^)#\s]+)(#[^)]*)?\)")
ADR_NUMBERED_RE = re.compile(r"^#{2,3} [0-9]+(?:\.[0-9]+)?\. ")
ROADMAP_DECIMAL_RE = re.compile(r"^## M[0-9]+\.[0-9]+")
LEGACY_ADR_HEADING_RE = re.compile(
    r"^## (ADR 候选|建议决策|负责人裁决|当前裁决状态|可行方案|被否决方案)$"
)
ABSOLUTE_PATH_RE = re.compile(r"\]\((<?)(?:[A-Za-z]:[\\/]|/home/|/Users/)")


def _keep(path: str) -> bool:
    return not path.startswith(EXCLUDED_PREFIXES)


def git_staged_files() -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"],
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return [
        name
        for name in result.stdout.decode("utf-8", "surrogateescape").split("\0")
        if name and _keep(name)
    ]


def all_markdown_files() -> list[str]:
    paths: set[str] = set()
    for command in (
        ["git", "ls-files", "-z", "--", "*.md"],
        ["git", "ls-files", "--others", "--exclude-standard", "-z", "--", "*.md"],
    ):
        result = subprocess.run(
            command,
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        paths.update(
            name for name in result.stdout.decode("utf-8", "surrogateescape").split("\0") if name
        )
    return sorted(name for name in paths if _keep(name))


def read_lines(relative_path: str, failed: list[bool]) -> list[str] | None:
    path = REPO_ROOT / Path(relative_path)
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        report(f"{relative_path} 不存在", failed)
        return None
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        report(f"{relative_path} 不是有效 UTF-8（{exc}）", failed)
        return None
    # 只按 LF 切分：`str.splitlines()` 会静默吞掉垂直制表符/换页符，
    # 而它们正是这里要报的控制字符。
    return text.split("\n")


def report(message: str, failed: list[bool]) -> None:
    print(f"文档格式错误：{message}", file=sys.stderr)
    failed[0] = True


def check_structure(relative_path: str, failed: list[bool]) -> None:
    lines = read_lines(relative_path, failed)
    if lines is None:
        return

    for line_number, raw_line in enumerate(lines, 1):
        line = raw_line.rstrip("\r")
        if any((ord(char) < 32 and char not in "\r\n") or ord(char) == 127 for char in line):
            report(f"{relative_path}:{line_number} 含控制字符", failed)
        if "\t" in line:
            report(f"{relative_path}:{line_number} 含制表符；Markdown 使用空格缩进", failed)

    fence = False
    h1_count = 0
    previous_level = 0
    for line_number, raw_line in enumerate(lines, 1):
        line = raw_line.rstrip("\r")
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


def check_numbered_headings(relative_path: str, failed: list[bool]) -> None:
    lines = read_lines(relative_path, failed)
    if lines is None:
        return
    fence = False
    expected = 1
    for line_number, raw_line in enumerate(lines, 1):
        line = raw_line.rstrip("\r")
        if line.startswith("```"):
            fence = not fence
            continue
        if fence or not line.startswith("## "):
            continue
        match = re.match(r"^## ([0-9]+)\. ", line)
        if not match:
            report(f"{relative_path}:{line_number} H2 必须使用连续整数编号", failed)
            continue
        current = int(match.group(1))
        if current != expected:
            report(f"{relative_path}:{line_number} H2 期望编号 {expected}，实际 {current}", failed)
        expected = current + 1


def check_links(markdown_files: list[str], failed: list[bool]) -> None:
    for relative_path in markdown_files:
        lines = read_lines(relative_path, failed)
        if lines is None:
            continue
        for line_number, line in enumerate(lines, 1):
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


def check_global_rules(markdown_files: list[str], failed: list[bool]) -> None:
    adr_files = [
        path
        for path in markdown_files
        if path.startswith("docs/decisions/ADR-") and path.endswith(".md")
    ]
    for relative_path in adr_files:
        lines = read_lines(relative_path, failed)
        if lines and any(ADR_NUMBERED_RE.match(line) for line in lines):
            report(f"{relative_path} 的 ADR 章节使用了手工数字编号", failed)
        if lines and any(LEGACY_ADR_HEADING_RE.match(line) for line in lines):
            report(f"{relative_path} 使用了未统一的历史章节名", failed)

    roadmap = "docs/plans/ROADMAP.md"
    if roadmap in markdown_files:
        lines = read_lines(roadmap, failed)
        if lines and any(ROADMAP_DECIMAL_RE.match(line) for line in lines):
            report("ROADMAP 使用了小数里程碑", failed)

    agents = REPO_ROOT / "AGENTS.md"
    claude = REPO_ROOT / "CLAUDE.md"
    if agents.exists() and claude.exists() and agents.read_bytes() != claude.read_bytes():
        report("AGENTS.md 与 CLAUDE.md 不一致", failed)


def main(argv: list[str]) -> int:
    staged_mode = bool(argv and argv[0] == "--staged")
    staged_files = git_staged_files() if staged_mode else []
    if staged_mode:
        markdown_files = [
            path for path in staged_files if path.endswith(".md") or path.startswith("docs/")
        ]
        if not markdown_files:
            print("未暂存 Markdown，跳过文档格式检查")
            return 0
    else:
        markdown_files = all_markdown_files()

    failed = [False]
    for relative_path in markdown_files:
        if (REPO_ROOT / Path(relative_path)).exists():
            check_structure(relative_path, failed)

    numbered = [path for path in NUMBERED_DOCS if not staged_mode or path in markdown_files]
    for relative_path in numbered:
        check_numbered_headings(relative_path, failed)

    check_links(markdown_files, failed)
    check_global_rules(markdown_files, failed)

    if failed[0]:
        return 1
    print("文档格式检查通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
