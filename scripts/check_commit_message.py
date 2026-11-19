#!/usr/bin/env python3
"""拒绝任何 Co-Authored-By 署名。

`docs/guides/DEVELOPMENT.md` §5 要求提交信息只描述实际改动，不加署名行（不区分署名工具）。
本脚本挂在 commit-msg 阶段，读取 Git 传入的提交信息文件路径作为唯一参数。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

SIGNATURE_RE = re.compile(r"^co-authored-by:", re.IGNORECASE | re.MULTILINE)


def main(argv: list[str]) -> int:
    if not argv:
        print("用法：check_commit_message.py <commit-msg-file>", file=sys.stderr)
        return 1
    path = Path(argv[0])
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print(f"无法读取提交信息：{exc}", file=sys.stderr)
        return 1
    if SIGNATURE_RE.search(text):
        print(
            "提交信息含 Co-Authored-By 署名（不区分署名工具），被 DEVELOPMENT §5 禁止。请移除署名后重试。",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
