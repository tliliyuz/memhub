"""一次性迁移（markdown → PG）的解析半段：只读扫描 `knowledge/`，不写库、不删文件。

规格见 `docs/plans/kb-pg-migration-spec.md` §5。本模块只负责第 1–5 步与第 7 步的
解析侧：把磁盘上的 markdown 真源转成目标表的行，并给出 `--verify-only` 需要的
逐节点内容哈希与差异清单。任何写库、删文件、跑事务的动作都不在这里。

约定（与目标表列名对齐，不另造结构）：

- `kb_nodes` / `kb_projects` / `kb_edges` / `kb_archives` 的行分别由
  `MigrationPlan.nodes` / `projects` / `edges` / `archives` 给出，键即列名。
- `kb_archives.snapshot` 之外多带一个 `snapshot_sha256`：它是 `--verify-only`
  用来与 `active.json` 记录的摘要比对的中间值，不是表列。
- `kb_node_revisions` 的历史快照不在迁移范围（本轮只建表并在写入时落历史），
  但 `_trash` 的删除元数据（时间戳、actor、reason）必须保留下来，
  由 `MigrationPlan.trash_events` 承载，避免删除事实在迁移中丢失。
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import frontmatter
from anyio import Path as AsyncPath

from memhub.contract import NodeFrontmatter
from memhub.kb import archive
from memhub.kb.store import TRASH_DIR

REVISION_RE = re.compile(r"[0-9a-f]{16}")
STAMP_RE = re.compile(r"\d{8}T\d{6}\d*")
# `_trash/<stamp>/<node_id>.md` 里的 node_id 含 `/`，stamp 是纯数字段时间。
NODE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}/[a-z0-9]+/[a-z0-9][a-z0-9-]{0,127}$")

# 目标表没有对应列的 frontmatter 字段；非空出现即进 diff.unsupported_fields。
# `id`/`project` 由路径与首段推导、迁移后是冗余列，`supersedes` 本轮无表列。
UNSUPPORTED_FIELDS = ("supersedes",)


@dataclass
class MigrationDiff:
    """解析结果里所有「不能静默吞掉」的差异。`as_dict()` 直接可序列化给 `--verify-only`。"""

    unregistered_projects: tuple[str, ...] = ()
    missing_projects: tuple[str, ...] = ()
    dangling_edges: tuple[dict[str, str], ...] = ()
    invalid_edges: tuple[dict[str, str], ...] = ()
    invalid_nodes: tuple[dict[str, str], ...] = ()
    invalid_trash: tuple[str, ...] = ()
    invalid_archives: tuple[dict[str, str], ...] = ()
    unsupported_fields: tuple[dict[str, str], ...] = ()
    unknown_files: tuple[str, ...] = ()
    duplicate_ids: tuple[str, ...] = ()
    id_mismatches: tuple[dict[str, str], ...] = ()
    approximated_fields: tuple[dict[str, str], ...] = ()
    pending_archive: bool = False
    registry_error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "unregistered_projects": list(self.unregistered_projects),
            "missing_projects": list(self.missing_projects),
            "dangling_edges": [dict(item) for item in self.dangling_edges],
            "invalid_edges": [dict(item) for item in self.invalid_edges],
            "invalid_nodes": [dict(item) for item in self.invalid_nodes],
            "invalid_trash": list(self.invalid_trash),
            "invalid_archives": [dict(item) for item in self.invalid_archives],
            "unsupported_fields": [dict(item) for item in self.unsupported_fields],
            "unknown_files": list(self.unknown_files),
            "duplicate_ids": list(self.duplicate_ids),
            "id_mismatches": [dict(item) for item in self.id_mismatches],
            "approximated_fields": [dict(item) for item in self.approximated_fields],
            "pending_archive": self.pending_archive,
            "registry_error": self.registry_error,
        }


@dataclass
class MigrationPlan:
    """一次只读扫描的完整结果；`blocking` 为真时不允许进入写库阶段。"""

    root: Path
    projects: list[dict[str, Any]] = field(default_factory=list)
    nodes: list[dict[str, Any]] = field(default_factory=list)
    edges: list[dict[str, Any]] = field(default_factory=list)
    archives: list[dict[str, Any]] = field(default_factory=list)
    trash_events: list[dict[str, Any]] = field(default_factory=list)
    diff: MigrationDiff = field(default_factory=MigrationDiff)

    @property
    def blocking(self) -> bool:
        return (
            self.diff.pending_archive
            or self.diff.registry_error is not None
            or bool(self.diff.duplicate_ids)
            or bool(self.diff.invalid_archives)
        )


def node_revision(record: dict[str, Any]) -> str:
    """行内容哈希的前 16 位小写十六进制；与 `kb_nodes.revision` 同口径。

    序列化固定键序与 `ensure_ascii=False`，同一记录在磁盘与校验两侧必须得到
    同一个值；`snapshot_sha256` 这类解析期辅助键不参与。
    """
    payload = {
        key: value for key, value in record.items() if key not in ("snapshot_sha256", "revision")
    }
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _project_revision(kb_id: str, created_at: datetime, updated_at: datetime) -> str:
    """登记行的修订号：目标表每次写入重算，迁移侧给内容哈希保持同构。"""
    text = json.dumps(
        {"id": kb_id, "created_at": created_at.isoformat(), "updated_at": updated_at.isoformat()}
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _parse_time(value: object, default: datetime) -> datetime:
    """登记/边文件里的时间字符串（可能带 Z 或偏移）；解析不了就用默认值，不静默丢行。"""
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return default
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
    return default


async def _registry(root: Path, diff: MigrationDiff) -> dict[str, dict[str, Any]]:
    """读 `.kbs.json`；结构坏时报 registry_error 并按空登记继续（目录扫描兜底）。"""
    path = root / ".kbs.json"
    if not await AsyncPath(path).is_file():
        return {}
    try:
        raw = json.loads(await AsyncPath(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        diff.registry_error = f".kbs.json 无法读取: {exc}"
        return {}
    items = raw.get("kbs") if isinstance(raw, dict) else None
    kbs: dict[str, dict[str, Any]] = {}
    if not isinstance(items, list):
        diff.registry_error = ".kbs.json 缺少 kbs 数组"
        return {}
    for item in items:
        if isinstance(item, dict) and item.get("id"):
            kbs[str(item["id"])] = item
    return kbs


def _frontmatter_row(node_id: str, node: NodeFrontmatter, body: str) -> dict[str, Any]:
    """`NodeFrontmatter` + 正文 → `kb_nodes` 行；列名对齐规格 §3.2。"""
    row: dict[str, Any] = {
        "id": node_id,
        "project": node.project,
        "kind": node.kind.value,
        "entity_kind": node.entity_kind.value if node.entity_kind else None,
        "title": node.title,
        "tier": node.tier.value,
        "confidence": node.confidence,
        "tags": list(node.tags),
        "body": body,
        "source": [item.model_dump(mode="json") for item in node.source],
        "valid_from": node.valid_from,
        "valid_until": node.valid_until,
        "superseded_by": node.superseded_by,
        "deprecated_reason": node.deprecated_reason,
        "occurred_at": node.occurred_at,
        "decided_at": node.decided_at,
        "status": node.status.value if node.status else None,
        "created_at": node.created_at,
        "updated_at": node.updated_at,
        "archived_at": None,
        "revision": "",
    }
    unsupported = [
        {"node_id": node_id, "field": name} for name in UNSUPPORTED_FIELDS if getattr(node, name)
    ]
    return row | {"_unsupported": unsupported}


async def _trash_row(root: Path, relative: Path) -> dict[str, Any] | None:
    """`_trash/<stamp>/<node_id>.md` → 软删节点行（`archived_at` = 删除时间）。"""
    stamp_match = STAMP_RE.fullmatch(relative.parts[1])
    node_id = Path(*relative.parts[2:]).with_suffix("").as_posix()
    if stamp_match is None or not NODE_ID_RE.fullmatch(node_id):
        return None
    stamp = datetime.strptime(stamp_match.group(0), "%Y%m%dT%H%M%S%f").replace(tzinfo=UTC)
    try:
        raw = await AsyncPath(root / relative).read_text(encoding="utf-8")
    except (OSError, ValueError):
        return None
    post = frontmatter.loads(raw)
    metadata = dict(post.metadata)
    metadata["id"] = node_id
    try:
        node = NodeFrontmatter.model_validate(metadata)
    except ValueError:
        return None
    row = _frontmatter_row(node_id, node, post.content)
    row["archived_at"] = stamp
    row["revision"] = ""
    return row


async def _trash_meta(relative: Path) -> dict[str, Any]:
    path = relative.with_suffix(".meta.json")
    if not await AsyncPath(path).is_file():
        return {}
    try:
        value: dict[str, Any] = json.loads(await AsyncPath(path).read_text(encoding="utf-8"))
        return value
    except (OSError, ValueError):
        return {}


async def _scan_nodes(root: Path, diff: MigrationDiff) -> tuple[list[dict[str, Any]], list[str]]:
    """扫活跃节点（跳过 `_trash` / `_kb_archives`），返回节点行与目录上出现过的库 id。"""
    nodes: list[dict[str, Any]] = []
    seen: dict[str, Path] = {}
    projects: set[str] = set()
    async for path in AsyncPath(root).rglob("*.md"):
        relative = path.relative_to(root)
        if relative.parts[0].startswith(("_", ".")):
            continue
        node_id = relative.with_suffix("").as_posix()
        try:
            post = frontmatter.loads(await path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            diff.invalid_nodes = (*diff.invalid_nodes, {"node_id": node_id, "error": str(exc)})
            continue
        metadata = dict(post.metadata)
        metadata["id"] = node_id
        try:
            node = NodeFrontmatter.model_validate(metadata)
        except ValueError as exc:
            diff.invalid_nodes = (*diff.invalid_nodes, {"node_id": node_id, "error": str(exc)})
            continue
        if node.project != relative.parts[0]:
            diff.id_mismatches = (
                *diff.id_mismatches,
                {"node_id": node_id, "frontmatter_project": node.project},
            )
        projects.add(relative.parts[0])
        row = _frontmatter_row(node_id, node, post.content)
        diff.unsupported_fields = (*diff.unsupported_fields, *row.pop("_unsupported"))
        if node_id in seen:
            diff.duplicate_ids = (*diff.duplicate_ids, node_id)
            continue
        seen[node_id] = Path(path)
        nodes.append(row)
    async for entry in AsyncPath(root).rglob("*"):
        other = Path(entry).relative_to(root)
        if other.parts[0].startswith(("_", ".")) or other.suffix == ".md":
            continue
        if other.name == "_edges.jsonl" or await AsyncPath(entry).is_dir():
            continue
        if other.parts[0] not in {".git"}:
            diff.unknown_files = (*diff.unknown_files, other.as_posix())
    return nodes, sorted(projects)


async def _edges(
    root: Path,
    projects: list[str],
    node_ids: set[str],
    diff: MigrationDiff,
) -> list[dict[str, Any]]:
    """`<project>/_edges.jsonl` → `kb_edges` 行；悬空边原样保留并单独报出。"""
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for project in projects:
        path = root / project / "_edges.jsonl"
        if not await AsyncPath(path).is_file():
            continue
        stat = await AsyncPath(path).stat()
        # `_edges.jsonl` 每行没有时间；用文件 mtime 作为 `kb_edges.created_at`
        # （not null 列必须有值），并在文档里写清这是近似来源。
        recorded_at = datetime.fromtimestamp(stat.st_mtime, tz=UTC)
        text = await AsyncPath(path).read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                if not all(
                    isinstance(record[key], str) for key in ("source", "predicate", "target")
                ):
                    raise ValueError("字段类型")
            except (ValueError, KeyError, TypeError) as exc:
                diff.invalid_edges = (
                    *diff.invalid_edges,
                    {"path": f"{project}/_edges.jsonl", "line": str(lineno), "error": str(exc)},
                )
                continue
            key = (record["source"], record["predicate"], record["target"])
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                {
                    "project": project,
                    "source": record["source"],
                    "predicate": record["predicate"],
                    "target": record["target"],
                    "source_doc": record.get("source_doc"),
                    "created_at": recorded_at,
                }
            )
            if record["source"] not in node_ids or record["target"] not in node_ids:
                diff.dangling_edges = (
                    *diff.dangling_edges,
                    {
                        "source": record["source"],
                        "predicate": record["predicate"],
                        "target": record["target"],
                    },
                )
    return rows


async def _scan_trash(
    root: Path, diff: MigrationDiff
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """`_trash/<stamp>/` 下的软删节点：行进 nodes（archived_at 非空），元数据进 trash_events。"""
    rows: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    base = root / TRASH_DIR
    if not await AsyncPath(base).is_dir():
        return rows, events
    async for path in AsyncPath(base).rglob("*.md"):
        relative = Path(path).relative_to(root)
        row = await _trash_row(root, relative)
        if row is None:
            diff.invalid_trash = (*diff.invalid_trash, relative.as_posix())
            continue
        meta = await _trash_meta(relative)
        events.append(
            {
                "node_id": row["id"],
                "archived_at": row["archived_at"],
                "actor": str(meta.get("actor", "")),
                "reason": str(meta.get("reason", "")),
            }
        )
        rows.append(row)
    return rows, events


async def _scan_archives(root: Path, diff: MigrationDiff) -> list[dict[str, Any]]:
    """`_kb_archives/<32hex>/` 的整库归档：快照字节入 `snapshot`，哈希供 `--verify-only` 比对。"""
    rows: list[dict[str, Any]] = []
    base = root / archive.ARCHIVES
    if not await AsyncPath(base).is_dir():
        return rows
    async for folder in AsyncPath(base).iterdir():
        if not archive.ARCHIVE_ID.fullmatch(folder.name):
            continue
        active = await archive.read_optional(root / archive.ARCHIVES / folder.name / "active.json")
        snapshot = await archive.read_optional(
            root / archive.ARCHIVES / folder.name / "snapshot.zip"
        )
        if active is None or snapshot is None:
            diff.invalid_archives = (
                *diff.invalid_archives,
                {"archive_id": folder.name, "error": "active.json 或 snapshot.zip 缺失"},
            )
            continue
        try:
            index = json.loads(active)
            header = index["header"]
            digest = index["sha256"]
            if header["archive_id"] != folder.name or not isinstance(digest, str):
                raise ValueError("header")
        except (ValueError, KeyError, TypeError) as exc:
            diff.invalid_archives = (
                *diff.invalid_archives,
                {"archive_id": folder.name, "error": str(exc)},
            )
            continue
        actual = hashlib.sha256(snapshot).hexdigest()
        if actual != digest:
            diff.invalid_archives = (
                *diff.invalid_archives,
                {"archive_id": folder.name, "error": "快照哈希不符"},
            )
            continue
        try:
            deleted_at = datetime.fromisoformat(str(header["deleted_at"]))
        except ValueError:
            deleted_at = None
        rows.append(
            {
                "archive_id": str(header["archive_id"]),
                "project": str(header["id"]),
                "status": "active",
                "snapshot": snapshot,
                "snapshot_sha256": digest,
                "archived_count": int(header["archived_count"]),
                "removed_edges": int(header["removed_edges"]),
                "actor": str(header["actor"]),
                "deleted_at": deleted_at,
                "created_at": deleted_at,
                "name": str(header["name"]),
            }
        )
    return rows


async def parse_tree(root: Path) -> MigrationPlan:
    """只读扫描 `root`，产出目标表行与差异清单；不做任何写入。"""
    root = Path(root)
    diff = MigrationDiff(pending_archive=await archive.projection_dirty(root))
    registry = await _registry(root, diff)

    active_nodes, dir_projects = await _scan_nodes(root, diff)
    trash_nodes, trash_events = await _scan_trash(root, diff)

    projects: list[dict[str, Any]] = []
    now = _utc_now()
    registered = set(registry)
    for kb_id in sorted(set(dir_projects) | registered):
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", kb_id):
            diff.unknown_files = (*diff.unknown_files, kb_id)
            continue
        if kb_id not in dir_projects:
            diff.missing_projects = (*diff.missing_projects, kb_id)
            continue
        meta = registry.get(kb_id, {})
        if kb_id not in registered:
            diff.unregistered_projects = (*diff.unregistered_projects, kb_id)
        # 登记里的 created_at 是真源事实；未登记/缺值时用扫描时刻。
        created = _parse_time(meta.get("created_at"), now)
        projects.append(
            {
                "id": kb_id,
                "name": str(meta.get("name") or kb_id),
                "description": str(meta.get("description") or ""),
                "revision": "",
                "created_at": created,
                "updated_at": created,
                "archived_at": None,
            }
        )
    for project in projects:
        project["revision"] = _project_revision(
            project["id"], project["created_at"], project["updated_at"]
        )

    node_ids = {row["id"] for row in (*active_nodes, *trash_nodes)}
    edges = await _edges(root, sorted(set(dir_projects)), node_ids, diff)
    archives = await _scan_archives(root, diff)

    all_nodes = [*active_nodes, *trash_nodes]
    for row in all_nodes:
        row["revision"] = node_revision(row)

    return MigrationPlan(
        root=root,
        projects=projects,
        nodes=all_nodes,
        edges=edges,
        archives=archives,
        trash_events=trash_events,
        diff=diff,
    )
