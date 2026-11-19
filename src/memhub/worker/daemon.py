"""worker 守护进程：raw_store → 抽取 → merge 进知识真源（全异步 IO）。

单并发串行（池=1）：LLM 调用是瓶颈也是成本，串行让错峰窗口、内存预算、
失败退避都可预测。多个容器实例不会互相踩——raw 文件处理成功即移动到
`processed_raw/`，移动是原子的，两个进程抢同一文件只有一个能得手。

窗口门控：`--window 21:00-02:00`（本地时间，跨午夜）内才处理；窗口外睡眠等待。
不传窗口则一直跑。

失败语义：
- 单文件抽取失败 → 留在 raw_store，下一轮重试，本轮继续处理其他文件；
- LLM 端点启动自检失败 → exit 2（配置错误，别进循环空转把日志写满）；
- 运行期连续失败按指数退避，日志只打摘要，不打 traceback。
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from datetime import time as dt_time
from pathlib import Path
from urllib.parse import urlparse

import anyio
from anyio import Path as AsyncPath

from memhub.contract import SourceKind, SourceRef
from memhub.kb.store import KnowledgeStore
from memhub.worker.extract import ExtractionFailed, extract_document
from memhub.worker.llm import LLMClient, LLMError
from memhub.worker.merge import merge
from memhub.worker.prompts import load_profile
from memhub.worker.render import render_jsonl

PROFILE_BY_SOURCE = {"sessions": "sessions", "wiki": "wiki", "docs": "wiki"}


@dataclass
class WorkerConfig:
    data_dir: Path
    knowledge_dir: Path
    model: str
    max_chars: int = 12000
    max_input_chars: int = 60000
    window: str | None = None
    interval: float = 300.0
    limit: int = 20
    max_attempts: int = 3

    @property
    def raw_root(self) -> Path:
        return self.data_dir / "raw_store"

    @property
    def processed_root(self) -> Path:
        return self.data_dir / "processed_raw"

    @property
    def pending_root(self) -> Path:
        return self.data_dir / "pending_review"

    @property
    def failures_path(self) -> Path:
        return self.data_dir / "state" / "failures.json"


@dataclass
class RoundReport:
    processed: int = 0
    failed: int = 0
    created: int = 0
    updated: int = 0
    edges: int = 0
    errors: list[str] = field(default_factory=list)


def parse_window(spec: str) -> tuple[dt_time, dt_time]:
    """`"21:00-02:00"` → (21:00, 02:00)；只接受 HH:MM。"""
    try:
        start_raw, end_raw = spec.split("-", 1)
        start = dt_time.fromisoformat(start_raw.strip())
        end = dt_time.fromisoformat(end_raw.strip())
    except ValueError as exc:
        raise ValueError(f"窗口格式应为 HH:MM-HH:MM，收到 {spec!r}") from exc
    return start, end


def in_window(now: dt_time, window: tuple[dt_time, dt_time]) -> bool:
    start, end = window
    if start <= end:
        return start <= now < end
    return now >= start or now < end  # 跨午夜


async def iter_pending(raw_root: Path, processed_root: Path) -> list[Path]:
    """未处理的 raw 文件，按修改时间升序（先来先提炼）。"""
    if not await AsyncPath(raw_root).is_dir():
        return []
    pending: list[tuple[float, Path]] = []
    async for item in AsyncPath(raw_root).rglob("*.json"):
        path = Path(item)
        relative = path.relative_to(raw_root)
        if await AsyncPath(processed_root / relative).exists():
            continue
        try:
            mtime = (await item.stat()).st_mtime
        except OSError:
            continue
        pending.append((mtime, path))
    pending.sort(key=lambda entry: entry[0])
    return [path for _mtime, path in pending]


async def probe_endpoint(base_url: str, *, timeout: float = 5.0) -> None:
    """启动自检：只做 DNS/TCP 可达性，不发模型请求（不发钱）。"""
    parsed = urlparse(base_url)
    host = parsed.hostname
    if not host:
        raise LLMError(f"LLM base URL 无法解析主机: {base_url!r}")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        with anyio.fail_after(timeout):
            _reader, writer = await asyncio.open_connection(host, port)
            writer.close()
            await writer.wait_closed()
        return
    except (OSError, TimeoutError) as exc:
        raise LLMError(f"LLM 端点不可达 {host}:{port}: {exc}") from exc


async def _move(config: WorkerConfig, path: Path, root: Path) -> None:
    relative = path.relative_to(config.raw_root)
    target = root / relative
    await AsyncPath(target.parent).mkdir(parents=True, exist_ok=True)
    await AsyncPath(path).replace(target)


async def _mark_processed(config: WorkerConfig, path: Path) -> None:
    await _move(config, path, config.processed_root)


async def _move_to(config: WorkerConfig, path: Path, root: Path) -> None:
    await _move(config, path, root)


async def _load_failures(config: WorkerConfig) -> dict[str, int]:
    try:
        text = await AsyncPath(config.failures_path).read_text(encoding="utf-8")
        data = json.loads(text)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(key): int(value) for key, value in data.items() if isinstance(value, int)}


async def _save_failures(config: WorkerConfig, failures: dict[str, int]) -> None:
    path = config.failures_path
    await AsyncPath(path.parent).mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    await AsyncPath(tmp).write_text(
        json.dumps(failures, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    await AsyncPath(tmp).replace(path)


PROCESSED_KEEP = timedelta(days=7)
PROCESSED_MAX_BYTES = 2 * 1024**3


async def _reclaim_empty_dirs(root: Path) -> None:
    """空目录一并回收，否则设备/source 目录会留一摞空壳。"""
    if not await AsyncPath(root).is_dir():
        return
    dirs = [path async for path in AsyncPath(root).rglob("*") if await path.is_dir()]
    # rglob 不含起点自身；根目录最后删（`os.walk(topdown=False)` 的等价行为）。
    dirs.append(AsyncPath(root))
    for path in sorted(dirs, key=lambda item: len(item.parts), reverse=True):
        try:
            await path.rmdir()
        except OSError:
            pass


async def purge_pending_review(
    data_dir: Path, *, older_than: timedelta = timedelta(days=30)
) -> tuple[int, int]:
    """清理 `pending_review/` 里超过保留期的文件，返回（文件数, 字节数）。

    隔离区只放「连续失败 3 次」的毒文件：人工排查完它就是纯占盘。没有清理策略时
    它会和 raw_store 一起把磁盘预算吃穿（raw_store 有配额，隔离区没有），因此
    由 purge-expired timer 每天顺手收一次。
    """
    root = data_dir / "pending_review"
    if not await AsyncPath(root).is_dir():
        return 0, 0
    cutoff = time.time() - older_than.total_seconds()
    removed = removed_bytes = 0
    async for item in AsyncPath(root).rglob("*"):
        if await item.is_dir():
            continue
        try:
            stat = await item.stat()
        except OSError:
            continue
        if stat.st_mtime >= cutoff:
            continue
        try:
            await item.unlink()
        except OSError:
            continue
        removed += 1
        removed_bytes += stat.st_size
    await _reclaim_empty_dirs(root)
    return removed, removed_bytes


async def prune_processed_raw(
    data_dir: Path,
    *,
    max_bytes: int = PROCESSED_MAX_BYTES,
    older_than: timedelta = PROCESSED_KEEP,
) -> tuple[int, int]:
    """裁剪 `processed_raw/`，返回（文件数, 字节数）。

    这个目录是 raw_store 的**完整副本**（处理成功后移动过去，供事后重跑抽取）。
    它不受 `MEMHUB_QUEUE_MAX_BYTES` 约束：配额一满 ingest 就 1008，但历史副本
    会无限增长，磁盘照样能被写满——上次事故的同一条路径。因此按「时间 + 总量」
    双阈值裁剪：超过 7 天或总量超过 2 GiB 时按最旧优先删除。原始增量仍在云端
    PG 的批次窗口内可重放（24h），markdown 真源也保留了溯源信息。
    """
    root = data_dir / "processed_raw"
    if not await AsyncPath(root).is_dir():
        return 0, 0
    entries: list[tuple[float, int, Path]] = []
    async for item in AsyncPath(root).rglob("*"):
        if await item.is_dir():
            continue
        try:
            stat = await item.stat()
        except OSError:
            continue
        entries.append((stat.st_mtime, stat.st_size, Path(item)))
    entries.sort(key=lambda item: item[0])
    cutoff = time.time() - older_than.total_seconds()
    total = sum(size for _mtime, size, _path in entries)
    removed = removed_bytes = 0
    for mtime, size, path in entries:
        if mtime >= cutoff and total <= max_bytes:
            break  # 已是最旧且两条阈值都满足，后面只会更新
        try:
            await AsyncPath(path).unlink()
        except OSError:
            continue
        total -= size
        removed += 1
        removed_bytes += size
    await _reclaim_empty_dirs(root)
    return removed, removed_bytes


def _document_text(payload: dict[str, object]) -> str:
    content = str(payload.get("content", ""))
    path = str(payload.get("path", ""))
    if path.endswith(".jsonl"):
        rendered = render_jsonl(content)
        # 增量可能从事件中间切出来，整段都不是合法 JSON 行时退回原文：
        # 静默丢掉一段真实增量比抽到噪音更糟。
        return rendered or content
    return content


async def process_file(
    client: LLMClient,
    config: WorkerConfig,
    path: Path,
    *,
    templates: dict[str, str] | None = None,
) -> tuple[int, int, int]:
    """处理一个 raw 文件；返回 (created, updated, edges)。失败抛异常，由调用方隔离。"""
    payload = json.loads(await AsyncPath(path).read_text(encoding="utf-8"))
    source_id = str(payload.get("source_id", "unknown"))
    source_type = str(payload.get("source_type", "sessions"))
    device_id = str(payload.get("device_id", "unknown"))
    file_path = str(payload.get("path", path.name))

    text = _document_text(payload)[: config.max_input_chars]
    # 日志里要能区分「渲染后为空」和「模型拒抽」：两者在 `+0 new` 上完全同形，
    # 排查时只能靠这一行字符数判断问题出在渲染还是提示词。
    print(f"[worker] text {path.name}: {len(text)} chars", flush=True)
    if not text.strip():
        return 0, 0, 0

    profile = PROFILE_BY_SOURCE.get(source_type, "sessions")
    if templates is None or profile not in templates:
        templates = dict(templates or {})
        templates[profile] = await load_profile(profile)

    extraction = await extract_document(
        client,
        template=templates[profile],
        path=file_path,
        text=text,
        model=config.model,
        max_chars=config.max_chars,
    )
    store = KnowledgeStore(config.knowledge_dir)
    kind = SourceKind.SESSION if source_type == "sessions" else SourceKind.WIKI
    report = await merge(
        store,
        extraction,
        project=source_id,
        source=SourceRef(type=kind, ref=file_path, device=device_id),
    )
    return len(report.created), len(report.updated), report.edges_added


async def run_round(
    client: LLMClient,
    config: WorkerConfig,
    *,
    report: RoundReport | None = None,
) -> RoundReport:
    """处理一批待提炼文件；不抛单文件异常。"""
    current = report or RoundReport()
    templates: dict[str, str] = {}
    failures = await _load_failures(config)
    dirty = False
    pending = await iter_pending(config.raw_root, config.processed_root)
    for path in pending[: config.limit]:
        relative = str(path.relative_to(config.raw_root))
        try:
            created, updated, edges = await process_file(client, config, path, templates=templates)
        except (ExtractionFailed, LLMError, OSError, ValueError) as exc:
            current.failed += 1
            current.errors.append(f"{path.name}: {type(exc).__name__}: {exc}")
            attempts = failures.get(relative, 0) + 1
            dirty = True
            if attempts >= config.max_attempts:
                # 毒文件不能让队列永远红着：再试下去每轮都在同一处付费失败。
                # 移出 raw_store，留原始字节 + 失败原因给人看。
                await _move_to(config, path, config.pending_root)
                failures.pop(relative, None)
                print(
                    f"[worker] quarantine {path.name}: 连续 {attempts} 次失败"
                    f" → pending_review/ ({type(exc).__name__}: {exc})",
                    file=sys.stderr,
                )
            else:
                failures[relative] = attempts
                print(
                    f"[worker] fail {path.name} ({attempts}/{config.max_attempts}):"
                    f" {type(exc).__name__}: {exc}",
                    file=sys.stderr,
                )
            continue
        await _mark_processed(config, path)
        if failures.pop(relative, None) is not None:
            dirty = True
        current.processed += 1
        current.created += created
        current.updated += updated
        current.edges += edges
        print(
            f"[worker] ok {path.name}: +{created} new, {updated} updated, {edges} edges",
            flush=True,
        )
    if dirty:
        await _save_failures(config, failures)
    return current


async def run_forever(
    client: LLMClient,
    config: WorkerConfig,
    *,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    max_rounds: int | None = None,
) -> int:
    """主循环；返回进程退出码（0 无失败，1 有失败）。"""
    window = parse_window(config.window) if config.window else None
    failure_streak = 0
    rounds = 0
    while max_rounds is None or rounds < max_rounds:
        rounds += 1
        local_now = now().astimezone()
        if window is not None and not in_window(local_now.time(), window):
            print(f"[worker] 窗口外（{config.window}），休眠 {config.interval:.0f}s", flush=True)
            await sleep(config.interval)
            continue
        report = await run_round(client, config)
        if report.processed or report.failed:
            print(
                f"[worker] round: {report.processed} ok / {report.failed} fail "
                f"/ +{report.created} new / {report.updated} updated",
                flush=True,
            )
        if report.failed:
            failure_streak += 1
            await sleep(min(1800.0, config.interval * 2 ** min(failure_streak, 4)))
        else:
            failure_streak = 0
            if not report.processed:
                await sleep(config.interval)
    return 1 if failure_streak else 0


__all__ = [
    "PROFILE_BY_SOURCE",
    "RoundReport",
    "WorkerConfig",
    "in_window",
    "iter_pending",
    "parse_window",
    "probe_endpoint",
    "process_file",
    "prune_processed_raw",
    "purge_pending_review",
    "run_forever",
    "run_round",
]
