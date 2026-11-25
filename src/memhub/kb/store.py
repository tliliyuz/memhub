"""markdown 真源读写（全异步 IO）。

一个节点 = 一个文件，路径 `<root>/<project>/<kind>/<slug>.md`；id 即相对路径去扩展名。
写入采用临时文件 + 原子替换；关系按项目追加到 `_edges.jsonl`（去重、整体重写）。
文件 IO 全部走 anyio 的异步 Path，不阻塞事件循环；`frontmatter` 解析是纯 CPU 操作。

本文件同时是**存储操作面**的文件实现：`manage` 只调用 `write_scope` / `guard_write` /
`write` / `archive_node` / `list_trash` / `restore_node` / `replace_out_edges` / `commit`
这套方法，PG 版（`pgstore.PgKnowledgeStore`）形状相同，从而调用方无感切换
（ADR-0013，规格 §7）。
"""

from __future__ import annotations

import errno
import hashlib
import json
import sys
import time
import uuid
from collections.abc import AsyncIterator, Callable, Iterable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import anyio
import frontmatter
from anyio import Path as AsyncPath

from memhub.contract import Edge, NodeFrontmatter, valid_project
from memhub.kb import proc
from memhub.kb.errors import (
    InvalidError,
    NodeMissing,
    ProjectMissing,
    RevisionConflict,
    TargetUnavailable,
    WriteDeferred,
)

# 删除是软删：原文件移到 `<root>/_trash/<时间戳>/<原 id>.md`。
# manage 的删除/恢复与这里的 list_ids 共用同一个名字。
TRASH_DIR = "_trash"

# 独立于旧版 O_EXCL 锁文件；回退时旧版不受持久锁文件影响（不可混跑）。
LOCK_NAME = ".memhub-write-v2.lock"
LEGACY_LOCK_NAME = ".memhub-write.lock"
ARCHIVE_STATE_DIR = "_kb_archives"

__all__ = [
    "ARCHIVE_STATE_DIR",
    "LEGACY_LOCK_NAME",
    "LOCK_NAME",
    "TRASH_DIR",
    "InvalidError",
    "KnowledgeStore",
    "NodeMissing",
    "ProjectMissing",
    "RevisionConflict",
    "WriteDeferred",
    "guard_project_write",
    "revision_of",
    "write_lock",
]


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
        pending = root / ARCHIVE_STATE_DIR / "pending.json"
        if not recovery and await _archive_state_exists(pending):
            raise WriteDeferred("有未恢复的知识库归档事务，暂不能写入真源", reason="pending")
        yield
    finally:
        with anyio.CancelScope(shield=True):
            await handle.aclose()


async def guard_project_write(root: Path, project: str) -> None:
    """在持有写锁时，检查项目是否仍被归档阻止写入。"""
    if not valid_project(project):
        raise InvalidError(f"project 不合法: {project!r}")
    marker = root / ARCHIVE_STATE_DIR / "blocked" / project
    if await _archive_state_exists(marker):
        raise WriteDeferred(f"知识库 {project} 已归档，恢复后才能写入", reason="archived")


async def revision_of(path: Path) -> str:
    """修订号 = 文件内容 sha256 前 16 位；用于乐观并发（ETag）。"""
    return hashlib.sha256(await AsyncPath(path).read_bytes()).hexdigest()[:16]


@dataclass(frozen=True)
class TrashEntry:
    """回收站条目；`trash` 是 `restore_node` 接受的定位串。"""

    id: str
    title: str
    kind: str
    project: str
    deleted_at: str
    reason: str
    actor: str
    trash: str

    def as_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "title": self.title,
            "kind": self.kind,
            "project": self.project,
            "deleted_at": self.deleted_at,
            "reason": self.reason,
            "actor": self.actor,
            "trash": self.trash,
        }


class KnowledgeStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def path_for(self, node_id: str) -> Path:
        return self.root / f"{node_id}.md"

    async def _require_project(self, project: str) -> None:
        """确认 `<root>/<project>` 已是普通目录；不创建、不修复。"""
        if not project:
            raise ProjectMissing("知识库目录缺失：project 为空")
        target = AsyncPath(self.root / project)
        try:
            ready = await target.is_dir()
        except OSError as exc:
            raise ProjectMissing(f"知识库目录不可用：{project}") from exc
        if not ready:
            raise ProjectMissing(f"知识库目录不存在：{project}")

    # -- 写作用域与项目许可（PG 版同形） --------------------------------

    @asynccontextmanager
    async def write_scope(
        self, *, timeout: float = 10.0, recovery: bool = False
    ) -> AsyncIterator[None]:
        """一次写操作 = 一次锁持有；PG 版对应一次事务。"""
        async with write_lock(self.root, timeout=timeout, recovery=recovery):
            yield

    async def guard_write(self, project: str) -> None:
        """确认项目可写：id 合法、未被整库归档阻断。"""
        await guard_project_write(self.root, project)

    def project_exists(self, project: str) -> bool:
        """文件版按目录判断；同步接口只是为了让调用方不必分叉。"""
        return (self.root / project).is_dir()

    async def require_project(self, project: str) -> None:
        await self._require_project(project)

    async def project_status(self, project: str) -> str:
        """登记状态：`active` / `unregistered` / `inactive`（PG 版同口径）。

        只认严格登记（`.kbs.json`）+ 活动普通目录：符号链接、重解析点与归档阻断
        标记一律不活动。登记不可读或归档事务未完成时抛 `TargetUnavailable`，
        调用方按可重试错误处理，不得猜默认值。
        """
        # 延迟导入：catalog / archive 都依赖本模块，模块级导入会成环。
        from memhub.kb import archive, catalog
        from memhub.kb.manage import ConflictError

        try:
            if await archive.path_kind(self.root) != "dir":
                raise TargetUnavailable("target registry unavailable")
            pending = await archive.checked_path(self.root, archive.PENDING)
            if await archive.path_kind(pending) is not None:
                raise TargetUnavailable("target registry unavailable")
            _, registry = await catalog._strict_registry(self)
            if not any(entry["id"] == project for entry in registry["kbs"]):
                return "unregistered"
            blocked = await archive.checked_path(self.root, f"{archive.ARCHIVES}/blocked/{project}")
            if await archive.path_kind(blocked) is not None:
                return "inactive"
        except (ConflictError, OSError) as exc:
            raise TargetUnavailable("target registry unavailable") from exc
        try:
            kind = await archive.path_kind(self.root / project)
        except ConflictError:
            return "inactive"
        except OSError as exc:
            raise TargetUnavailable("target registry unavailable") from exc
        return "active" if kind == "dir" else "inactive"

    def scoped_reader(self, projects: frozenset[str] | None) -> Any:
        """按授权范围读取的视图；文件版保留符号链接与目录形状检查。"""
        from memhub.kb.reader import ActiveReader

        return ActiveReader(self, projects)

    # -- 节点 ------------------------------------------------------------

    async def exists(self, node_id: str) -> bool:
        return await AsyncPath(self.path_for(node_id)).is_file()

    async def revision(self, node_id: str) -> str | None:
        """修订号 = 文件内容 sha256 前 16 位；不存在返回 None（与 PG 版同口径）。"""
        path = self.path_for(node_id)
        if not await AsyncPath(path).is_file():
            return None
        return await revision_of(path)

    async def read(self, node_id: str) -> tuple[NodeFrontmatter, str]:
        text = await AsyncPath(self.path_for(node_id)).read_text(encoding="utf-8")
        post = frontmatter.loads(text)
        metadata = dict(post.metadata)
        metadata["id"] = node_id
        node = NodeFrontmatter.model_validate(metadata)
        return node, post.content

    async def write(
        self,
        node_id: str,
        node: NodeFrontmatter,
        body: str,
        *,
        actor: str | None = None,
        reason: str | None = None,
        expected_revision: str | None = None,
    ) -> str:
        """写入节点并返回新 revision；`expected_revision` 非空时做乐观锁比对。

        `actor` / `reason` 在文件版没有落点（历史由 git 承担），只为与 PG 版同形。
        """
        project, _, remainder = node_id.partition("/")
        if not remainder:
            raise ProjectMissing(f"节点 id 缺少项目段：{node_id}")
        if expected_revision is not None:
            current = await self.revision(node_id)
            if current != expected_revision:
                raise RevisionConflict(node_id, expected=expected_revision, current=current)
        path = self.path_for(node_id)
        await self._require_project(project)
        # 库目录已存在，只需补齐 `<kind>` 一级；不做递归创建。
        await AsyncPath(path.parent).mkdir(exist_ok=True)
        metadata = node.model_dump(mode="json", exclude_none=True)
        metadata["id"] = node_id
        text = frontmatter.dumps(frontmatter.Post(body.rstrip() + "\n", **metadata))
        await _atomic_write(path, text + "\n")
        return await revision_of(path)

    async def list_ids(self, project: str | None = None) -> list[str]:
        base = self.root / project if project else self.root
        if not await AsyncPath(base).is_dir():
            return []
        ids: list[str] = []
        async for path in AsyncPath(base).rglob("*.md"):
            relative = Path(path).relative_to(self.root)
            # 回收站里的文件仍是 markdown，但不是节点：不跳过的话删除过的节点会以
            # `_trash/<时间戳>/<原 id>` 的伪节点身份重新出现在图谱里。
            if relative.parts[0] == TRASH_DIR:
                continue
            ids.append(relative.with_suffix("").as_posix())
        return sorted(ids)

    # -- 软删与回收站 ----------------------------------------------------

    async def archive_node(
        self,
        node_id: str,
        *,
        expected_revision: str | None = None,
        reason: str = "",
        actor: str = "ui",
    ) -> dict[str, Any]:
        """归档到 `<root>/_trash/<时间戳>/` 并清掉相连的边。"""
        if not await self.exists(node_id):
            raise NodeMissing(f"节点不存在: {node_id}")
        current = await self.revision(node_id)
        if expected_revision is not None and current != expected_revision:
            raise RevisionConflict(node_id, expected=expected_revision, current=current)
        node, _ = await self.read(node_id)
        moment = datetime.now(UTC)
        stamp = moment.strftime("%Y%m%dT%H%M%S%f")
        folder = self.root / TRASH_DIR / stamp
        await AsyncPath(folder).mkdir(parents=True, exist_ok=True)
        target = folder / f"{node_id}.md"
        await AsyncPath(target.parent).mkdir(parents=True, exist_ok=True)
        await AsyncPath(self.path_for(node_id)).replace(target)
        meta = {
            "id": node_id,
            "title": node.title,
            "kind": node.kind.value,
            "project": node.project,
            "deleted_at": moment.isoformat(),
            "reason": reason,
            "actor": actor,
        }
        meta_path = folder / f"{node_id}.meta.json"
        await AsyncPath(meta_path.parent).mkdir(parents=True, exist_ok=True)
        await AsyncPath(meta_path).write_text(
            json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        removed_edges = await self._remove_incident_edges(node_id)
        return {"trash": f"{stamp}/{node_id}", "removed_edges": removed_edges}

    async def list_trash(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        project: str | None = None,
        q: str | None = None,
    ) -> dict[str, Any]:
        base = self.root / TRASH_DIR
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

    async def restore_node(self, trash: str) -> dict[str, Any]:
        parts = trash.split("/")
        if len(parts) < 2 or any(part in {"", ".", ".."} or "\\" in part for part in parts):
            raise ValueError(f"trash 路径不合法: {trash!r}")
        stamp = parts[0]
        node_id = "/".join(parts[1:])
        project = parts[1]
        base = Path(await AsyncPath(self.root / TRASH_DIR).resolve())
        source = Path(await AsyncPath(base / stamp / f"{node_id}.md").resolve())
        if not await AsyncPath(source).is_file() or base not in source.parents:
            raise ProjectMissing(f"回收站里没有: {trash}")
        if await self.exists(node_id):
            raise FileExistsError(f"节点已重新存在，无法恢复: {node_id}")
        target = self.path_for(node_id)
        # 库目录缺失时恢复必须失败：存储层不隐式建库，这里也不重建。
        await self._require_project(project)
        await AsyncPath(target.parent).mkdir(exist_ok=True)
        await AsyncPath(source).replace(target)
        meta = source.with_suffix(".meta.json")
        if await AsyncPath(meta).is_file():
            await AsyncPath(meta).unlink()
        return {"id": node_id}

    # -- 边 --------------------------------------------------------------

    resolve_short_aliases = True

    async def edges(self, project: str | None = None) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for path in (
            sorted(await self._edge_files(), key=str)
            if project is None
            else [self.edges_path(project)]
        ):
            if not await AsyncPath(path).is_file():
                continue
            for line in (await AsyncPath(path).read_text(encoding="utf-8")).splitlines():
                if not line.strip():
                    continue
                record = json.loads(line)
                rows.append(
                    {
                        "source": str(record["source"]),
                        "predicate": str(record["predicate"]),
                        "target": str(record["target"]),
                        "source_doc": record.get("source_doc"),
                    }
                )
        return rows

    async def edge_lines(self) -> AsyncIterator[str]:
        for record in await self.edges():
            yield json.dumps(record, ensure_ascii=False)

    def edges_path(self, project: str) -> Path:
        return self.root / project / "_edges.jsonl"

    async def append_edges(
        self, project: str, edges: Iterable[Edge], source_doc: str | None = None
    ) -> int:
        await self._require_project(project)
        path = self.edges_path(project)
        existing: dict[tuple[str, str, str], dict[str, object]] = {}
        if await AsyncPath(path).is_file():
            text = await AsyncPath(path).read_text(encoding="utf-8")
            for line in text.splitlines():
                if not line.strip():
                    continue
                record = json.loads(line)
                key = (str(record["source"]), str(record["predicate"]), str(record["target"]))
                existing[key] = record
        added = 0
        for edge in edges:
            key = (edge.source, edge.predicate.value, edge.target)
            if key in existing:
                continue
            entry: dict[str, object] = {
                "source": edge.source,
                "predicate": edge.predicate.value,
                "target": edge.target,
                "source_doc": source_doc,
            }
            existing[key] = entry
            added += 1
        text = "".join(
            json.dumps(record, ensure_ascii=False) + "\n" for record in existing.values()
        )
        await _atomic_write(path, text)
        return added

    async def replace_out_edges(self, node_id: str, edges: list[Edge]) -> int:
        """替换 node_id 的出边；入边与其他节点的边不动。"""
        node, _ = await self.read(node_id)
        await self._drop_out_edges(node_id)
        if not edges:
            return 0
        return await self.append_edges(node.project, edges, node_id)

    async def remove_nodes_edges(self, node_ids: set[str], *, drop_file: Path | None = None) -> int:
        """清理与给定节点相连的边；`drop_file` 指定的边文件整体摘除。"""
        resolve = await self._resolver(include=node_ids)
        removed = 0
        for path in await self._edge_files():
            edge_file = AsyncPath(path)
            if drop_file is not None and path == drop_file:
                lines = (await edge_file.read_text(encoding="utf-8")).splitlines(keepends=True)
                removed += sum(bool(line.strip()) for line in lines)
                await edge_file.unlink()
                continue
            lines = (await edge_file.read_text(encoding="utf-8")).splitlines(keepends=True)
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

    async def _edge_files(self) -> list[Path]:
        paths = [Path(path) async for path in AsyncPath(self.root).rglob("_edges.jsonl")]
        return sorted(paths, key=str)

    async def _resolver(
        self, *, include: str | set[str] | None = None
    ) -> Callable[[str], str | None]:
        ids = set(await self.list_ids())
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

    async def _remove_incident_edges(self, node_id: str) -> int:
        """删掉与 node_id 相连的边（源或目标解析到它）。返回删除条数。"""
        resolve = await self._resolver(include=node_id)
        removed = 0
        for path in await self._edge_files():
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

    async def _drop_out_edges(self, node_id: str) -> int:
        resolve = await self._resolver()
        removed = 0
        for path in await self._edge_files():
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

    # -- 历史 ------------------------------------------------------------

    async def commit(self, message: str, *, node_path: str | None = None) -> str | None:
        """真源在 git 仓库内时提交一次；PG 版没有这一步（历史进 `kb_node_revisions`）。"""
        return await git_commit(self.root, message, node_path=node_path)


# ---------------------------------------------------------------- git 提交


async def find_git_root(path: Path) -> Path | None:
    for candidate in [path, *path.parents]:
        if await AsyncPath(candidate / ".git").exists():
            return candidate
    return None


async def git(repo: Path, args: list[str], *, timeout: float) -> tuple[int, bytes, bytes]:
    completed = await proc.run_command(["git", "-C", str(repo), *args], timeout=timeout)
    return completed.returncode, completed.stdout, completed.stderr


async def git_commit(root: Path, message: str, *, node_path: str | None = None) -> str | None:
    """只提交本次写入的节点，不捎带其他真源改动；任何失败都不影响写操作本身。"""
    resolved = Path(await AsyncPath(root).resolve())
    repo = await find_git_root(resolved)
    if repo is None:
        return None
    try:
        relative = resolved.relative_to(repo)
        archives = (relative / ARCHIVE_STATE_DIR).as_posix()
        journal_name = "[0-9a-f]" * 32 + ".zip"
        # 排除运行时状态；归档快照、active.json 和 blocked 标记仍属于真源。
        pathspec = [
            "--",
            relative.as_posix(),
            f":(exclude,literal){(relative / LOCK_NAME).as_posix()}",
            f":(exclude,literal){(relative / LEGACY_LOCK_NAME).as_posix()}",
            f":(exclude,literal){archives}/pending.json",
            f":(exclude,literal){archives}/projection-dirty",
            f":(exclude,glob){archives}/**/.*.tmp",
            f":(exclude,glob){archives}/*/{journal_name}",
        ]
        if node_path is not None:
            pathspec = ["--", f":(literal){(relative / node_path).as_posix()}"]
        code, _, stderr = await git(repo, ["add", "-A", *pathspec], timeout=30)
        if code != 0:
            raise OSError(stderr.decode("utf-8", "replace").strip() or f"git add exit {code}")
        code, _, _ = await git(repo, ["diff", "--cached", "--quiet", *pathspec], timeout=30)
        if code == 0:
            return None
        code, _, stderr = await git(repo, ["commit", "-m", message, *pathspec], timeout=60)
        if code != 0:
            raise OSError(stderr.decode("utf-8", "replace").strip() or f"git commit exit {code}")
        code, stdout, stderr = await git(repo, ["rev-parse", "--short", "HEAD"], timeout=30)
        if code != 0:
            raise OSError(stderr.decode("utf-8", "replace").strip() or f"git rev-parse exit {code}")
        return stdout.decode("utf-8", "replace").strip() or None
    except TimeoutError:
        import logging

        logging.getLogger(__name__).warning("git 提交超时：%s", message)
        return None
    except (OSError, RuntimeError) as exc:
        import logging

        logging.getLogger(__name__).warning("git 提交失败（%s）：%s", message, str(exc)[-800:])
        return None


async def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        async with await AsyncPath(tmp).open("w", encoding="utf-8", newline="\n") as handle:
            await handle.write(text)
        await AsyncPath(tmp).replace(path)
    except BaseException:
        try:
            await AsyncPath(tmp).unlink()
        except OSError:
            pass
        raise
