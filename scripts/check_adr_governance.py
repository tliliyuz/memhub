#!/usr/bin/env python3
"""检查 ADR 索引边界、状态与链接，以及根级治理镜像。

只验证可机械裁决的部分：索引里出现的文件存在、编号唯一、状态词合法、每份 ADR
只有一个状态行、Markdown 链接可解析、「拟部分替代」这类未决措辞已清除。

不替代负责人裁决、规格评审或业务验收测试。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DECISIONS = REPO_ROOT / "docs" / "decisions"
INDEX = DECISIONS / "README.md"

LINK_RE = re.compile(r"\]\(([^)#\s]+)(?:#[^)]*)?\)")
NUMBER_RE = re.compile(r"^ADR-(\d{4})-")
STATUS_RE = re.compile(r"^\|\s*状态\s*\|\s*(\S+)\s*\|")
VALID_STATUS = {"proposed", "accepted", "superseded", "deprecated"}
PENDING_WORDING_RE = re.compile(r"拟部分替代|待负责人裁决为 accepted")


def report(message: str, failed: list[bool]) -> None:
    print(f"ADR 治理检查：{message}", file=sys.stderr)
    failed[0] = True


def main() -> int:
    failed = [False]
    if not INDEX.exists():
        report(f"{INDEX.relative_to(REPO_ROOT)} 不存在", failed)
        return 1

    adr_files = sorted(path for path in DECISIONS.glob("ADR-*.md"))
    if not adr_files:
        report("docs/decisions/ 下没有任何 ADR", failed)

    by_number: dict[str, list[str]] = {}
    for path in adr_files:
        number = NUMBER_RE.match(path.name)
        if number:
            by_number.setdefault(number.group(1), []).append(path.name)
    for number, names in sorted(by_number.items()):
        if len(names) > 1:
            report(
                f"ADR 编号 {number} 被 {len(names)} 份文件重复使用：{'、'.join(sorted(names))}",
                failed,
            )

    for path in adr_files:
        text = path.read_text(encoding="utf-8")
        statuses = [line for line in text.split("\n") if STATUS_RE.match(line)]
        if len(statuses) != 1:
            report(f"{path.name} 应有且仅有一个「状态」元数据行，实际 {len(statuses)} 行", failed)
            continue
        status = STATUS_RE.match(statuses[0]).group(1)
        if status not in VALID_STATUS:
            report(
                f"{path.name} 状态 {status} 不合法；只允许 {'/'.join(sorted(VALID_STATUS))}",
                failed,
            )
        if PENDING_WORDING_RE.search(text):
            report(f"{path.name} 残留未决措辞（拟部分替代/待裁决）", failed)

    index_text = INDEX.read_text(encoding="utf-8")
    linked = set()
    for match in LINK_RE.finditer(index_text):
        target = match.group(1)
        if target.startswith(("http://", "https://", "mailto:", "/", "#")):
            continue
        resolved = (INDEX.parent / target).resolve()
        if not resolved.exists():
            report(f"decisions/README.md 引用了不存在的文件 {target}", failed)
        elif resolved.parent == DECISIONS.resolve():
            linked.add(resolved.name)

    names = {path.name for path in adr_files}
    for missing in sorted(names - linked):
        report(f"{missing} 未出现在 decisions/README.md 的任何索引中", failed)
    for stale in sorted(linked - names):
        report(f"decisions/README.md 索引了不存在的 {stale}", failed)

    agents = REPO_ROOT / "AGENTS.md"
    claude = REPO_ROOT / "CLAUDE.md"
    if agents.exists() and claude.exists() and agents.read_bytes() != claude.read_bytes():
        report("AGENTS.md 与 CLAUDE.md 不一致", failed)

    if failed[0]:
        return 1
    print(f"ADR 治理检查通过（{len(adr_files)} 份 ADR，索引与状态一致）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
