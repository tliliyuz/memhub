#!/usr/bin/env python3
"""检查根级治理文档镜像是否逐字节一致。

`AGENTS.md` 与 `CLAUDE.md` 是同一份治理规范的双入口，任一文件单独变更
都意味着两个 Agent 会读到不同规则，因此只允许逐字节相同的状态。
"""

from __future__ import annotations

from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    agents = root / "AGENTS.md"
    claude = root / "CLAUDE.md"
    for path in (agents, claude):
        if not path.exists():
            print(f"{path.name} 不存在")
            return 1
    if agents.read_bytes() == claude.read_bytes():
        print("AGENTS.md 与 CLAUDE.md 镜像一致")
        return 0
    print("AGENTS.md 与 CLAUDE.md 必须逐字节一致")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
