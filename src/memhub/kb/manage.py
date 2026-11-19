"""知识库管理写操作：增删改查 + 文件锁 + 修订号 + git 提交。

真源仍是 markdown：这里只做「读 → 合并 → 原子写」。与 worker 的 merge 走同一把
进程间文件锁，避免后台提炼与人工编辑互相覆盖；写成功后在真源所在 git 仓库
（若存在）提交一次，便于回溯「谁在什么时候改了什么」。

删除不是硬删：文件移进 `_trash/<时间戳>/`，并清掉与之相连的边。投影（kg.json）
不由本模块维护，调用方写完自行 rebuild。
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from memhub.contract import (
    Edge,
    EntityKind,
    ErrorCode,
    Kind,
    NodeFrontmatter,
    Predicate,
    QuestionStatus,
    SourceKind,
    SourceRef,
    Tier,
)
from memhub.kb import query
from memhub.kb.store import KnowledgeStore

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
LOCK_NAME = ".memhub-write.lock"
LOCK_STALE_SECONDS = 120.0
TRASH_DIR = "_trash"

_log = logging.getLogger(__name__)


class ManageError(Exception):
    """管理端错误；`status` 映射 HTTP，`code` 是契约业务码。"""

    status = 400
    code = ErrorCode.KB_INVALID

    def __init__(self, message: str, data: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.data = data or {}


class NotFoundError(ManageError):
    status = 404
    code = ErrorCode.KB_NOT_FOUND


class ConflictError(ManageError):
    status = 409
    code = ErrorCode.KB_CONFLICT


class InvalidError(ManageError):
    status = 422
    code = ErrorCode.KB_INVALID


# ---------------------------------------------------------------- 锁与修订号


@contextmanager
def write_lock(root: Path, *, timeout: float = 10.0) -> Iterator[None]:
    """跨进程写锁（单主机）。

    用 O_EXCL 建锁文件；超过 `LOCK_STALE_SECONDS` 的锁视为崩溃残留并接管。
    这足够保护「worker 与 kb-api 同机」的当前形态；未来多机写同一真源时
    应换成基于 git 的乐观并发。
    """
    path = root / LOCK_NAME
    deadline = time.monotonic() + timeout
    fd = -1
    while True:
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, f"{os.getpid()} {time.time():.0f}".encode())
            break
        except FileExistsError:
            try:
                age = time.time() - path.stat().st_mtime
            except OSError:
                age = 0.0
            if age > LOCK_STALE_SECONDS:
                path.unlink(missing_ok=True)
                continue
            if time.monotonic() >= deadline:
                raise ConflictError(
                    "真源正被其他进程写入（worker 或另一个管理端请求），稍后重试",
                    {"lock": str(path), "age_seconds": round(age, 1)},
                ) from None
            time.sleep(0.05)
    try:
        yield
    finally:
        os.close(fd)
        path.unlink(missing_ok=True)


def revision_of(path: Path) -> str:
    """修订号 = 文件内容 sha256 前 16 位；用于乐观并发（ETag）。"""
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def node_revision(store: KnowledgeStore, node_id: str) -> str | None:
    path = store.path_for(node_id)
    return revision_of(path) if path.is_file() else None


# ---------------------------------------------------------------- 列表与详情


def _summary(store: KnowledgeStore, record: query.NodeRecord) -> dict[str, Any]:
    node = record.node
    return {
        "id": record.id,
        "kind": node.kind.value,
        "entity_kind": node.entity_kind.value if node.entity_kind else None,
        "title": node.title,
        "tier": node.tier.value,
        "project": node.project,
        "tags": node.tags,
        "confidence": node.confidence,
        "status": node.status.value if node.status else None,
        "created_at": node.created_at.isoformat(),
        "updated_at": node.updated_at.isoformat(),
        "revision": node_revision(store, record.id),
        "body_chars": len(record.body),
    }


def list_nodes(
    store: KnowledgeStore,
    *,
    project: str | None = None,
    kind: str | None = None,
    tier: str | None = None,
    q: str | None = None,
    tag: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    terms = query.terms(q) if q and q.strip() else []
    items: list[dict[str, Any]] = []
    for record in query.records(store, project):
        if kind and record.node.kind.value != kind:
            continue
        if tier and tier != "all" and record.node.tier.value != tier:
            continue
        if tag and tag not in record.node.tags:
            continue
        if terms and query.score(record, terms) <= 0:
            continue
        items.append(_summary(store, record))
    items.sort(key=lambda item: str(item["updated_at"]), reverse=True)
    return {
        "items": items[offset : offset + limit],
        "total": len(items),
        "offset": offset,
        "limit": limit,
    }


def stats(store: KnowledgeStore) -> dict[str, Any]:
    by_kind: dict[str, int] = {}
    by_tier: dict[str, int] = {}
    by_project: dict[str, int] = {}
    for record in query.records(store):
        kind = record.node.kind.value
        tier = record.node.tier.value
        by_kind[kind] = by_kind.get(kind, 0) + 1
        by_tier[tier] = by_tier.get(tier, 0) + 1
        by_project[record.node.project] = by_project.get(record.node.project, 0) + 1
    index = query.edge_index(store)
    return {
        "nodes": sum(by_kind.values()),
        "edges": len(index.edges),
        "unresolved_edges": len(index.unresolved),
        "orphans": sum(
            1 for record in query.records(store) if index.incident.get(record.id, 0) == 0
        ),
        "by_kind": dict(sorted(by_kind.items())),
        "by_tier": dict(sorted(by_tier.items())),
        "by_project": dict(sorted(by_project.items())),
    }


def get_node(store: KnowledgeStore, node_id: str) -> dict[str, Any]:
    try:
        detail = query.read_node(store, node_id)
    except query.NotFound as exc:
        raise NotFoundError(exc.args[0] if exc.args else f"节点不存在: {node_id}") from exc
    detail["revision"] = node_revision(store, node_id)
    return detail


# ---------------------------------------------------------------- 创建与更新


@dataclass
class NodeDraft:
    kind: Kind
    title: str
    body: str = ""
    project: str = "memhub"
    tier: Tier = Tier.CANDIDATE
    tags: list[str] = field(default_factory=list)
    entity_kind: EntityKind | None = None
    confidence: float | None = None
    status: QuestionStatus | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    occurred_at: datetime | None = None
    decided_at: datetime | None = None
    slug: str | None = None
    actor: str = "ui"
    supersedes: list[str] = field(default_factory=list)


def slugify(title: str) -> str:
    """标题 → kebab-case；无法收敛（纯中文等）时返回空串，由调用方兜底。"""
    slug = re.sub(r"[^a-z0-9]+", "-", title.strip().lower()).strip("-")
    return slug[:64].strip("-") if SLUG_RE.match(slug) else ""


def _brief_errors(exc: ValidationError) -> list[dict[str, Any]]:
    """只留 loc/msg/type：pydantic 的 `input` 可能含枚举与 datetime，不是 JSON 安全的。"""
    return [
        {
            "loc": list(error.get("loc", ())),
            "msg": error.get("msg", ""),
            "type": error.get("type", ""),
        }
        for error in exc.errors(include_url=False)
    ]


def _manual_source(actor: str) -> SourceRef:
    return SourceRef(type=SourceKind.MANUAL, ref=f"ui:{actor}", captured_at=datetime.now(UTC))


def _validate_path_parts(project: str, kind: str, slug: str) -> None:
    if not SLUG_RE.match(project):
        raise InvalidError(f"project 不合法: {project!r}（小写字母/数字/连字符）")
    if not SLUG_RE.match(slug):
        raise InvalidError(f"slug 不合法: {slug!r}（小写字母/数字/连字符）")
    if kind not in {item.value for item in Kind}:
        raise InvalidError(f"kind 不合法: {kind!r}")


def create_node(store: KnowledgeStore, draft: NodeDraft) -> dict[str, Any]:
    slug = draft.slug or slugify(draft.title) or f"n-{os.urandom(4).hex()}"
    _validate_path_parts(draft.project, draft.kind.value, slug)
    node_id = f"{draft.project}/{draft.kind.value}/{slug}"
    now = datetime.now(UTC)
    with write_lock(store.root):
        if store.exists(node_id):
            raise ConflictError(f"节点已存在: {node_id}", {"id": node_id})
        node = _build_node(
            node_id,
            draft,
            created_at=now,
        )
        store.write(node_id, node, draft.body)
        commit = _git_commit(store.root, f"kb: create {node_id}")
    return {
        "id": node_id,
        "revision": node_revision(store, node_id),
        "commit": commit,
        "node": get_node(store, node_id),
    }


def _build_node(
    node_id: str,
    draft: NodeDraft,
    *,
    created_at: datetime,
    updated_at: datetime | None = None,
) -> NodeFrontmatter:
    try:
        return NodeFrontmatter(
            id=node_id,
            kind=draft.kind,
            entity_kind=draft.entity_kind,
            title=draft.title,
            tier=draft.tier,
            confidence=draft.confidence,
            project=draft.project,
            tags=draft.tags,
            source=[_manual_source(draft.actor)],
            created_at=created_at,
            updated_at=updated_at or created_at,
            valid_from=draft.valid_from,
            valid_until=draft.valid_until,
            supersedes=draft.supersedes,
            occurred_at=draft.occurred_at,
            decided_at=draft.decided_at,
            status=draft.status,
        )
    except ValidationError as exc:
        raise InvalidError("frontmatter 校验失败", {"errors": _brief_errors(exc)}) from exc


@dataclass
class NodePatch:
    title: str | None = None
    body: str | None = None
    tags: list[str] | None = None
    tier: Tier | None = None
    confidence: float | None = None
    status: QuestionStatus | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    occurred_at: datetime | None = None
    decided_at: datetime | None = None
    superseded_by: str | None = None
    actor: str = "ui"


def update_node(
    store: KnowledgeStore,
    node_id: str,
    *,
    expected_revision: str,
    patch: NodePatch,
) -> dict[str, Any]:
    with write_lock(store.root):
        if not store.exists(node_id):
            raise NotFoundError(f"节点不存在: {node_id}")
        current = node_revision(store, node_id)
        if current != expected_revision:
            raise ConflictError(
                "节点已被其他人/进程修改，请刷新后重试",
                {"expected": expected_revision, "current": current},
            )
        node, body = store.read(node_id)
        data = node.model_dump(mode="json")
        data["updated_at"] = datetime.now(UTC)
        if patch.title is not None:
            data["title"] = patch.title
        if patch.tags is not None:
            data["tags"] = patch.tags
        if patch.tier is not None:
            data["tier"] = patch.tier
        if patch.confidence is not None:
            data["confidence"] = patch.confidence
        if patch.status is not None:
            data["status"] = patch.status
        for field_name in ("valid_from", "valid_until", "occurred_at", "decided_at"):
            value = getattr(patch, field_name)
            if value is not None:
                data[field_name] = value
        if patch.superseded_by is not None:
            data["superseded_by"] = patch.superseded_by
        data["id"] = node_id
        try:
            updated = NodeFrontmatter.model_validate(data)
        except ValidationError as exc:
            raise InvalidError("frontmatter 校验失败", {"errors": _brief_errors(exc)}) from exc
        new_body = body if patch.body is None else patch.body
        store.write(node_id, updated, new_body)
        commit = _git_commit(store.root, f"kb: update {node_id}")
    return {
        "id": node_id,
        "revision": node_revision(store, node_id),
        "commit": commit,
        "node": get_node(store, node_id),
    }


# ---------------------------------------------------------------- 废弃与删除


def deprecate_node(
    store: KnowledgeStore,
    node_id: str,
    *,
    superseded_by: str,
    reason: str = "",
    actor: str = "ui",
) -> dict[str, Any]:
    if not superseded_by:
        raise InvalidError("superseded_by 必须给出替代节点的 id")
    with write_lock(store.root):
        if not store.exists(node_id):
            raise NotFoundError(f"节点不存在: {node_id}")
        if superseded_by != node_id and not store.exists(superseded_by):
            raise InvalidError(f"替代节点不存在: {superseded_by}")
        node, body = store.read(node_id)
        data = node.model_dump(mode="json")
        data["tier"] = Tier.DEPRECATED
        data["superseded_by"] = superseded_by
        data["updated_at"] = datetime.now(UTC)
        data["id"] = node_id
        try:
            updated = NodeFrontmatter.model_validate(data)
        except ValidationError as exc:
            raise InvalidError("frontmatter 校验失败", {"errors": _brief_errors(exc)}) from exc
        if reason.strip():
            body = body.rstrip() + f"\n\n## 废弃说明\n\n{reason.strip()}（{actor}）\n"
        store.write(node_id, updated, body)
        commit = _git_commit(store.root, f"kb: deprecate {node_id}")
    return {
        "id": node_id,
        "revision": node_revision(store, node_id),
        "commit": commit,
        "node": get_node(store, node_id),
    }


def delete_node(
    store: KnowledgeStore,
    node_id: str,
    *,
    expected_revision: str,
    reason: str = "",
    actor: str = "ui",
) -> dict[str, Any]:
    """归档到 `_trash/<时间戳>/` 并清掉相连的边；可从回收站恢复。"""
    with write_lock(store.root):
        if not store.exists(node_id):
            raise NotFoundError(f"节点不存在: {node_id}")
        current = node_revision(store, node_id)
        if current != expected_revision:
            raise ConflictError(
                "节点已被其他人/进程修改，请刷新后重试",
                {"expected": expected_revision, "current": current},
            )
        node, _ = store.read(node_id)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
        folder = store.root / TRASH_DIR / stamp
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"{node_id}.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(store.path_for(node_id)), str(target))
        meta = {
            "id": node_id,
            "title": node.title,
            "kind": node.kind.value,
            "project": node.project,
            "deleted_at": datetime.now(UTC).isoformat(),
            "reason": reason,
            "actor": actor,
        }
        (folder / f"{node_id}.meta.json").parent.mkdir(parents=True, exist_ok=True)
        (folder / f"{node_id}.meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        removed_edges = _remove_incident_edges(store, node_id)
        commit = _git_commit(store.root, f"kb: delete {node_id} (archived to _trash/{stamp})")
    return {
        "id": node_id,
        "trash": f"{stamp}/{node_id}",
        "removed_edges": removed_edges,
        "commit": commit,
    }


def list_trash(store: KnowledgeStore, *, limit: int = 100) -> dict[str, Any]:
    base = store.root / TRASH_DIR
    items: list[dict[str, Any]] = []
    if base.is_dir():
        for meta_path in sorted(base.rglob("*.meta.json"), reverse=True):
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            meta["trash"] = meta_path.relative_to(base).with_suffix("").with_suffix("").as_posix()
            items.append(meta)
    return {"items": items[: max(1, min(limit, 500))], "total": len(items)}


def restore_node(store: KnowledgeStore, trash: str) -> dict[str, Any]:
    base = (store.root / TRASH_DIR).resolve()
    parts = trash.split("/")
    if len(parts) < 2 or any(part in {"", ".", ".."} or "\\" in part for part in parts):
        raise InvalidError(f"trash 路径不合法: {trash!r}")
    stamp = parts[0]
    node_id = "/".join(parts[1:])
    source = (base / stamp / f"{node_id}.md").resolve()
    if not source.is_file() or base not in source.parents:
        raise NotFoundError(f"回收站里没有: {trash}")
    with write_lock(store.root):
        if store.exists(node_id):
            raise ConflictError(f"节点已重新存在，无法恢复: {node_id}", {"id": node_id})
        target = store.path_for(node_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(target))
        meta = source.with_suffix(".meta.json")
        if meta.is_file():
            meta.unlink()
        commit = _git_commit(store.root, f"kb: restore {node_id}")
    return {"id": node_id, "revision": node_revision(store, node_id), "commit": commit}


# ---------------------------------------------------------------- 边编辑


def _resolver(store: KnowledgeStore, *, include: str | None = None) -> Callable[[str], str | None]:
    ids = set(store.list_ids())
    if include is not None:
        # 删除时文件已移入 _trash，解析器要把它当成「仍存在」才能找到相连的边。
        ids.add(include)
    slug_index: dict[str, list[str]] = {}
    for node_id in ids:
        slug_index.setdefault(node_id.rsplit("/", 1)[-1], []).append(node_id)

    def resolve(reference: str) -> str | None:
        if reference in ids:
            return reference
        candidates = slug_index.get(reference, [])
        return candidates[0] if len(candidates) == 1 else None

    return resolve


def _edge_files(store: KnowledgeStore) -> list[Path]:
    return sorted(store.root.rglob("_edges.jsonl"))


def _remove_incident_edges(store: KnowledgeStore, node_id: str) -> int:
    """删掉与 node_id 相连的边（源或目标解析到它）。返回删除条数。"""
    resolve = _resolver(store, include=node_id)
    removed = 0
    for path in _edge_files(store):
        kept: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            source = resolve(str(record["source"]))
            target = resolve(str(record["target"]))
            if source == node_id or target == node_id:
                removed += 1
                continue
            kept.append(record)
        text = "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in kept)
        path.write_text(text, encoding="utf-8", newline="\n")
    return removed


def replace_out_edges(
    store: KnowledgeStore,
    node_id: str,
    edges: list[Edge],
) -> dict[str, Any]:
    """用给定列表替换 node_id 的出边；入边不动。"""
    if not store.exists(node_id):
        raise NotFoundError(f"节点不存在: {node_id}")
    node, _ = store.read(node_id)
    valid_predicates = {item.value for item in Predicate}
    for edge in edges:
        if edge.source != node_id:
            raise InvalidError(f"边的 source 必须是 {node_id}，收到 {edge.source}")
        if edge.predicate.value not in valid_predicates:
            raise InvalidError(f"predicate 不合法: {edge.predicate}")
    with write_lock(store.root):
        _drop_out_edges(store, node_id)
        added = store.append_edges(node.project, edges, node_id) if edges else 0
        commit = _git_commit(store.root, f"kb: edit edges of {node_id}")
    return {"id": node_id, "added": added, "commit": commit}


def _drop_out_edges(store: KnowledgeStore, node_id: str) -> int:
    resolve = _resolver(store)
    removed = 0
    for path in _edge_files(store):
        kept: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            if resolve(str(record["source"])) == node_id:
                removed += 1
                continue
            kept.append(record)
        path.write_text(
            "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in kept),
            encoding="utf-8",
            newline="\n",
        )
    return removed


# ---------------------------------------------------------------- git 提交


def _find_git_root(path: Path) -> Path | None:
    for candidate in [path, *path.parents]:
        if (candidate / ".git").exists():
            return candidate
    return None


def _git_commit(root: Path, message: str) -> str | None:
    """真源所在的 git 仓库存在时提交一次；任何失败都不影响写操作本身。"""
    repo = _find_git_root(root.resolve())
    if repo is None:
        return None
    try:
        relative = root.resolve().relative_to(repo).as_posix()
        # 锁文件是运行时状态，不能进真源的历史。
        subprocess.run(
            [
                "git",
                "-C",
                str(repo),
                "add",
                "-A",
                "--",
                relative,
                f":(exclude){relative}/{LOCK_NAME}",
            ],
            check=True,
            capture_output=True,
            timeout=30,
        )
        staged = subprocess.run(
            ["git", "-C", str(repo), "diff", "--cached", "--quiet", "--", relative],
            check=False,
            capture_output=True,
            timeout=30,
        )
        if staged.returncode == 0:
            return None
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-m", message, "--", relative],
            check=True,
            capture_output=True,
            timeout=60,
        )
        head = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--short", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return head.stdout.strip() or None
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or b"").decode("utf-8", "replace").strip()
        _log.warning("git 提交失败（%s）：%s", exc.cmd[-1], detail[-800:] or exc.returncode)
        return None
    except (OSError, subprocess.SubprocessError) as exc:
        _log.warning("git 提交失败：%s", exc)
        return None
