"""生成交付清单：wheelhouse 大小 + 每个文件的 sha256。

用法：python scripts/make_release_manifest.py deploy/dist
输出写到 stdout（Markdown 表格），可直接贴给部署方核对。
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path


def release_commit() -> str:
    """清单必须自带 release commit：否则部署方无从确认 wheel 到底由哪一版构建。"""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return result.stdout.strip()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv: list[str]) -> int:
    root = Path(argv[1]) if len(argv) > 1 else Path("deploy/dist")
    if not root.is_dir():
        print(f"目录不存在: {root}", file=sys.stderr)
        return 2
    total = 0
    print(f"# 交付清单 {root}")
    print(f"\n- release commit: `{release_commit()}`")
    for wheelhouse in sorted(path for path in root.iterdir() if path.is_dir()):
        files = sorted(path for path in wheelhouse.rglob("*") if path.is_file())
        size = sum(path.stat().st_size for path in files)
        total += size
        size_mb = size / (1 << 20)
        print(f"\n## {wheelhouse.name}（{len(files)} 个文件，{size_mb:.1f} MB）")
        print("\n| 文件 | sha256 |")
        print("|:---|:---|")
        for path in files:
            print(f"| {path.relative_to(wheelhouse).as_posix()} | `{sha256(path)}` |")
    print(f"\n总计: {total / (1 << 20):.1f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
