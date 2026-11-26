"""MCP 调用轨迹的写入器（ADR-0014，规格 docs/plans/mcp-trace-spec.md §4）。

可靠落库：独立事务提交，失败按 100ms/300ms 退避重试（最多 3 次），仍失败追加到
本地 spool（JSONL，flush + fsync）；下一次成功写入前先补投 spool，成功后清空。
spool 也不可用时记 ERROR——这是唯一会丢记录的路径。保留期 30 天，
清理按小时节流挂在写入路径上，失败只记 WARNING。记录失败不得改变调用返回。
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from dataclasses import asdict, dataclass, fields
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import anyio
import anyio.to_thread

RETENTION_DAYS = 30
_CLEANUP_THROTTLE_SECONDS = 3600.0
_RETRY_DELAYS = (0.1, 0.3, 0.3)
_SPOOL_MAX_BYTES = 8 * 1024 * 1024

if TYPE_CHECKING:
    from memhub.kb.pgstore import PgKnowledgeStore

_log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TraceEntry:
    """一调用一行的元数据载荷；字段与 `kb_mcp_trace` 列一一对应。"""

    trace_id: str
    request_id: str
    rpc_id: str | None
    called_at: datetime
    credential_id: str | None
    credential_name: str | None
    tool: str | None
    status: str
    http_status: int
    error_code: int | None
    error_kind: str | None
    duration_ms: int
    result_bytes: int | None
    args_digest: str | None
    projects: list[str] | None
    client: str | None

    def as_row(self) -> dict[str, object]:
        """spool 用 JSON 兼容行：键与列一致，时间为 ISO-8601 UTC 字符串。"""
        row = asdict(self)
        row["called_at"] = self.called_at.astimezone(UTC).isoformat()
        return row


def new_trace_id() -> str:
    return uuid.uuid4().hex


def entry_from_row(row: dict[str, object]) -> TraceEntry:
    """从 spool JSON 行还原；`called_at` 是 ISO-8601 字符串。"""
    known = {item.name for item in fields(TraceEntry)}
    data = {key: value for key, value in row.items() if key in known}
    if isinstance(data["called_at"], str):
        data["called_at"] = datetime.fromisoformat(data["called_at"])
    return TraceEntry(**data)  # type: ignore[arg-type]


class TraceRecorder:
    """把每次调用记录写入 PG；失败走 spool 补投。"""

    def __init__(
        self,
        store: PgKnowledgeStore,
        *,
        spool_path: str | Path | None,
    ) -> None:
        self._store = store
        self._spool_path = Path(spool_path) if spool_path is not None else None
        self._last_cleanup = -_CLEANUP_THROTTLE_SECONDS

    async def record(self, entry: TraceEntry) -> None:
        await self._replay_spool()
        if await self._write_with_retry(entry):
            await self._maybe_cleanup()
        elif self._spool_path is not None:
            await self._spool_append(entry)
        else:
            _log.error("MCP 调用轨迹写入失败且 spool 未配置，该条记录丢失: %s", entry.trace_id)

    async def _write_with_retry(self, entry: TraceEntry) -> bool:
        for index, delay in enumerate((*_RETRY_DELAYS, 0.0)):
            try:
                await self._store.record_mcp_trace(entry)
                return True
            except Exception as exc:  # noqa: BLE001 - 落库失败只能退避或进 spool
                _log.warning("MCP 调用轨迹写入失败（第 %d 次）: %s", index + 1, exc)
                if delay:
                    await anyio.sleep(delay)
        return False

    # -- 保留期清理（规格 §5） --------------------------------------------

    async def _maybe_cleanup(self) -> None:
        now = time.monotonic()
        if now - self._last_cleanup <= _CLEANUP_THROTTLE_SECONDS:
            return
        self._last_cleanup = now
        cleanup = getattr(self._store, "cleanup_mcp_traces", None)
        if cleanup is None:
            return
        cutoff = datetime.now(UTC) - timedelta(days=RETENTION_DAYS)
        try:
            await cleanup(cutoff)
        except Exception as exc:  # noqa: BLE001 - 清理失败不影响记录
            _log.warning("MCP 调用轨迹清理失败: %s", exc)

    # -- spool（规格 §4.2） ------------------------------------------------

    async def _spool_append(self, entry: TraceEntry) -> None:
        line = json.dumps(entry.as_row(), ensure_ascii=False) + "\n"
        path = self._spool_path
        if path is None:
            return
        try:
            parent = path.parent
            if not await anyio.Path(parent).is_dir():
                await anyio.Path(parent).mkdir(parents=True, exist_ok=True)
            async with await anyio.open_file(path, "a", encoding="utf-8") as handle:
                await handle.write(line)
                await handle.flush()
                await anyio.to_thread.run_sync(_fsync_fp, handle.wrapped)
        except OSError as exc:
            _log.error("MCP 调用轨迹 spool 不可写，该条记录丢失: %s", exc)
            return
        await self._trim_spool()

    async def _trim_spool(self) -> None:
        """spool 超过上限时保留最新的行，丢弃最旧部分（规格 §4.2）。"""
        path = self._spool_path
        if path is None:
            return
        try:
            size = (await anyio.Path(path).stat()).st_size
        except OSError:
            return
        if size <= _SPOOL_MAX_BYTES:
            return
        try:
            async with await anyio.open_file(path, "r", encoding="utf-8") as handle:
                content = await handle.read()
        except OSError as exc:
            _log.warning("MCP 调用轨迹 spool 超限后不可读: %s", exc)
            return
        lines = content.splitlines()
        kept: list[str] = []
        used = 0
        for line in reversed(lines):
            cost = len(line.encode("utf-8")) + 1
            if used + cost > _SPOOL_MAX_BYTES:
                break
            kept.append(line)
            used += cost
        dropped = len(lines) - len(kept)
        _log.warning("MCP 调用轨迹 spool 超过 %d 字节，丢弃最旧的 %d 行", _SPOOL_MAX_BYTES, dropped)
        trimmed = "\n".join(reversed(kept))
        await self._rewrite_spool(f"{trimmed}\n" if trimmed else "")

    async def _replay_spool(self) -> None:
        path = self._spool_path
        if path is None:
            return
        try:
            async with await anyio.open_file(path, "r", encoding="utf-8") as handle:
                content = await handle.read()
        except FileNotFoundError:
            return
        except OSError as exc:
            _log.warning("MCP 调用轨迹 spool 不可读: %s", exc)
            return
        if not content.strip():
            return
        replayed: list[str] = []
        for line in content.splitlines():
            if not line.strip():
                continue
            try:
                entry = entry_from_row(json.loads(line))
            except (ValueError, TypeError, KeyError) as exc:
                _log.warning("MCP 调用轨迹 spool 行无法解析，丢弃: %s", exc)
                continue
            try:
                await self._store.record_mcp_trace(entry)
            except Exception as exc:  # noqa: BLE001 - 单行失败保留在 spool
                _log.warning("MCP 调用轨迹补投失败，该行保留: %s", exc)
                replayed.append(line)
        if replayed:
            await self._rewrite_spool("\n".join(replayed) + "\n")
        else:
            await self._rewrite_spool("")

    async def _rewrite_spool(self, content: str) -> None:
        """原子替换：先写临时文件并 fsync，再一次性 rename 覆盖。"""
        path = self._spool_path
        if path is None:
            return
        tmp = anyio.Path(f"{path}.tmp")
        try:
            async with await anyio.open_file(tmp, "w", encoding="utf-8") as handle:
                await handle.write(content)
                await handle.flush()
                await anyio.to_thread.run_sync(_fsync_fp, handle.wrapped)
            await tmp.replace(path)
        except OSError as exc:
            _log.error("MCP 调用轨迹 spool 重写失败: %s", exc)


def _fsync_fp(fp: object) -> None:
    fp.flush()  # type: ignore[attr-defined]
    os.fsync(fp.fileno())  # type: ignore[attr-defined]


__all__ = ["RETENTION_DAYS", "TraceEntry", "TraceRecorder", "entry_from_row", "new_trace_id"]
