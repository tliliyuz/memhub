"""提炼队列落盘：写入方（ingest 采集、kb 上传）收到即写，worker 从这里读（全异步 IO）。

放在 `queue/` 而不是 `ingest/`：kb-api 的上传也要落同一个 raw_store，但 kb 不该
依赖采集协议层（鉴权、游标、<200ms 约束）。这里只保留与协议无关的落盘、计量与配额。

布局（内容寻址，重放与重复推送天然幂等）：

    <DATA_DIR>/raw_store/<device>/<source>/<sha[:2]>/<sha>.json

单个 JSON 文件包含该文件片段的元数据与正文；同一 sha 只会有一个文件，
同设备、同源内的重复内容不重写；若现存记录目标不一致，整批拒绝。
正文是 `content` 字段，路径仅作溯源。

写入用「临时文件 + 原子替换」：worker 只扫描到完整文件，不会读到半截 JSON。
"""

from __future__ import annotations

import json
import os
import re
import stat
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path, PureWindowsPath
from typing import Any, Literal

import anyio
from anyio import Path as AsyncPath

from memhub.contract import IngestRequest, explicit_project
from memhub.kb.manage import WriteDeferred, write_lock

_SAFE = re.compile(r"[^A-Za-z0-9_.-]")
# 每枚文件除正文外还有元数据外壳（路径、时间戳、sha 等），配额估算按此加项。
_PAYLOAD_OVERHEAD = 512
Producer = Literal["collector", "console"]
_QUEUE_ROOTS = ("raw_store", "processed_raw", "pending_review")
CONSOLE_DEVICE = "kb-console"


class BatchTargetConflict(Exception):
    def __init__(self) -> None:
        super().__init__("queue target conflict")


class QuotaExceeded(Exception):
    """raw_store 已到上限：该拒绝本批，而不是把磁盘写满。"""

    def __init__(self, used: int, limit: int, incoming: int) -> None:
        super().__init__(f"raw_store quota exceeded: {used}+{incoming} > {limit}")
        self.used = used
        self.limit = limit
        self.incoming = incoming


def _safe_id(value: str) -> str:
    """沿用队列地址映射；Windows 文件系统会忽略分量末尾的点。"""
    cleaned = _SAFE.sub("_", value)[:100]
    return cleaned.rstrip(".") if os.name == "nt" else cleaned


def _queue_component_valid(part: str) -> bool:
    if not part or part in {".", ".."}:
        return False
    if os.name != "nt":
        return True
    isreserved = getattr(os.path, "isreserved", None)
    return not (isreserved(part) if isreserved is not None else PureWindowsPath(part).is_reserved())


def batch_dir(data_dir: Path, device_id: str, source_id: str) -> Path:
    parts = (_safe_id(device_id), _safe_id(source_id))
    if not all(_queue_component_valid(part) for part in parts):
        raise BatchTargetConflict()
    return data_dir.joinpath("raw_store", *parts)


async def tree_size(root: Path) -> int:
    """目录下所有普通文件的大小之和；读不到的文件按 0 计（配额不能因 stat 失败放行）。"""
    root_path = AsyncPath(root)
    if not await root_path.is_dir():
        return 0
    total = 0
    async for item in root_path.rglob("*"):
        try:
            if await item.is_dir():
                continue
            total += (await item.stat()).st_size
        except OSError:
            continue
    return total


async def _purge_path_mode(path: AsyncPath) -> int:
    info = await path.lstat()
    reparse_point = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    if getattr(info, "st_file_attributes", 0) & reparse_point:
        raise BatchTargetConflict()
    return info.st_mode


