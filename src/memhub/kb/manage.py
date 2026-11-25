"""知识库管理写操作：校验、拼装与错误映射（全异步 IO）。

原子写、软删、回收站、边维护与提交下沉到存储对象的统一操作面：文件版是
`store.KnowledgeStore`，迁移后是 `pgstore.PgKnowledgeStore`。本模块只做
「读 → 校验 → 合并 → 调存储写」，不直接摸文件系统，因此两种存储下行为一致
（ADR-0013，规格 §7）。

删除不是硬删：存储层置 `archived_at`（文件版移入 `_trash/<时间戳>/`），并清掉
与之相连的边。图谱与检索都直读真源，本模块不再维护任何文件投影。
"""

from __future__ import annotations

import os
import re
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from pydantic import ValidationError

from memhub.contract import (
    Edge,
    EntityKind,
    Kind,
    NodeFrontmatter,
    Predicate,
    QuestionStatus,
    SourceKind,
    SourceRef,
    Tier,
)
from memhub.kb import query
from memhub.kb.errors import (
    ConflictError,
    InvalidError,
    ManageError,
    NodeMissing,
    NotFoundError,
    ProjectInvalid,
    ProjectMissing,
    RevisionConflict,
    WriteDeferred,
)
from memhub.kb.store import (
    ARCHIVE_STATE_DIR,
    LEGACY_LOCK_NAME,
    LOCK_NAME,
    TRASH_DIR,
    KnowledgeStore,
    find_git_root,
    git_commit,
    guard_project_write,
    revision_of,
    write_lock,
)

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")

_log_name = __name__

# 兼容旧调用方：`manage.guard_project_write(root, project)` / `manage.write_lock`。
__all__ = [
    "ARCHIVE_STATE_DIR",
    "LEGACY_LOCK_NAME",
    "LOCK_NAME",
    "TRASH_DIR",
    "ConflictError",
    "InvalidError",
    "ManageError",
    "NodeDraft",
    "NodePatch",
    "NotFoundError",
    "ProjectMissing",
    "WriteDeferred",
    "create_node",
    "delete_node",
    "deprecate_node",
    "get_node",
    "guard_project_write",
    "list_nodes",
    "list_trash",
    "node_revision",
    "remove_nodes_edges",
    "replace_out_edges",
    "restore_node",
    "revision_of",
    "slugify",
    "stats",
    "update_node",
    "write_lock",
]


class Storage(query.KnowledgeReader, Protocol):
    """`manage` 依赖的存储操作面；文件版与 PG 版同形。

    读侧复用 `query.KnowledgeReader`，写侧在此补齐；`write_scope` 返回异步上下文
    管理器（实现端由 `@asynccontextmanager` 提供），不是裸异步迭代器。
    真源路径（`root`）只属于文件实现，不在操作面里，避免调用方误以为 PG 也有目录。
    """

    def write_scope(
        self, *, timeout: float = ..., recovery: bool = ...
    ) -> AbstractAsyncContextManager[None]: ...

    async def guard_write(self, project: str) -> None: ...

    async def project_status(self, project: str) -> str: ...

    def scoped_reader(self, projects: frozenset[str] | None) -> query.KnowledgeReader: ...

    async def exists(self, node_id: str) -> bool: ...

    async def revision(self, node_id: str) -> str | None: ...

    async def read(self, node_id: str) -> tuple[NodeFrontmatter, str]: ...

    async def write(
        self,
        node_id: str,
        node: NodeFrontmatter,
        body: str,
        *,
        actor: str | None = ...,
        reason: str | None = ...,
        expected_revision: str | None = ...,
    ) -> str: ...

    async def archive_node(
        self,
        node_id: str,
        *,
        expected_revision: str | None = ...,
        reason: str = ...,
        actor: str = ...,
    ) -> dict[str, Any]: ...

    async def list_trash(
        self, *, limit: int = ..., offset: int = ..., project: str | None = ..., q: str | None = ...
    ) -> dict[str, Any]: ...

    async def restore_node(self, trash: str) -> dict[str, Any]: ...

    async def replace_out_edges(self, node_id: str, edges: list[Edge]) -> int: ...

    async def remove_nodes_edges(self, node_ids: set[str], *, drop_file: Any = ...) -> int: ...

    async def commit(self, message: str, *, node_path: str | None = ...) -> str | None: ...


# ---------------------------------------------------------------- 错误映射


# ---------------------------------------------------------------- 修订号


