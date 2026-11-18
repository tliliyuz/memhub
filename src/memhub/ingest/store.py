"""内存态存储（仅 dev / 联调用）。

生产的 raw_store 与游标在 SQLite/文件里，本模块刻意把接口收窄到几个方法，
后续替换实现时 API 层不用改。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from memhub.contract import Cursor, FileCursor, IngestRequest, IngestResult

REPLAY_WINDOW = timedelta(hours=24)


class CursorConflict(Exception):
    """客户端的 from_offset 落后于服务端已知 offset。"""

    def __init__(self, path: str, expected_offset: int) -> None:
        super().__init__(f"{path}: expected offset {expected_offset}")
        self.path = path
        self.expected_offset = expected_offset


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


class MemoryStore:
    def __init__(self) -> None:
        self.devices: set[str] = set()
        self.sources: dict[tuple[str, str], SourceState] = {}
        self.batches: dict[tuple[str, str], ReplayedBatch] = {}
        self.seen_shas: set[tuple[str, str]] = set()

    # -- devices ---------------------------------------------------------
    def register_device(self, device_id: str) -> None:
        self.devices.add(device_id)

    # -- cursors ---------------------------------------------------------
    def get_cursor(self, device_id: str, source_id: str) -> tuple[int, list[FileCursor]]:
        state = self.sources.get((device_id, source_id))
        if state is None:
            return 0, []
        return state.source_rev, sorted(state.files.values(), key=lambda f: f.path)

    def cursor_summary(self, device_id: str, source_id: str) -> Cursor:
        state = self.sources.get((device_id, source_id))
        if state is None:
            return Cursor()
        return Cursor(files=len(state.files), bytes=state.total_bytes, last_at=state.last_at)

    # -- ingest ----------------------------------------------------------
    def apply(self, request: IngestRequest) -> IngestResult:
        key = (request.device_id, request.batch_id)
        now = datetime.now(UTC)
        previous = self.batches.get(key)
        if previous is not None and now - previous.at < REPLAY_WINDOW:
            return previous.result.model_copy(update={"replayed": True})

        state = self.sources.setdefault((request.device_id, request.source_id), SourceState())
        reset_allowed = request.source_rev > state.source_rev

        accepted = 0
        duplicates = 0
        for batch_file in request.files:
            known = None if reset_allowed else state.files.get(batch_file.path)
            expected = known.offset if known is not None else 0
            if batch_file.from_offset < expected:
                raise CursorConflict(batch_file.path, expected)

            sha_key = (request.source_id, batch_file.sha256)
            if sha_key in self.seen_shas:
                duplicates += 1
            else:
                self.seen_shas.add(sha_key)
                accepted += 1

            new_offset = max(expected, batch_file.to_offset)
            state.files[batch_file.path] = FileCursor(
                path=batch_file.path,
                offset=new_offset,
                size=batch_file.to_offset,
                mtime=batch_file.mtime,
            )

        if reset_allowed:
            state.source_rev = request.source_rev
        state.total_bytes = sum(file.offset for file in state.files.values())
        state.last_at = now

        result = IngestResult(
            batch_id=request.batch_id,
            accepted=accepted,
            duplicates=duplicates,
            cursor=self.cursor_summary(request.device_id, request.source_id),
        )
        self.batches[key] = ReplayedBatch(at=now, result=result)
        return result
