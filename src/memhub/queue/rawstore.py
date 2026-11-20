"""提炼队列落盘：写入方（ingest 采集、kb 上传）收到即写，worker 从这里读（全异步 IO）。

放在 `queue/` 而不是 `ingest/`：kb-api 的上传也要落同一个 raw_store，但 kb 不该
依赖采集协议层（鉴权、游标、<200ms 约束）。这里只保留与协议无关的落盘、计量与配额。

布局（内容寻址，重放与重复推送天然幂等）：

    <DATA_DIR>/raw_store/<device>/<source>/<sha[:2]>/<sha>.json

单个 JSON 文件包含该文件片段的元数据与正文；同一 sha 只会有一个文件，
所以在移动端重推同一批时只会覆盖成相同内容，不会膨胀。

为什么按 sha 而不是按设备路径：worker 按内容处理，同一份内容被两个设备/路径
推上来只该提炼一次；正文本身是 `content` 字段，路径只作溯源信息保留。

写入用「临时文件 + 原子替换」：worker 只扫描到完整文件，不会读到半截 JSON。
"""

from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path
from typing import Any

import anyio
from anyio import Path as AsyncPath

from memhub.contract import IngestRequest

_SAFE = re.compile(r"[^A-Za-z0-9_.-]")
# 每枚文件除正文外还有元数据外壳（路径、时间戳、sha 等），配额估算按此加项。
_PAYLOAD_OVERHEAD = 512


class QuotaExceeded(Exception):
    """raw_store 已到上限：该拒绝本批，而不是把磁盘写满。"""

    def __init__(self, used: int, limit: int, incoming: int) -> None:
        super().__init__(f"raw_store quota exceeded: {used}+{incoming} > {limit}")
        self.used = used
        self.limit = limit
        self.incoming = incoming


def _safe_id(value: str) -> str:
    """设备/来源 id 直接拼路径前做白名单化；不做路径拼接攻击面。"""
    cleaned = _SAFE.sub("_", value)
    return cleaned[:100] or "_"


def batch_dir(data_dir: Path, device_id: str, source_id: str) -> Path:
    return data_dir / "raw_store" / _safe_id(device_id) / _safe_id(source_id)


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


async def estimate_new_bytes(data_dir: Path, request: IngestRequest) -> int:
    """本批实际会新增的字节数：已落盘的 sha 不会再写，配额不该把它们算进去。

    重放同一批在配额满时仍必须成功——否则采集端会被永久卡死在一条已经收下的数据上。
    """
    base = batch_dir(data_dir, request.device_id, request.source_id)
    total = 0
    for batch_file in request.files:
        target = base / batch_file.sha256[:2] / f"{batch_file.sha256}.json"
        if not await AsyncPath(target).is_file():
            total += len(batch_file.content.encode("utf-8")) + _PAYLOAD_OVERHEAD
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


async def save_batch(data_dir: Path, request: IngestRequest) -> int:
    """落一批原始增量；返回写入（或覆盖）的文件数。

    调用方保证本批已通过 `StateStore.apply()`——这里不判断游标与去重，
    只保证「已接受批次里的内容确实在盘上」。失败时抛 OSError，由调用方
    决定是否整批返回错误（当前策略：抛 500，客户端会重推）。
    """
    base = batch_dir(data_dir, request.device_id, request.source_id)
    written = 0
    for batch_file in request.files:
        target = base / batch_file.sha256[:2] / f"{batch_file.sha256}.json"
        if await AsyncPath(target).is_file():
            # 完全相同的内容已经落过盘；重放/跨设备重复推送走到这里。
            continue
        payload: dict[str, Any] = {
            "device_id": request.device_id,
            "source_id": request.source_id,
            "source_type": request.source_type,
            # 目标知识库由采集端选（桌面端 UI 里按目录指定）；worker 落到
            # knowledge/<project>/。"auto" 时 worker 回退 source_id（旧行为）。
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
    "QuotaExceeded",
    "RawStoreQuota",
    "batch_dir",
    "estimate_new_bytes",
    "save_batch",
    "tree_size",
]
