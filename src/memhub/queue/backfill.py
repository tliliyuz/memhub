"""旧本机队列（ADR-0020 之前的 `raw_store/`）一次性导入 CH 正文与 PG 队列。

只处理「已接收、未提炼」的 `raw_store/`；`processed_raw/` 与 `pending_review/` 是旧 worker
的终态，重新入队会产生重复知识或绕过复核，只统计不导入。脚本不删除、不改写任何源文件，
也不推进游标或批次记录——它不是采集入口，只是把积压补进新的内容寻址队列。

幂等由 `(project, sha256)` 内容寻址保证：已写入的正文与队列行都按重复跳过，失败后直接
重跑即可从断点继续。每个批次先写正文、再入队，与 `queue.flow.enqueue_batch` 的在线顺序一致。
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from anyio import Path as AsyncPath

from memhub.contract import BatchFile, IngestRequest
from memhub.queue.content import ContentUnavailable, RawContentStore
from memhub.queue.identity import BatchTargetConflict
from memhub.queue.tasks import Producer, QueueStore, QuotaExceeded, project_for

_RAW_ROOT = "raw_store"
_TERMINAL_ROOTS = ("processed_raw", "pending_review")
_REQUIRED = (
    "producer",
    "device_id",
    "source_id",
    "source_type",
    "project",
    "batch_id",
    "path",
    "from_offset",
    "to_offset",
    "mtime",
    "sha256",
    "content",
)
_GROUP_FIELDS = ("device_id", "source_id", "source_type", "batch_id")


@dataclass(frozen=True)
class LegacyFile:
    """一条旧 raw_store 记录；字段与旧版 save_batch 的 JSON 一一对应。"""

    relative: str
    producer: Producer
    device_id: str
    source_id: str
    source_type: str
    project: str
    batch_id: str
    path: str
    from_offset: int
    to_offset: int
    mtime: datetime
    sha256: str
    content: str

    @property
    def key(self) -> tuple[str, str, str, str, str]:
        return (self.producer, self.project, self.device_id, self.source_id, self.batch_id)


@dataclass(frozen=True)
class BackfillReport:
    scanned: int = 0
    valid: int = 0
    imported: int = 0
    duplicates: int = 0
    verified: int = 0
    failures: tuple[str, ...] = ()
    processed_raw: int = 0
    pending_review: int = 0
    dry_run: bool = False
    verify_only: bool = False


async def _parse(path: AsyncPath, data_dir: Path) -> LegacyFile:
    relative = path.relative_to(data_dir).as_posix()
    try:
        payload = json.loads(await path.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError) as exc:
        raise ValueError("不是合法 JSON") from exc
    if type(payload) is not dict:
        raise ValueError("记录不是 JSON 对象")
    missing = [name for name in _REQUIRED if name not in payload]
    if missing:
        raise ValueError(f"缺字段 {','.join(missing)}")
    producer = payload["producer"]
    if producer not in ("collector", "console"):
        raise ValueError(f"producer 不合法：{producer!r}")
    content = payload["content"]
    if type(content) is not str:
        raise ValueError("content 不是字符串")
    digest = payload["sha256"]
    if not isinstance(digest, str) or not _is_sha(digest):
        raise ValueError("sha256 不是 64 位小写十六进制")
    actual = hashlib.sha256(content.encode("utf-8")).hexdigest()
    if actual != digest:
        raise ValueError("sha256 与 content 不一致")
    if path.name != f"{digest}.json":
        raise ValueError("文件名与 sha256 不一致")
    try:
        mtime = datetime.fromisoformat(str(payload["mtime"]))
        from_offset = int(payload["from_offset"])
        to_offset = int(payload["to_offset"])
    except (TypeError, ValueError) as exc:
        raise ValueError("时间或偏移量不合法") from exc
    if from_offset < 0 or to_offset < from_offset:
        raise ValueError("偏移量不合法")
    record = LegacyFile(
        relative=relative,
        producer=producer,
        device_id=str(payload["device_id"]),
        source_id=str(payload["source_id"]),
        source_type=str(payload["source_type"]),
        project=str(payload["project"]),
        batch_id=str(payload["batch_id"]),
        path=str(payload["path"]),
        from_offset=from_offset,
        to_offset=to_offset,
        mtime=mtime,
        sha256=digest,
        content=content,
    )
    _request((record,))  # 身份与目标规则复用在线路径，提前暴露冲突
    return record


def _is_sha(value: str) -> bool:
    return len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _request(records: tuple[LegacyFile, ...] | list[LegacyFile]) -> IngestRequest:
    head = records[0]
    request = IngestRequest(
        batch_id=head.batch_id,
        device_id=head.device_id,
        source_id=head.source_id,
        source_type=head.source_type,
        project=head.project,
        files=[
            BatchFile(
                path=item.path,
                from_offset=item.from_offset,
                to_offset=item.to_offset,
                mtime=item.mtime,
                sha256=item.sha256,
                content=item.content,
            )
            for item in records
        ],
    )
    project_for(request, head.producer)
    return request


async def scan(data_dir: Path) -> tuple[list[LegacyFile], list[str], int, int]:
    """只读扫描：返回有效记录、失败说明与两个终态目录的文件数。"""
    raw_root = AsyncPath(data_dir) / _RAW_ROOT
    files: list[LegacyFile] = []
    failures: list[str] = []
    paths = await _json_files(raw_root)
    for path in paths:
        try:
            files.append(await _parse(path, data_dir))
        except (ValueError, BatchTargetConflict, OSError) as exc:
            reason = str(exc) or type(exc).__name__
            failures.append(f"{path.relative_to(data_dir).as_posix()}: {reason}")
    terminal: dict[str, int] = {}
    for root in _TERMINAL_ROOTS:
        terminal[root] = len(await _json_files(AsyncPath(data_dir) / root))
    return files, failures, terminal["processed_raw"], terminal["pending_review"]


async def _json_files(root: AsyncPath) -> list[AsyncPath]:
    if not await root.is_dir():
        return []
    found = [item async for item in root.rglob("*.json")]
    return sorted(found, key=lambda item: str(item))


def _groups(files: list[LegacyFile]) -> dict[tuple[str, str, str, str, str], list[LegacyFile]]:
    grouped: dict[tuple[str, str, str, str, str], list[LegacyFile]] = defaultdict(list)
    for item in files:
        grouped[item.key].append(item)
    return grouped


def _label(records: list[LegacyFile]) -> str:
    head = records[0]
    return f"{head.project}/{head.batch_id}@{head.producer}"


async def _import_group(
    records: list[LegacyFile],
    *,
    queue: QueueStore,
    content: RawContentStore,
    limit: int,
    dry_run: bool,
) -> tuple[int, int]:
    request = _request(records)
    producer = records[0].producer
    plan = await queue.check(request, producer=producer, limit=limit)
    stored = await content.existing(
        request.device_id,
        request.source_id,
        [entry.sha256 for entry in plan.entries],
    )
    if any(project != plan.project for project in stored.values()):
        raise BatchTargetConflict()
    if dry_run:
        return plan.accepted, plan.duplicates
    if plan.entries:
        await content.put(plan.entries)
    outcome = await queue.enqueue(request, producer=producer, limit=limit)
    return outcome.accepted, outcome.duplicates


async def _verify_group(
    records: list[LegacyFile],
    *,
    queue: QueueStore,
    content: RawContentStore,
) -> tuple[int, list[str]]:
    head = records[0]
    queued = {item.sha256 for item in await queue.batch_items(head.project, head.batch_id)}
    stored = await content.existing(
        head.device_id, head.source_id, [item.sha256 for item in records]
    )
    verified = 0
    failures: list[str] = []
    for item in records:
        missing = []
        if item.sha256 not in queued:
            missing.append("队列行")
        if stored.get(item.sha256) != item.project:
            missing.append("正文")
        if missing:
            failures.append(f"{item.relative}: 缺 {'、'.join(missing)}")
        else:
            verified += 1
    return verified, failures


async def run_backfill(
    data_dir: Path,
    *,
    queue: QueueStore,
    content: RawContentStore,
    limit: int,
    dry_run: bool = False,
    verify_only: bool = False,
) -> BackfillReport:
    """扫描并导入（或核验）旧队列；任何失败都只记录，不中断其余批次。"""
    if dry_run and verify_only:
        raise ValueError("--dry-run 与 --verify-only 不能同时使用")
    files, scan_failures, processed_raw, pending_review = await scan(data_dir)
    if verify_only:
        imported = duplicates = 0
        verified = 0
        failures = scan_failures
        for records in _groups(files).values():
            try:
                ok, group_failures = await _verify_group(records, queue=queue, content=content)
            except (BatchTargetConflict, ContentUnavailable, OSError) as exc:
                failures.append(f"{_label(records)}: {type(exc).__name__}")
                continue
            verified += ok
            failures.extend(group_failures)
    else:
        imported = duplicates = 0
        failures = scan_failures
        for records in _groups(files).values():
            try:
                accepted, repeated = await _import_group(
                    records,
                    queue=queue,
                    content=content,
                    limit=limit,
                    dry_run=dry_run,
                )
            except (BatchTargetConflict, QuotaExceeded, ContentUnavailable, OSError) as exc:
                failures.append(f"{_label(records)}: {type(exc).__name__}")
                continue
            imported += accepted
            duplicates += repeated
        verified = 0
    return BackfillReport(
        scanned=len(files) + len(scan_failures),
        valid=len(files),
        imported=imported,
        duplicates=duplicates,
        verified=verified,
        failures=tuple(failures),
        processed_raw=processed_raw,
        pending_review=pending_review,
        dry_run=dry_run,
        verify_only=verify_only,
    )


__all__ = ["BackfillReport", "LegacyFile", "run_backfill", "scan"]