async def _plan_source_purge(
    root: Path, relative: Path, device_id: str, source_id: str
) -> tuple[list[AsyncPath], list[AsyncPath]]:
    base = AsyncPath(root)
    try:
        for index in range(len(relative.parts) + 1):
            if index:
                base /= relative.parts[index - 1]
            if not stat.S_ISDIR(await _purge_path_mode(base)):
                raise BatchTargetConflict()
    except FileNotFoundError:
        return [], []

    files: list[AsyncPath] = []
    directories = [base]
    async for shard in base.iterdir():
        if not stat.S_ISDIR(await _purge_path_mode(shard)):
            raise BatchTargetConflict()
        directories.append(shard)
        async for batch in shard.iterdir():
            if batch.suffix != ".json" or not stat.S_ISREG(await _purge_path_mode(batch)):
                raise BatchTargetConflict()
            try:
                payload = json.loads(await batch.read_text(encoding="utf-8"))
            except (ValueError, RecursionError) as exc:
                raise BatchTargetConflict() from exc
            if not isinstance(payload, dict) or (
                payload.get("device_id"),
                payload.get("source_id"),
            ) != (device_id, source_id):
                raise BatchTargetConflict()
            files.append(batch)
    return files, directories


async def purge_source_files(data_dir: Path, device_id: str, source_id: str) -> dict[str, int]:
    """核对三个队列根下的批次归属后再删除；调用方须持有队列写锁。"""
    if _safe_id(device_id) != device_id or _safe_id(source_id) != source_id:
        raise BatchTargetConflict()
    relative = batch_dir(data_dir, device_id, source_id).relative_to(data_dir / "raw_store")
    plans = {
        root: await _plan_source_purge(data_dir / root, relative, device_id, source_id)
        for root in _QUEUE_ROOTS
    }
    counts: dict[str, int] = {}
    for root, (files, directories) in plans.items():
        for batch in files:
            await batch.unlink()
        for directory in reversed(directories):
            await directory.rmdir()
        counts[root] = len(files)
    return counts


def collector_device_reserved(device_id: str) -> bool:
    return _safe_id(device_id).rstrip(".").lower() == CONSOLE_DEVICE


@asynccontextmanager
async def queue_write_lock(data_dir: Path) -> AsyncIterator[None]:
    """采集器写入与状态更新串行；各进程必须共享同一个 data_dir。"""
    try:
        async with write_lock(data_dir / "state" / "collector-queue", timeout=2, recovery=True):
            yield
    except WriteDeferred as exc:
        raise OSError("queue lock unavailable") from exc


async def _existing_hashes(data_dir: Path, request: IngestRequest, producer: Producer) -> set[str]:
    project = explicit_project(request.project)
    if project is None:
        raise BatchTargetConflict()
    if producer == "console":
        if (request.device_id, request.source_type, request.source_id) != (
            CONSOLE_DEVICE,
            "docs",
            project,
        ):
            raise BatchTargetConflict()
    elif collector_device_reserved(request.device_id):
        raise BatchTargetConflict()

    base = batch_dir(data_dir, request.device_id, request.source_id)
    relative = base.relative_to(data_dir / "raw_store")
    existing: set[str] = set()
    for sha in {entry.sha256 for entry in request.files}:
        # worker 只向后移动，不重投。先查 raw，再查两个终态。
        for root in _QUEUE_ROOTS:
            path = data_dir / root / relative / sha[:2] / f"{sha}.json"
            try:
                text = await AsyncPath(path).read_text(encoding="utf-8")
            except FileNotFoundError:
                continue
            try:
                stored = json.loads(text)
            except ValueError as exc:
                raise BatchTargetConflict() from exc
            if not isinstance(stored, dict) or (
                stored.get("project"),
                stored.get("device_id"),
                stored.get("source_id"),
                stored.get("sha256"),
                stored.get("producer", producer),
            ) != (project, request.device_id, request.source_id, sha, producer):
                raise BatchTargetConflict()
            existing.add(sha)
    return existing


async def estimate_new_bytes(
    data_dir: Path, request: IngestRequest, *, producer: Producer = "collector"
) -> int:
    """配额只计新增哈希；重放已收内容不占额度。"""
    existing = await _existing_hashes(data_dir, request, producer)
    total = 0
    for batch_file in request.files:
        if batch_file.sha256 not in existing:
            total += len(batch_file.content.encode("utf-8")) + _PAYLOAD_OVERHEAD
            existing.add(batch_file.sha256)
    return total


