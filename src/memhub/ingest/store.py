"""运行态存储：设备、游标、批次幂等（`MemoryStore` 只给 dev / 联调）。

生产实现是 `memhub.ingest.postgres.PostgresStore`（云上共享 PG 实例的独立 database）。
本模块只定接口与内存实现；API 层只依赖 `StateStore` 协议，换实现不用改路由。
接口是 **async** 的（ADR-0005）：生产实现走 SQLAlchemy async engine，内存实现是
纯 dict 操作，不会阻塞事件循环。

**这里不存知识**：知识是 `knowledge/**/*.md` + git（ADR-0002），原始增量是文件系统里的
`raw_store/`。本模块的行都是「推到哪儿了、收过哪批、谁注册过」这类运行状态。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol

from memhub.contract import Cursor, FileCursor, IngestRequest, IngestResult
from memhub.queue.rawstore import BatchTargetConflict

REPLAY_WINDOW = timedelta(hours=24)


class CursorConflict(Exception):
    """客户端的 from_offset 落后于服务端已知 offset。"""

    def __init__(self, path: str, expected_offset: int) -> None:
        super().__init__(f"{path}: expected offset {expected_offset}")
        self.path = path
        self.expected_offset = expected_offset


class StateStore(Protocol):
    """运行态读写的全部契约。所有方法都是 async，且可并发调用。"""

    async def register_device(self, device_id: str, *, name: str = "", platform: str = "") -> None:
        """幂等登记设备；已存在时只更新元数据，不动游标。"""
        ...

    async def is_registered(self, device_id: str) -> bool: ...

    async def get_cursor(self, device_id: str, source_id: str) -> tuple[int, list[FileCursor]]: ...

    async def cursor_summary(self, device_id: str, source_id: str) -> Cursor: ...

    async def check_replay_target(self, request: IngestRequest) -> IngestResult | None:
        """验证已接收批次的目标，并返回仍在重放窗口内的结果。"""
        ...

    async def apply(self, request: IngestRequest) -> IngestResult:
        """落一批增量：幂等重放、游标冲突、去重、更新游标，一次事务完成。"""
        ...


@dataclass
class SourceState:
    source_rev: int = 0
    files: dict[str, FileCursor] = field(default_factory=dict)
    total_bytes: int = 0
    last_at: datetime | None = None


@dataclass
class ReplayedBatch:
    at: datetime
    result: IngestResult
    project: str | None = None


class MemoryStore:
    """进程内实现：重启即清空。只用于 dev 与联调，不可用于生产。"""

    def __init__(self) -> None:
        self.devices: dict[str, dict[str, str]] = {}
        self.sources: dict[tuple[str, str], SourceState] = {}
        self.batches: dict[tuple[str, str], ReplayedBatch] = {}
        self.seen_shas: set[tuple[str, str]] = set()

    # -- devices ---------------------------------------------------------
    async def register_device(self, device_id: str, *, name: str = "", platform: str = "") -> None:
        self.devices[device_id] = {"name": name, "platform": platform}

    async def is_registered(self, device_id: str) -> bool:
        return device_id in self.devices

    # -- cursors ---------------------------------------------------------
    async def get_cursor(self, device_id: str, source_id: str) -> tuple[int, list[FileCursor]]:
        state = self.sources.get((device_id, source_id))
        if state is None:
            return 0, []
        return state.source_rev, sorted(state.files.values(), key=lambda f: f.path)

    async def cursor_summary(self, device_id: str, source_id: str) -> Cursor:
        state = self.sources.get((device_id, source_id))
        if state is None:
            return Cursor()
        return Cursor(files=len(state.files), bytes=state.total_bytes, last_at=state.last_at)

    # -- ingest ----------------------------------------------------------
    async def check_replay_target(self, request: IngestRequest) -> IngestResult | None:
        previous = self.batches.get((request.device_id, request.batch_id))
        if previous is None or datetime.now(UTC) - previous.at >= REPLAY_WINDOW:
            return None
        if previous.project is None or previous.project != request.project:
            raise BatchTargetConflict()
        return previous.result.model_copy(update={"replayed": True})

    async def apply(
        self,
        request: IngestRequest,
        *,
        stored_paths: dict[str, str] | None = None,
    ) -> IngestResult:
        key = (request.device_id, request.batch_id)
        now = datetime.now(UTC)
        previous = await self.check_replay_target(request)
        if previous is not None:
            return previous

        state = self.sources.setdefault((request.device_id, request.source_id), SourceState())
        reset_allowed = request.source_rev > state.source_rev

        # 先校验整批，再落状态：任何一个文件冲突都整批回滚，不留半批游标或哈希。
        accepted = 0
        duplicates = 0
        updates: list[FileCursor] = []
        new_shas: list[tuple[str, str]] = []
        seen = set(self.seen_shas)
        for batch_file in request.files:
            known = None if reset_allowed else state.files.get(batch_file.path)
            expected = known.offset if known is not None else 0
            if batch_file.from_offset < expected:
                raise CursorConflict(batch_file.path, expected)

            sha_key = (request.source_id, batch_file.sha256)
            if sha_key in seen:
                duplicates += 1
            else:
                seen.add(sha_key)
                new_shas.append(sha_key)
                accepted += 1

            updates.append(
                FileCursor(
                    path=batch_file.path,
                    offset=max(expected, batch_file.to_offset),
                    size=batch_file.to_offset,
                    mtime=batch_file.mtime,
                )
            )

        self.seen_shas.update(new_shas)
        for file_cursor in updates:
            state.files[file_cursor.path] = file_cursor
        if reset_allowed:
            state.source_rev = request.source_rev
        state.total_bytes = sum(file.offset for file in state.files.values())
        state.last_at = now

        result = IngestResult(
            batch_id=request.batch_id,
            accepted=accepted,
            duplicates=duplicates,
            cursor=await self.cursor_summary(request.device_id, request.source_id),
        )
        self.batches[key] = ReplayedBatch(at=now, result=result, project=request.project)
        return result


__all__ = [
    "REPLAY_WINDOW",
    "CursorConflict",
    "MemoryStore",
    "ReplayedBatch",
    "SourceState",
    "StateStore",
]
