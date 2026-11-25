"""把共享查询限制在授权的活跃节点与边。

`ActiveReader` 是文件实现，额外检查符号链接与目录形状；`ScopedReader` 只依赖
存储操作面（`list_ids` / `exists` / `read` / `edge_lines` / `project_status`），
文件版与 PG 版都能用，PG 版即走它。
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Protocol

from anyio import Path as AsyncPath

from memhub.contract import Kind, NodeFrontmatter
from memhub.contract.mcp import NODE_ID_PATTERN
from memhub.contract.models import KB_ID_RE
from memhub.kb.archive import checked_path, path_kind
from memhub.kb.errors import TargetUnavailable
from memhub.kb.manage import ConflictError
from memhub.kb.store import KnowledgeStore

NODE_ID_RE = re.compile(NODE_ID_PATTERN)


async def _safe_kind(root: Path, path: Path) -> str | None:
    try:
        return await path_kind(await checked_path(root, path.relative_to(root).as_posix()))
    except ConflictError:
        # 跳过链接、重解析点和非法 Windows 路径，不返回磁盘细节。
        return None


class ActiveReader:
    """每次调用独立使用，调用方须持共享的真源写锁。"""

    def __init__(self, store: KnowledgeStore, projects: frozenset[str] | None) -> None:
        self._store = store
        self._root = store.root
        self._scope = projects
        self.resolve_short_aliases = projects is None
        self._active: dict[str, bool] = {}

    async def _project_active(self, name: str) -> bool:
        if self._scope is not None and name not in self._scope:
            return False
        if not KB_ID_RE.fullmatch(name):
            return False
        if name not in self._active:
            path = self._root / name
            marker = self._root / "_kb_archives" / "blocked" / name
            try:
                # 阻止写入标记异常时也不开放该库。
                self._active[name] = (
                    await _safe_kind(self._root, path) == "dir"
                    and await path_kind(
                        await checked_path(self._root, marker.relative_to(self._root).as_posix())
                    )
                    is None
                )
            except ConflictError:
                self._active[name] = False
        return self._active[name]

    async def _projects(self, project: str | None = None) -> list[str]:
        if project is not None:
            names = [project]
        elif self._scope is not None:
            names = sorted(self._scope)
        else:
            names = sorted([path.name async for path in AsyncPath(self._root).iterdir()])
        return [name for name in names if await self._project_active(name)]

    async def exists(self, node_id: str) -> bool:
        return (
            NODE_ID_RE.fullmatch(node_id) is not None
            and await self._project_active(node_id.split("/", 1)[0])
            and await _safe_kind(self._root, self._store.path_for(node_id)) == "file"
        )

    async def read(self, node_id: str) -> tuple[NodeFrontmatter, str]:
        if not await self.exists(node_id):
            raise FileNotFoundError
        return await self._store.read(node_id)

    async def list_ids(self, project: str | None = None) -> list[str]:
        ids: list[str] = []
        for name in await self._projects(project):
            for kind in Kind:
                directory = self._root / name / kind.value
                if await _safe_kind(self._root, directory) != "dir":
                    continue
                async for path in AsyncPath(directory).iterdir():
                    if path.suffix != ".md":
                        continue
                    node_id = f"{name}/{kind.value}/{path.stem}"
                    if (
                        NODE_ID_RE.fullmatch(node_id)
                        and await _safe_kind(self._root, Path(path)) == "file"
                    ):
                        ids.append(node_id)
        return sorted(ids)

    async def edge_lines(self) -> AsyncIterator[str]:
        for name in await self._projects():
            path = self._store.edges_path(name)
            if await _safe_kind(self._root, path) != "file":
                continue
            async with await AsyncPath(path).open(encoding="utf-8") as source:
                async for line in source:
                    yield line


class ScopedSource(Protocol):
    """`ScopedReader` 依赖的最小存储面；文件版与 PG 版都满足。"""

    async def project_status(self, project: str) -> str: ...
    async def exists(self, node_id: str) -> bool: ...
    async def read(self, node_id: str) -> tuple[NodeFrontmatter, str]: ...
    async def list_ids(self, project: str | None = None) -> list[str]: ...
    def edge_lines(self) -> AsyncIterator[str]: ...


class ScopedReader:
    """按授权范围与登记状态过滤的读取视图；只依赖存储操作面。

    与 `ActiveReader` 的区别是不碰文件系统细节（符号链接、目录形状），
    活动性由 `store.project_status()` 给出，因此文件版与 PG 版共用同一份过滤规则。
    """

    def __init__(self, store: ScopedSource, projects: frozenset[str] | None) -> None:
        self._store = store
        self._scope = projects
        self.resolve_short_aliases = projects is None
        self._active: dict[str, bool] = {}

    async def _project_active(self, name: str) -> bool:
        if self._scope is not None and name not in self._scope:
            return False
        if not KB_ID_RE.fullmatch(name):
            return False
        if name not in self._active:
            try:
                self._active[name] = await self._store.project_status(name) == "active"
            except TargetUnavailable:
                # 登记状态无法确认时按不活动处理，不沿用旧权限。
                self._active[name] = False
        return self._active[name]

    async def exists(self, node_id: str) -> bool:
        return (
            NODE_ID_RE.fullmatch(node_id) is not None
            and await self._project_active(node_id.split("/", 1)[0])
            and await self._store.exists(node_id)
        )

    async def read(self, node_id: str) -> tuple[NodeFrontmatter, str]:
        if not await self.exists(node_id):
            raise FileNotFoundError
        return await self._store.read(node_id)

    async def list_ids(self, project: str | None = None) -> list[str]:
        ids = await self._store.list_ids(project)
        return [node_id for node_id in ids if await self._project_active(node_id.split("/", 1)[0])]

    async def edge_lines(self) -> AsyncIterator[str]:
        async for line in self._store.edge_lines():
            try:
                source = json.loads(line).get("source", "")
            except (ValueError, AttributeError):
                continue
            if isinstance(source, str) and await self._project_active(source.split("/", 1)[0]):
                yield line
