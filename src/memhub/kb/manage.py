"""知识库管理写操作：增删改查 + 文件锁 + 修订号 + git 提交（全异步 IO）。

真源仍是 markdown：这里只做「读 → 合并 → 原子写」。与 worker 的 merge 走同一把
进程间文件锁，避免后台提炼与人工编辑互相覆盖；写成功后在真源所在 git 仓库
（若存在）提交一次，便于回溯「谁在什么时候改了什么」。

删除不是硬删：文件移进 `_trash/<时间戳>/`，并清掉与之相连的边。投影（kg.json）
不由本模块维护，调用方写完自行 rebuild。
"""

from __future__ import annotations

import errno
import json
import logging
import os
import re
import sys
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import anyio
from anyio import Path as AsyncPath
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
    valid_project,
)
from memhub.kb import proc, query
from memhub.kb.store import TRASH_DIR, KnowledgeStore

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
# 独立于旧版 O_EXCL 锁文件；回退时旧版不受持久锁文件影响（不可混跑）。
LOCK_NAME = ".memhub-write-v2.lock"
_LEGACY_LOCK_NAME = ".memhub-write.lock"
_ARCHIVE_STATE_DIR = "_kb_archives"

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


class WriteDeferred(ConflictError):
    """写入需要等待；不是输入失败，不应消耗 worker 的重试次数。"""

    def __init__(
        self, message: str, data: dict[str, Any] | None = None, *, reason: str | None = None
    ) -> None:
        super().__init__(message, data)
        self.reason = reason


class InvalidError(ManageError):
    status = 422
    code = ErrorCode.KB_INVALID


# ---------------------------------------------------------------- 锁与修订号


def _try_write_lock(fd: int) -> bool:
    if sys.platform == "win32":
        import msvcrt

        try:
            # 文件打开后偏移为零；锁范围可超出 EOF，无需写入占位字节。
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            if exc.errno != errno.EACCES:
                raise
            return False
    else:
        import fcntl

        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
    return True


async def _archive_state_exists(path: Path) -> bool:
    try:
        await AsyncPath(path).lstat()
    except FileNotFoundError:
        return False
    return True


@asynccontextmanager
async def write_lock(
    root: Path, *, timeout: float = 10.0, recovery: bool = False
) -> AsyncIterator[None]:
    """单主机跨进程写锁。正常退出、取消或进程死亡时，关闭句柄即释放。

    锁文件不可删除或替换，否则不同进程可能锁住不同文件。等待用 async sleep，
    不依赖文件年龄。只有恢复归档事务的调用方可以绕过待恢复日志。
    """
    path = root / LOCK_NAME
    await AsyncPath(root).mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout
    # 保护句柄交接与关闭，避免取消后留下无人持有的开文件句柄。
    with anyio.CancelScope(shield=True):
        handle = await AsyncPath(path).open("a+b")
    try:
        # Windows 的字节范围锁从当前偏移开始；始终锁同一字节。
        await handle.seek(0)
        fd = handle.wrapped.fileno()
        while not await anyio.to_thread.run_sync(_try_write_lock, fd):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise WriteDeferred(
                    "真源正被其他进程写入（worker 或另一个管理端请求），稍后重试",
                    {"lock": str(path)},
                    reason="busy",
                )
            await anyio.sleep(min(remaining, 0.05))
        pending = root / _ARCHIVE_STATE_DIR / "pending.json"
        if not recovery and await _archive_state_exists(pending):
            raise WriteDeferred(
                "有未恢复的知识库归档事务，暂不能写入真源",
                reason="pending",
            )
        yield
    finally:
        with anyio.CancelScope(shield=True):
            await handle.aclose()


async def guard_project_write(root: Path, project: str) -> None:
    """在持有写锁时，检查项目是否仍被归档阻止写入。"""
    if not valid_project(project):
        raise InvalidError(f"project 不合法: {project!r}")
    marker = root / _ARCHIVE_STATE_DIR / "blocked" / project
    if await _archive_state_exists(marker):
        raise WriteDeferred(
            f"知识库 {project} 已归档，恢复后才能写入",
            {"project": project},
            reason="archived",
        )


