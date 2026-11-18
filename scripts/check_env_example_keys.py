#!/usr/bin/env python3
"""检查 `.env.example` 与 `docs/tech/ENVIRONMENT.md` 的键集是否双向一致。

部署面环境变量只在 ENVIRONMENT.md §2 列全，`.env.example` 是这份清单的部署侧
投影，两者的键集必须相等。任一方向多键或少键都意味着事实无处可查或部署方无从
设置，因此本检查双向进行：

- 模板里的每个键必须出现在清单的键行中；
- 清单键行里的每个键必须出现在模板中。

只判定键集边界，不检查默认值、读取方与失败语义是否描述正确——那些是文档内容，
不是本脚本能机械裁决的。键行形态：模板接受 `KEY=值` 与 `# KEY=值` 两种写法，
清单侧以 `` | `KEY` | `` 开头的表格行计。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ENV_EXAMPLE = ".env.example"
ENVIRONMENT_DOC = "docs/tech/ENVIRONMENT.md"
ENV_KEY_RE = re.compile(r"^(?:# ?)?([A-Z][A-Z0-9_]*)=")
DOC_KEY_RE = re.compile(r"^\|\s*`([A-Z][A-Z0-9_]*)`\s*\|")


def report(message: str, failed: list[bool]) -> None:
    print(f"环境变量键集检查：{message}", file=sys.stderr)
    failed[0] = True


def read_keys(relative_path: str, pattern: re.Pattern[str], failed: list[bool]) -> set[str]:
    try:
        text = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
    except FileNotFoundError:
        report(f"{relative_path} 不存在", failed)
        return set()
    except (OSError, UnicodeError) as exc:
        report(f"{relative_path} 无法读取：{exc}", failed)
        return set()
    keys: set[str] = set()
    for raw_line in text.split("\n"):
        match = pattern.match(raw_line.rstrip("\r"))
        if match:
            keys.add(match.group(1))
    return keys


def main() -> int:
    failed = [False]
    env_keys = read_keys(ENV_EXAMPLE, ENV_KEY_RE, failed)
    doc_keys = read_keys(ENVIRONMENT_DOC, DOC_KEY_RE, failed)
    if failed[0]:
        return 1
    if not env_keys or not doc_keys:
        report(
            f"键集为空（{ENV_EXAMPLE} {len(env_keys)} 键、{ENVIRONMENT_DOC} {len(doc_keys)} 键）；"
            "键行形态见 ENVIRONMENT.md §2，两侧都应为空时说明解析规则已与文档脱节",
            failed,
        )
        return 1

    for key in sorted(env_keys - doc_keys):
        report(f"{ENV_EXAMPLE} 的 {key} 未出现在 {ENVIRONMENT_DOC} 的键清单中", failed)
    for key in sorted(doc_keys - env_keys):
        report(f"{ENVIRONMENT_DOC} 的 {key} 未出现在 {ENV_EXAMPLE} 中", failed)
    if failed[0]:
        return 1

    print(f"环境变量键集检查通过（{len(env_keys)} 键双向一致）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
