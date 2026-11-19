#!/usr/bin/env python3
"""把旧 memhub 的 Obsidian 风格 wiki 导入新真源（一次性迁移）。

旧的 `me/wiki/<kb>/<type>/*.md` → 新的 `knowledge/<kb>/<kind>/<slug>.md`：

- type 映射：concept/source/comparison/synthesis/other → fact；entity → entity；
- 旧 frontmatter 的 `description` 作为引用块放在正文开头；`tags`/`keywords` 合并；
- `timestamp` 作为 created_at/updated_at，缺失时用文件修改时间；
- 正文里的 `[[页面名]]` 先在本库内按文件名/标题解析，解析成功的写成
  `related_to` 边；解析不到的只计数，不阻塞导入；
- 节点按 canonical 层级导入（旧 wiki 是当时的人工沉淀结果），来源记为 WIKI。

直接写文件而不走 manage.create_node：一次性迁移不需要每个节点一次 git 提交，
最后统一提交。默认幂等：目标节点已存在就跳过；`--force` 才覆盖。

用法：
    PYTHONPATH=src .venv/Scripts/python scripts/import_legacy_wiki.py \\
        --src D:/workplace/export_memhub/me/wiki --dest knowledge

    # 先看会写什么
    ... --dry-run

    # 只导一个库
    ... --projects sdp-tag
"""

from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import frontmatter

from memhub.contract import (
    Edge,
    EntityKind,
    Kind,
    NodeFrontmatter,
    Predicate,
    SourceKind,
    SourceRef,
    Tier,
)
from memhub.kb.store import KnowledgeStore