async def revision_of(path: Path) -> str:
    """修订号 = 文件内容 sha256 前 16 位；用于乐观并发（ETag）。"""
    import hashlib

    return hashlib.sha256(await AsyncPath(path).read_bytes()).hexdigest()[:16]


async def node_revision(store: KnowledgeStore, node_id: str) -> str | None:
    path = store.path_for(node_id)
    return await revision_of(path) if await AsyncPath(path).is_file() else None


# ---------------------------------------------------------------- 列表与详情


async def _summary(store: KnowledgeStore, record: query.NodeRecord) -> dict[str, Any]:
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
        "revision": await node_revision(store, record.id),
        "body_chars": len(record.body),
    }


async def list_nodes(
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
    for record in await query.records(store, project):
        if kind and record.node.kind.value != kind:
            continue
        if tier and tier != "all" and record.node.tier.value != tier:
            continue
        if tag and tag not in record.node.tags:
            continue
        if terms and query.score(record, terms) <= 0:
            continue
        items.append(await _summary(store, record))
    items.sort(key=lambda item: str(item["updated_at"]), reverse=True)
    return {
        "items": items[offset : offset + limit],
        "total": len(items),
        "offset": offset,
        "limit": limit,
    }


async def stats(store: KnowledgeStore) -> dict[str, Any]:
    by_kind: dict[str, int] = {}
    by_tier: dict[str, int] = {}
    by_project: dict[str, int] = {}
    records = await query.records(store)
    for record in records:
        kind = record.node.kind.value
        tier = record.node.tier.value
        by_kind[kind] = by_kind.get(kind, 0) + 1
        by_tier[tier] = by_tier.get(tier, 0) + 1
        by_project[record.node.project] = by_project.get(record.node.project, 0) + 1
    index = await query.edge_index(store)
    return {
        "nodes": sum(by_kind.values()),
        "edges": len(index.edges),
        "unresolved_edges": len(index.unresolved),
        "orphans": sum(1 for record in records if index.incident.get(record.id, 0) == 0),
        "by_kind": dict(sorted(by_kind.items())),
        "by_tier": dict(sorted(by_tier.items())),
        "by_project": dict(sorted(by_project.items())),
    }


async def get_node(store: KnowledgeStore, node_id: str) -> dict[str, Any]:
    try:
        detail = await query.read_node(store, node_id)
    except query.NotFound as exc:
        raise NotFoundError(exc.args[0] if exc.args else f"节点不存在: {node_id}") from exc
    detail["revision"] = await node_revision(store, node_id)
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


async def create_node(store: KnowledgeStore, draft: NodeDraft) -> dict[str, Any]:
    slug = draft.slug or slugify(draft.title) or f"n-{os.urandom(4).hex()}"
    _validate_path_parts(draft.project, draft.kind.value, slug)
    node_id = f"{draft.project}/{draft.kind.value}/{slug}"
    now = datetime.now(UTC)
    async with write_lock(store.root):
        await guard_project_write(store.root, draft.project)
        if await store.exists(node_id):
            raise ConflictError(f"节点已存在: {node_id}", {"id": node_id})
        node = _build_node(
            node_id,
            draft,
            created_at=now,
        )
        await store.write(node_id, node, draft.body)
        commit = await _git_commit(store.root, f"kb: create {node_id}")
    return {
        "id": node_id,
        "revision": await node_revision(store, node_id),
        "commit": commit,
        "node": await get_node(store, node_id),
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


async def update_node(
    store: KnowledgeStore,
    node_id: str,
    *,
    expected_revision: str,
    patch: NodePatch,
) -> dict[str, Any]:
    async with write_lock(store.root):
        if not await store.exists(node_id):
            raise NotFoundError(f"节点不存在: {node_id}")
        current = await node_revision(store, node_id)
        if current != expected_revision:
            raise ConflictError(
                "节点已被其他人/进程修改，请刷新后重试",
                {"expected": expected_revision, "current": current},
            )
        node, body = await store.read(node_id)
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
        await store.write(node_id, updated, new_body)
        commit = await _git_commit(store.root, f"kb: update {node_id}")
    return {
        "id": node_id,
        "revision": await node_revision(store, node_id),
        "commit": commit,
        "node": await get_node(store, node_id),
    }


# ---------------------------------------------------------------- 废弃与删除


async def deprecate_node(
    store: KnowledgeStore,
    node_id: str,
    *,
    superseded_by: str,
    reason: str = "",
    actor: str = "ui",
) -> dict[str, Any]:
    if not superseded_by:
        raise InvalidError("superseded_by 必须给出替代节点的 id")
    async with write_lock(store.root):
        if not await store.exists(node_id):
            raise NotFoundError(f"节点不存在: {node_id}")
        if superseded_by != node_id and not await store.exists(superseded_by):
            raise InvalidError(f"替代节点不存在: {superseded_by}")
        node, body = await store.read(node_id)
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
        await store.write(node_id, updated, body)
        commit = await _git_commit(store.root, f"kb: deprecate {node_id}")
    return {
        "id": node_id,
        "revision": await node_revision(store, node_id),
        "commit": commit,
        "node": await get_node(store, node_id),
    }


async def delete_node(
    store: KnowledgeStore,
    node_id: str,
    *,
    expected_revision: str,
    reason: str = "",
    actor: str = "ui",
) -> dict[str, Any]:
    """归档到 `_trash/<时间戳>/` 并清掉相连的边；可从回收站恢复。"""
    async with write_lock(store.root):
        if not await store.exists(node_id):
            raise NotFoundError(f"节点不存在: {node_id}")
        current = await node_revision(store, node_id)
        if current != expected_revision:
            raise ConflictError(
                "节点已被其他人/进程修改，请刷新后重试",
                {"expected": expected_revision, "current": current},
            )
        node, _ = await store.read(node_id)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
        folder = store.root / TRASH_DIR / stamp
        await AsyncPath(folder).mkdir(parents=True, exist_ok=True)
        target = folder / f"{node_id}.md"
        await AsyncPath(target.parent).mkdir(parents=True, exist_ok=True)
        await AsyncPath(store.path_for(node_id)).replace(target)
        meta = {
            "id": node_id,
            "title": node.title,
            "kind": node.kind.value,
            "project": node.project,
            "deleted_at": datetime.now(UTC).isoformat(),
            "reason": reason,
            "actor": actor,
        }
        meta_path = folder / f"{node_id}.meta.json"
        await AsyncPath(meta_path.parent).mkdir(parents=True, exist_ok=True)
        await AsyncPath(meta_path).write_text(
            json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        removed_edges = await _remove_incident_edges(store, node_id)
        commit = await _git_commit(store.root, f"kb: delete {node_id} (archived to _trash/{stamp})")
    return {
        "id": node_id,
        "trash": f"{stamp}/{node_id}",
        "removed_edges": removed_edges,
        "commit": commit,
    }


async def list_trash(
    store: KnowledgeStore,
    *,
    limit: int = 100,
    offset: int = 0,
    project: str | None = None,
    q: str | None = None,
) -> dict[str, Any]:
    base = store.root / TRASH_DIR
    items: list[dict[str, Any]] = []
    if await AsyncPath(base).is_dir():
        paths = [path async for path in AsyncPath(base).rglob("*.meta.json")]
        for meta_path in sorted(paths, key=str, reverse=True):
            try:
                meta = json.loads(await meta_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            relative = Path(meta_path).relative_to(base)
            meta["trash"] = relative.with_suffix("").with_suffix("").as_posix()
            items.append(meta)
    total_all = len(items)
    if project:
        items = [item for item in items if item.get("project") == project]
    if q:
        needle = q.casefold()
        items = [
            item
            for item in items
            if needle in str(item.get("title", "")).casefold()
            or needle in str(item.get("id", "")).casefold()
        ]
    offset = max(0, offset)
    page = items[offset : offset + max(1, min(limit, 500))]
    return {"items": page, "total": len(items), "offset": offset, "total_all": total_all}


async def restore_node(store: KnowledgeStore, trash: str) -> dict[str, Any]:
    parts = trash.split("/")
    if len(parts) < 2 or any(part in {"", ".", ".."} or "\\" in part for part in parts):
        raise InvalidError(f"trash 路径不合法: {trash!r}")
    stamp = parts[0]
    node_id = "/".join(parts[1:])
    async with write_lock(store.root):
        await guard_project_write(store.root, parts[1])
        base = Path(await AsyncPath(store.root / TRASH_DIR).resolve())
        source = Path(await AsyncPath(base / stamp / f"{node_id}.md").resolve())
        if not await AsyncPath(source).is_file() or base not in source.parents:
            raise NotFoundError(f"回收站里没有: {trash}")
        if await store.exists(node_id):
            raise ConflictError(f"节点已重新存在，无法恢复: {node_id}", {"id": node_id})
        target = store.path_for(node_id)
        await AsyncPath(target.parent).mkdir(parents=True, exist_ok=True)
        await AsyncPath(source).replace(target)
        meta = source.with_suffix(".meta.json")
        if await AsyncPath(meta).is_file():
            await AsyncPath(meta).unlink()
        commit = await _git_commit(store.root, f"kb: restore {node_id}")
    return {
        "id": node_id,
        "revision": await node_revision(store, node_id),
        "commit": commit,
    }


# ---------------------------------------------------------------- 边编辑


async def _resolver(
    store: KnowledgeStore, *, include: str | set[str] | None = None
) -> Callable[[str], str | None]:
    ids = set(await store.list_ids())
    if include is not None:
        # 删除时文件已移入 _trash，解析器要把它当成「仍存在」才能找到相连的边。
        ids.update({include} if isinstance(include, str) else include)
    slug_index: dict[str, list[str]] = {}
    for node_id in ids:
        slug_index.setdefault(node_id.rsplit("/", 1)[-1], []).append(node_id)

    def resolve(reference: str) -> str | None:
        if reference in ids:
            return reference
        candidates = slug_index.get(reference, [])
        return candidates[0] if len(candidates) == 1 else None

    return resolve


async def _edge_files(store: KnowledgeStore) -> list[Path]:
    paths = [Path(path) async for path in AsyncPath(store.root).rglob("_edges.jsonl")]
    return sorted(paths, key=str)


async def _remove_incident_edges(store: KnowledgeStore, node_id: str) -> int:
    """删掉与 node_id 相连的边（源或目标解析到它）。返回删除条数。"""
    resolve = await _resolver(store, include=node_id)
    removed = 0
    for path in await _edge_files(store):
        kept: list[dict[str, Any]] = []
        text = await AsyncPath(path).read_text(encoding="utf-8")
        for line in text.splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            source = resolve(str(record["source"]))
            target = resolve(str(record["target"]))
            if source == node_id or target == node_id:
                removed += 1
                continue
            kept.append(record)
        body = "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in kept)
        await AsyncPath(path).write_text(body, encoding="utf-8", newline="\n")
    return removed


async def remove_nodes_edges(store: KnowledgeStore, node_ids: set[str], *, drop_file: Path) -> int:
    """清理相连边及整个库的边文件；已归档节点仍参与解析。"""
    resolve = await _resolver(store, include=node_ids)
    removed = 0
    for path in await _edge_files(store):
        edge_file = AsyncPath(path)
        lines = (await edge_file.read_text(encoding="utf-8")).splitlines(keepends=True)
        if path == drop_file:
            removed += sum(bool(line.strip()) for line in lines)
            await edge_file.unlink()
            continue
        kept: list[str] = []
        for line in lines:
            try:
                record = json.loads(line)
            except ValueError:
                record = None
            if isinstance(record, dict) and (
                resolve(str(record.get("source", ""))) in node_ids
                or resolve(str(record.get("target", ""))) in node_ids
            ):
                removed += 1
            else:
                kept.append(line)
        if len(kept) != len(lines):
            await edge_file.write_text("".join(kept), encoding="utf-8", newline="\n")
    return removed


async def replace_out_edges(
    store: KnowledgeStore,
    node_id: str,
    edges: list[Edge],
) -> dict[str, Any]:
    """用给定列表替换 node_id 的出边；入边不动。"""
    async with write_lock(store.root):
        await guard_project_write(store.root, node_id.split("/", 1)[0])
        if not await store.exists(node_id):
            raise NotFoundError(f"节点不存在: {node_id}")
        node, _ = await store.read(node_id)
        valid_predicates = {item.value for item in Predicate}
        for edge in edges:
            if edge.source != node_id:
                raise InvalidError(f"边的 source 必须是 {node_id}，收到 {edge.source}")
            if edge.predicate.value not in valid_predicates:
                raise InvalidError(f"predicate 不合法: {edge.predicate}")
        await _drop_out_edges(store, node_id)
        added = await store.append_edges(node.project, edges, node_id) if edges else 0
        commit = await _git_commit(store.root, f"kb: edit edges of {node_id}")
    return {"id": node_id, "added": added, "commit": commit}


async def _drop_out_edges(store: KnowledgeStore, node_id: str) -> int:
    resolve = await _resolver(store)
    removed = 0
    for path in await _edge_files(store):
        kept: list[dict[str, Any]] = []
        text = await AsyncPath(path).read_text(encoding="utf-8")
        for line in text.splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            if resolve(str(record["source"])) == node_id:
                removed += 1
                continue
            kept.append(record)
        await AsyncPath(path).write_text(
            "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in kept),
            encoding="utf-8",
            newline="\n",
        )
    return removed


# ---------------------------------------------------------------- git 提交


async def _find_git_root(path: Path) -> Path | None:
    for candidate in [path, *path.parents]:
        if await AsyncPath(candidate / ".git").exists():
            return candidate
    return None


async def _git(repo: Path, args: list[str], *, timeout: float) -> tuple[int, bytes, bytes]:
    completed = await proc.run_command(["git", "-C", str(repo), *args], timeout=timeout)
    return completed.returncode, completed.stdout, completed.stderr


async def _git_commit(root: Path, message: str) -> str | None:
    """真源所在的 git 仓库存在时提交一次；任何失败都不影响写操作本身。"""
    resolved = Path(await AsyncPath(root).resolve())
    repo = await _find_git_root(resolved)
    if repo is None:
        return None
    try:
        relative = resolved.relative_to(repo)
        archives = (relative / _ARCHIVE_STATE_DIR).as_posix()
        journal_name = "[0-9a-f]" * 32 + ".zip"
        # 排除运行时状态；归档快照、active.json 和 blocked 标记仍属于真源。
        pathspec = [
            "--",
            relative.as_posix(),
            f":(exclude,literal){(relative / LOCK_NAME).as_posix()}",
            f":(exclude,literal){(relative / _LEGACY_LOCK_NAME).as_posix()}",
            f":(exclude,literal){archives}/pending.json",
            f":(exclude,literal){archives}/projection-dirty",
            f":(exclude,glob){archives}/**/.*.tmp",
            f":(exclude,glob){archives}/*/{journal_name}",
        ]
        code, _, stderr = await _git(repo, ["add", "-A", *pathspec], timeout=30)
        if code != 0:
            raise OSError(stderr.decode("utf-8", "replace").strip() or f"git add exit {code}")
        code, _, _ = await _git(repo, ["diff", "--cached", "--quiet", *pathspec], timeout=30)
        if code == 0:
            return None
        code, _, stderr = await _git(repo, ["commit", "-m", message, *pathspec], timeout=60)
        if code != 0:
            raise OSError(stderr.decode("utf-8", "replace").strip() or f"git commit exit {code}")
        code, stdout, stderr = await _git(repo, ["rev-parse", "--short", "HEAD"], timeout=30)
        if code != 0:
            raise OSError(stderr.decode("utf-8", "replace").strip() or f"git rev-parse exit {code}")
        return stdout.decode("utf-8", "replace").strip() or None
    except TimeoutError:
        _log.warning("git 提交超时：%s", message)
        return None
    except (OSError, RuntimeError) as exc:
        _log.warning("git 提交失败（%s）：%s", message, str(exc)[-800:])
        return None