class RawStoreQuota:
    """raw_store 用量上限（`MEMHUB_QUEUE_MAX_BYTES`）。

    为什么不是一个简单的「每次全量扫描」：worker 只在窗口内把文件搬去
    `processed_raw/`，白天 raw_store 只增不减，扫描成本随存量线性增长。
    这里缓存上次扫描结果，写入后按估算增量平移，最多每 `refresh_seconds`
    重扫一次纠正偏差（worker 搬运、人工清理都会让缓存偏大）。

    超限返回 1008（503）而不是静默丢弃：采集端按契约降级/暂停，数据留在本地。
    """

    def __init__(self, root: Path, limit: int, *, refresh_seconds: float = 30.0) -> None:
        self.root = root
        self.limit = limit
        self.refresh_seconds = refresh_seconds
        self._lock = anyio.Lock()
        self._used: int | None = None
        self._scanned_at = 0.0

    async def used_bytes(self) -> int:
        async with self._lock:
            return await self._used_cached()

    async def _used_cached(self) -> int:
        now = time.monotonic()
        if self._used is None or now - self._scanned_at >= self.refresh_seconds:
            self._used = await tree_size(self.root)
            self._scanned_at = now
        return self._used

    async def check(self, incoming: int) -> None:
        """抛出 QuotaExceeded；调用方把它翻成 1008。"""
        async with self._lock:
            used = await self._used_cached()
            if used + incoming > self.limit:
                raise QuotaExceeded(used=used, limit=self.limit, incoming=incoming)

    async def invalidate(self) -> None:
        """写盘中途失败时让下一次请求重扫，避免缓存低估真实占用。"""
        async with self._lock:
            self._used = None
            self._scanned_at = 0.0

    async def record(self, written_bytes: int) -> None:
        async with self._lock:
            if self._used is None:
                self._used = await tree_size(self.root)
                self._scanned_at = time.monotonic()
            self._used += written_bytes


async def save_batch(
    data_dir: Path, request: IngestRequest, *, producer: Producer = "collector"
) -> int:
    """先检查整批寻址冲突，再写入新内容。采集入口须持有 queue_write_lock。"""
    existing = await _existing_hashes(data_dir, request, producer)
    base = batch_dir(data_dir, request.device_id, request.source_id)
    written = 0
    for batch_file in request.files:
        if batch_file.sha256 in existing:
            continue
        target = base / batch_file.sha256[:2] / f"{batch_file.sha256}.json"
        payload: dict[str, Any] = {
            "producer": producer,
            "device_id": request.device_id,
            "source_id": request.source_id,
            "source_type": request.source_type,
            "project": request.project,
            "batch_id": request.batch_id,
            "path": batch_file.path,
            "from_offset": batch_file.from_offset,
            "to_offset": batch_file.to_offset,
            "mtime": batch_file.mtime.isoformat(),
            "sha256": batch_file.sha256,
            "content": batch_file.content,
        }
        await AsyncPath(target.parent).mkdir(parents=True, exist_ok=True)
        await _atomic_write_json(target, payload)
        existing.add(batch_file.sha256)
        written += 1
    return written


async def _atomic_write_json(target: Path, payload: dict[str, Any]) -> None:
    tmp = target.with_name(f"{target.name}.{uuid.uuid4().hex}.tmp")
    text = json.dumps(payload, ensure_ascii=False) + "\n"
    try:
        await AsyncPath(tmp).write_text(text, encoding="utf-8", newline="\n")
        await AsyncPath(tmp).replace(target)
    except BaseException:
        try:
            await AsyncPath(tmp).unlink()
        except OSError:
            pass
        raise


__all__ = [
    "CONSOLE_DEVICE",
    "BatchTargetConflict",
    "QuotaExceeded",
    "RawStoreQuota",
    "batch_dir",
    "collector_device_reserved",
    "estimate_new_bytes",
    "purge_source_files",
    "queue_write_lock",
    "save_batch",
    "tree_size",
]