async def node_revision(store: Storage, node_id: str) -> str | None:
    """当前修订号；节点不存在返回 None。文件版是内容 sha256，PG 版是写入时生成的 hex。"""
    return await store.revision(node_id)


# ---------------------------------------------------------------- 列表与详情


async def _summary(store: Storage, record: query.NodeRecord) -> dict[str, Any]:
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
    store: Storage,
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


async def stats(store: Storage) -> dict[str, Any]:
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


async def get_node(store: Storage, node_id: str) -> dict[str, Any]:
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


@asynccontextmanager
async def _enter_write(
    store: Storage, project: str, *, timeout: float = 10.0
) -> AsyncIterator[None]:
    """进入写作用域并确认项目可写；把存储层错误翻译成管理端错误。"""
    try:
        async with store.write_scope(timeout=timeout):
            try:
                await store.guard_write(project)
            except ProjectInvalid as exc:
                raise InvalidError(str(exc)) from exc
            yield
    except ProjectInvalid as exc:  # 锁/事务在进入前就可能报项目非法
        raise InvalidError(str(exc)) from exc


async def create_node(store: Storage, draft: NodeDraft) -> dict[str, Any]:
    slug = draft.slug or slugify(draft.title) or f"n-{os.urandom(4).hex()}"
    _validate_path_parts(draft.project, draft.kind.value, slug)
    node_id = f"{draft.project}/{draft.kind.value}/{slug}"
    now = datetime.now(UTC)
    async with _enter_write(store, draft.project):
        if await store.exists(node_id):
            raise ConflictError(f"节点已存在: {node_id}", {"id": node_id})
        node = _build_node(node_id, draft, created_at=now)
        revision = await store.write(
            node_id, node, draft.body, actor=f"ui:{draft.actor}", reason="create"
        )
        commit = await store.commit(f"kb: create {node_id}")
    return {
        "id": node_id,
        "revision": revision,
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


def _patched(
    node: NodeFrontmatter, node_id: str, patch: NodePatch, *, now: datetime
) -> NodeFrontmatter:
    data = node.model_dump(mode="json")
    data["updated_at"] = now
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
        return NodeFrontmatter.model_validate(data)
    except ValidationError as exc:
        raise InvalidError("frontmatter 校验失败", {"errors": _brief_errors(exc)}) from exc


async def update_node(
    store: Storage,
    node_id: str,
    *,
    expected_revision: str,
    patch: NodePatch,
) -> dict[str, Any]:
    project = node_id.split("/", 1)[0]
    async with _enter_write(store, project):
        try:
            node, body = await store.read(node_id)
        except (NodeMissing, FileNotFoundError, OSError) as exc:
            raise NotFoundError(f"节点不存在: {node_id}") from exc
        updated = _patched(node, node_id, patch, now=datetime.now(UTC))
        new_body = body if patch.body is None else patch.body
        try:
            revision = await store.write(
                node_id,
                updated,
                new_body,
                actor=f"ui:{patch.actor}",
                reason="update",
                expected_revision=expected_revision,
            )
        except RevisionConflict as exc:
            raise ConflictError(
                "节点已被其他人/进程修改，请刷新后重试",
                {"expected": exc.expected, "current": exc.current},
            ) from exc
        commit = await store.commit(f"kb: update {node_id}")
    return {
        "id": node_id,
        "revision": revision,
        "commit": commit,
        "node": await get_node(store, node_id),
    }


# ---------------------------------------------------------------- 废弃与删除


async def deprecate_node(
    store: Storage,
    node_id: str,
    *,
    superseded_by: str,
    reason: str = "",
    actor: str = "ui",
) -> dict[str, Any]:
    if not superseded_by:
        raise InvalidError("superseded_by 必须给出替代节点的 id")
    project = node_id.split("/", 1)[0]
    async with _enter_write(store, project):
        try:
            node, body = await store.read(node_id)
        except (NodeMissing, FileNotFoundError, OSError) as exc:
            raise NotFoundError(f"节点不存在: {node_id}") from exc
        if superseded_by != node_id and not await store.exists(superseded_by):
            raise InvalidError(f"替代节点不存在: {superseded_by}")
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
        revision = await store.write(
            node_id, updated, body, actor=f"ui:{actor}", reason="deprecate"
        )
        commit = await store.commit(f"kb: deprecate {node_id}")
    return {
        "id": node_id,
        "revision": revision,
        "commit": commit,
        "node": await get_node(store, node_id),
    }


async def delete_node(
    store: Storage,
    node_id: str,
    *,
    expected_revision: str,
    reason: str = "",
    actor: str = "ui",
) -> dict[str, Any]:
    """软删并清掉相连的边；可从回收站恢复。"""
    project = node_id.split("/", 1)[0]
    async with _enter_write(store, project):
        try:
            result = await store.archive_node(
                node_id, expected_revision=expected_revision, reason=reason, actor=actor
            )
        except NodeMissing as exc:
            raise NotFoundError(f"节点不存在: {node_id}") from exc
        except RevisionConflict as exc:
            raise ConflictError(
                "节点已被其他人/进程修改，请刷新后重试",
                {"expected": exc.expected, "current": exc.current},
            ) from exc
        commit = await store.commit(f"kb: delete {node_id}")
    return {
        "id": node_id,
        "trash": result["trash"],
        "removed_edges": result["removed_edges"],
        "commit": commit,
    }


async def list_trash(
    store: Storage,
    *,
    limit: int = 100,
    offset: int = 0,
    project: str | None = None,
    q: str | None = None,
) -> dict[str, Any]:
    return await store.list_trash(limit=limit, offset=offset, project=project, q=q)


async def restore_node(store: Storage, trash: str) -> dict[str, Any]:
    parts = trash.split("/")
    if len(parts) < 2 or any(part in {"", ".", ".."} or "\\" in part for part in parts):
        raise InvalidError(f"trash 路径不合法: {trash!r}")
    project = parts[1]
    async with _enter_write(store, project):
        try:
            result = await store.restore_node(trash)
        except ValueError as exc:
            raise InvalidError(str(exc)) from exc
        except FileExistsError as exc:
            raise ConflictError(f"节点已重新存在，无法恢复: {result_id(parts)}") from exc
        except NodeMissing as exc:
            raise NotFoundError(f"回收站里没有: {trash}") from exc
        commit = await store.commit(f"kb: restore {result.get('id')}")
    return {
        "id": result["id"],
        "revision": await node_revision(store, str(result["id"])),
        "commit": commit,
    }


def result_id(parts: list[str]) -> str:
    return "/".join(parts[1:])


# ---------------------------------------------------------------- 边编辑


async def replace_out_edges(
    store: Storage,
    node_id: str,
    edges: list[Edge],
) -> dict[str, Any]:
    """用给定列表替换 node_id 的出边；入边不动。"""
    project = node_id.split("/", 1)[0]
    async with _enter_write(store, project):
        try:
            node, _ = await store.read(node_id)
        except (NodeMissing, FileNotFoundError, OSError) as exc:
            raise NotFoundError(f"节点不存在: {node_id}") from exc
        valid_predicates = {item.value for item in Predicate}
        for edge in edges:
            if edge.source != node_id:
                raise InvalidError(f"边的 source 必须是 {node_id}，收到 {edge.source}")
            if edge.predicate.value not in valid_predicates:
                raise InvalidError(f"predicate 不合法: {edge.predicate}")
        added = await store.replace_out_edges(node_id, edges)
        commit = await store.commit(f"kb: edit edges of {node_id}")
        assert node is not None
    return {"id": node_id, "added": added, "commit": commit}


async def remove_nodes_edges(store: Storage, node_ids: set[str], *, drop_file: Path) -> int:
    """清理相连边及整个库的边文件；已归档节点仍参与解析。"""
    return await store.remove_nodes_edges(node_ids, drop_file=drop_file)


async def _edge_files(store: KnowledgeStore) -> list[Path]:
    """文件版边文件清单；`catalog` 归档时仍在用（PG 版归档另走事务）。"""
    return await store._edge_files()


# ---------------------------------------------------------------- git 提交


async def commit_source(root: Path, message: str, *, node_path: str) -> str | None:
    """只提交本次写入的节点，不捎带其他真源改动（文件版专用）。"""
    return await git_commit(root, message, node_path=node_path)


def _git_commit(root: Path, message: str, *, node_path: str | None = None) -> Any:
    return git_commit(root, message, node_path=node_path)


def _git(repo: Path, args: list[str], *, timeout: float) -> Any:
    from memhub.kb.store import git

    return git(repo, args, timeout=timeout)


def _find_git_root(path: Path) -> Any:
    return find_git_root(path)


assert _log_name  # 保持模块名在调试器中可辨识