TYPE_TO_KIND: dict[str, Kind] = {
    "concept": Kind.FACT,
    "source": Kind.FACT,
    "comparison": Kind.FACT,
    "synthesis": Kind.FACT,
    "other": Kind.FACT,
    "entity": Kind.ENTITY,
}
SKIP_TYPES = {"overview", "purpose", "schema", None}
WIKILINK_RE = re.compile(r"\[\[([^\]|#]+?)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


@dataclass
class Entry:
    project: str
    source_path: Path
    relative: str
    kind: Kind
    entity_kind: EntityKind | None
    title: str
    body: str
    tags: list[str]
    timestamp: datetime
    slug: str = ""
    node_id: str = ""
    links: list[str] = field(default_factory=list)


def normalize(text: str) -> str:
    return re.sub(r"\s+", "", text).casefold()


def make_slug(stem: str, taken: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-")[:56].strip("-")
    if len(base) < 3 or not SLUG_RE.match(base):
        base = f"n-{hashlib.sha1(stem.encode('utf-8')).hexdigest()[:8]}"
    slug = base
    if slug in taken:
        slug = f"{base[:48]}-{hashlib.sha1(stem.encode('utf-8')).hexdigest()[:6]}"
    return slug


def parse_timestamp(meta: dict, path: Path) -> datetime:
    raw = meta.get("timestamp")
    if isinstance(raw, str) and raw.strip():
        try:
            return datetime.fromisoformat(raw.strip())
        except ValueError:
            pass
    return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)


def collect(project: str, project_dir: Path, src_root: Path) -> list[Entry]:
    entries: list[Entry] = []
    taken: set[str] = set()
    for path in sorted(project_dir.rglob("*.md")):
        post = frontmatter.load(path)
        meta = dict(post.metadata)
        old_type = meta.get("type")
        if old_type in SKIP_TYPES or old_type not in TYPE_TO_KIND:
            continue
        kind = TYPE_TO_KIND[str(old_type)]
        title = str(meta.get("title") or path.stem).strip()
        if not title:
            continue

        entity_kind: EntityKind | None = None
        if kind is Kind.ENTITY:
            raw_kind = str(meta.get("kind") or "").strip()
            entity_kind = next(
                (item for item in EntityKind if item.value == raw_kind), EntityKind.OTHER
            )

        tags: list[str] = []
        for key in ("tags", "keywords"):
            value = meta.get(key)
            if isinstance(value, list):
                tags.extend(str(item).strip() for item in value if str(item).strip())
            elif isinstance(value, str) and value.strip():
                tags.extend(part.strip() for part in value.split(",") if part.strip())

        body = post.content.strip()
        description = str(meta.get("description") or "").strip()
        if description and description not in body:
            body = f"> {description}\n\n{body}"
        links = [match.strip() for match in WIKILINK_RE.findall(body)]

        slug = make_slug(path.stem, taken)
        taken.add(slug)
        entries.append(
            Entry(
                project=project,
                source_path=path,
                relative=path.relative_to(src_root).as_posix(),
                kind=kind,
                entity_kind=entity_kind,
                title=title,
                body=body,
                tags=list(dict.fromkeys(tags)),
                timestamp=parse_timestamp(meta, path),
                slug=slug,
                node_id=f"{project}/{kind.value}/{slug}",
                links=links,
            )
        )
    return entries


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src", required=True, type=Path, help="旧 wiki 根目录（含 <kb>/<type>/）")
    parser.add_argument("--dest", default=Path("knowledge"), type=Path, help="新真源根目录")
    parser.add_argument("--projects", default="", help="逗号分隔的知识库；默认全部")
    parser.add_argument("--tier", default="canonical", choices=[item.value for item in Tier])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true", help="覆盖已存在的节点")
    args = parser.parse_args()

    src: Path = args.src.resolve()
    dest: Path = args.dest.resolve()
    if not src.is_dir():
        parser.error(f"--src 不存在: {src}")

    wanted = {item.strip() for item in args.projects.split(",") if item.strip()}
    projects = sorted(
        path.name for path in src.iterdir() if path.is_dir() and (not wanted or path.name in wanted)
    )
    if not projects:
        parser.error(f"{src} 下没有可导入的知识库目录")

    store = KnowledgeStore(dest)
    tier = Tier(args.tier)
    written = skipped = unresolved_links = edges_written = 0

    for project in projects:
        entries = collect(project, src / project, src)
        by_title: dict[str, str] = {}
        for entry in entries:
            by_title.setdefault(normalize(entry.title), entry.node_id)
            by_title.setdefault(normalize(entry.source_path.stem), entry.node_id)

        print(f"[{project}] 发现 {len(entries)} 个节点")
        for entry in entries:
            target = store.path_for(entry.node_id)
            if target.exists() and not args.force:
                skipped += 1
                continue
            node = NodeFrontmatter(
                id=entry.node_id,
                kind=entry.kind,
                entity_kind=entry.entity_kind,
                title=entry.title,
                tier=tier,
                project=entry.project,
                tags=entry.tags,
                source=[
                    SourceRef(
                        type=SourceKind.WIKI,
                        ref=entry.relative,
                        captured_at=entry.timestamp,
                    )
                ],
                created_at=entry.timestamp,
                updated_at=entry.timestamp,
            )
            if args.dry_run:
                print(f"  + {entry.node_id}  <- {entry.relative}")
                written += 1
                continue
            store.write(entry.node_id, node, entry.body)
            written += 1

        if args.dry_run:
            continue

        for entry in entries:
            if not store.exists(entry.node_id):
                continue
            edges: list[Edge] = []
            seen: set[str] = set()
            for link in entry.links:
                node_id = by_title.get(normalize(link))
                if not node_id or node_id == entry.node_id or node_id in seen:
                    if not node_id:
                        unresolved_links += 1
                    continue
                seen.add(node_id)
                edges.append(
                    Edge(source=entry.node_id, predicate=Predicate.RELATED_TO, target=node_id)
                )
            if edges:
                edges_written += store.append_edges(project, edges, entry.node_id)

    print(
        f"完成：写入 {written}，跳过（已存在） {skipped}，"
        f"边 {edges_written}，无法解析的链接 {unresolved_links}"
    )
    if args.dry_run:
        print("（dry-run，没有写文件）")
        return 0

    if (dest / ".git").exists() or _inside_git(dest):
        subprocess.run(
            ["git", "-C", str(dest), "add", "-A"],
            capture_output=True,
            check=False,
        )
        commit = subprocess.run(
            ["git", "-C", str(dest), "commit", "-m", "kb: import legacy wiki"],
            capture_output=True,
            text=True,
            check=False,
        )
        if commit.returncode == 0:
            print("已提交：kb: import legacy wiki")
        else:
            print(f"git 提交未完成（可忽略）：{commit.stderr.strip()[-300:]}")
    return 0


def _inside_git(path: Path) -> bool:
    probe = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    return probe.returncode == 0


if __name__ == "__main__":
    raise SystemExit(main())
