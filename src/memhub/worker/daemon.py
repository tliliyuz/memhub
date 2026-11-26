"""worker 守护进程：raw_store → 抽取 → merge 进知识真源（全异步 IO）。

单并发串行（池=1）：LLM 调用是瓶颈也是成本，串行让错峰窗口、内存预算、
失败退避都可预测。多个容器实例不会互相踩——raw 文件处理成功即移动到
`processed_raw/`，移动是原子的，两个进程抢同一文件只有一个能得手。

窗口门控：`--window 21:00-02:00`（本地时间，跨午夜）内才处理；窗口外睡眠等待。
不传窗口则一直跑。

失败语义：
- 单文件抽取失败 → 留在 raw_store，下一轮重试，本轮继续处理其他文件；
- 授权明确拒绝 → 原始字节直接移入 pending_review，不消耗失败重试次数；
- 授权无法核实或真源写入推迟 → 保留原始文件和失败次数；
- LLM 端点启动自检失败 → exit 2（配置错误，别进循环空转把日志写满）；
- 运行期连续失败按指数退避，日志只打摘要，不打 traceback。
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone, tzinfo
from datetime import time as dt_time
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import anyio
from anyio import Path as AsyncPath

from memhub.contract import SourceKind, SourceRef, explicit_project
from memhub.kb.manage import WriteDeferred
from memhub.kb.pgstore import PgKnowledgeStore
from memhub.kb.store import KnowledgeStore
from memhub.kb.target_access import TargetRegistry, TargetUnavailable
from memhub.queue.rawstore import (
    CONSOLE_DEVICE,
    BatchTargetConflict,
    batch_dir,
    collector_device_reserved,
)
from memhub.worker.extract import ExtractionFailed, extract_document, extract_session
from memhub.worker.llm import LLMClient, LLMError
from memhub.worker.merge import merge
from memhub.worker.prompts import load_profile
from memhub.worker.render import (
    SessionBlock,
    render_jsonl_events,
    render_plaintext_blocks,
    render_session_blocks,
    truncate_blocks,
)

if TYPE_CHECKING:
    from memhub.ingest.store import StateStore

PROFILE_BY_SOURCE = {"sessions": "sessions", "wiki": "wiki", "docs": "wiki"}


class AuthorizationDenied(ValueError):
    """仅携带固定原因码的永久拒绝，不含原始正文。"""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class MessageIndexUnavailable(RuntimeError):
    """已见消息索引不可用（表缺失/库不可用）：推迟文件，不消耗重试也不调 LLM。"""


@dataclass(frozen=True)
class ProcessedFile:
    """单文件处理结果；`skipped_extraction` 表示消息全部见过、没有调用模型。"""

    created: int = 0
    updated: int = 0
    edges: int = 0
    skipped_extraction: bool = False
    filtered_messages: int = 0


@dataclass
class WorkerConfig:
    data_dir: Path
    store: KnowledgeStore | PgKnowledgeStore
    model: str
    max_chars: int = 12000
    max_input_chars: int = 60000
    # 单次 LLM 调用的输出预算（含 thinking）。8000 会被 thinking 吃光、拿不到
    # text 块，线上首跑已踩；默认 32000，可用 MEMHUB_LLM_MAX_TOKENS 覆盖。
    max_tokens: int = 32000
    window: str | None = None
    # 窗口按哪个时区解释。None = 系统本地时区（容器里通常是 UTC！）。
    # 线上踩过：没设 TZ 的容器让 `--window 21:00-02:00` 实际跑在 05:00-10:00 CST。
    window_tz: tzinfo | None = None
    interval: float = 300.0
    limit: int = 20
    max_attempts: int = 3
    target_registry: TargetRegistry | None = None
    is_registered: Callable[[str], Awaitable[bool]] | None = None
    # 运行态库；缺省时关闭消息 uuid 去重（管理台上传与 dev 联调保持旧行为）。
    state: StateStore | None = None

    def registry(self) -> TargetRegistry:
        return self.target_registry or TargetRegistry(self.store)

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
    quarantined: int = 0
    deduped: int = 0


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


def parse_window_tz(spec: str) -> tzinfo | None:
    """窗口时区：空 = 系统本地；`UTC` / `+08:00` / IANA 名（IANA 依赖系统 tzdata）。

    只用显式偏移就不必给镜像装 tzdata——slim 镜像缺 zoneinfo 时
    `astimezone()` 会静默退回 UTC，线上正是这样把 21:00 跑成了 05:00。
    """
    text = spec.strip()
    if not text:
        return None
    if text.upper() == "UTC":
        return UTC
    match = re.fullmatch(r"([+-])(\d{1,2}):?(\d{2})", text)
    if match:
        sign, hours, minutes = match.groups()
        if int(hours) > 14 or int(minutes) > 59:
            raise ValueError(f"窗口时区偏移非法：{spec!r}")
        delta = timedelta(hours=int(hours), minutes=int(minutes))
        return timezone(-delta if sign == "-" else delta)
    try:
        return ZoneInfo(text)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(
            f"不认识的窗口时区：{spec!r}（可用 UTC / +08:00 / IANA 名；IANA 需要系统 tzdata）"
        ) from exc


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

    隔离区保留授权拒绝和重试耗尽的原始文件供人工检查。没有清理策略时，
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


def _document_text(content: str, path: str) -> str:
    if path.endswith(".jsonl"):
        rendered, events = render_jsonl_events(content)
        return rendered if events else content
    return content


@dataclass(frozen=True)
class QueueTarget:
    project: str
    device_id: str
    source_id: str
    source_type: str
    console: bool


def _queue_target(config: WorkerConfig, payload: dict[str, object], path: Path) -> QueueTarget:
    project = explicit_project(payload.get("project"))
    if project is None:
        raise AuthorizationDenied("project_required")
    producer = payload.get("producer")
    if "producer" in payload and producer not in ("collector", "console"):
        raise AuthorizationDenied("producer_unrecognized")
    device_id, source_id, source_type = (
        payload.get("device_id"),
        payload.get("source_id"),
        payload.get("source_type"),
    )
    if (
        not isinstance(device_id, str)
        or not device_id
        or not isinstance(source_id, str)
        or not source_id
        or not isinstance(source_type, str)
        or source_type not in PROFILE_BY_SOURCE
    ):
        raise AuthorizationDenied("queue_identity_invalid")
    sha = payload.get("sha256")
    if not isinstance(sha, str) or re.fullmatch(r"[0-9a-f]{64}", sha) is None:
        raise AuthorizationDenied("queue_identity_invalid")
    try:
        directory = batch_dir(config.data_dir, device_id, source_id)
    except BatchTargetConflict:
        raise AuthorizationDenied("queue_identity_invalid") from None
    expected = directory / sha[:2] / f"{sha}.json"
    if expected.relative_to(config.raw_root).parts != path.relative_to(config.raw_root).parts:
        raise AuthorizationDenied("queue_identity_mismatch")

    # 即使带管理台标记，也必须符合保留的生产者身份。
    exact_console = device_id == CONSOLE_DEVICE and source_type == "docs" and source_id == project
    if producer == "console" or (producer is None and exact_console):
        if not exact_console:
            raise AuthorizationDenied("console_identity_invalid")
        return QueueTarget(project, device_id, source_id, source_type, console=True)
    if collector_device_reserved(device_id):
        raise AuthorizationDenied("console_identity_invalid")
    return QueueTarget(project, device_id, source_id, source_type, console=False)


async def _authorize(config: WorkerConfig, registry: TargetRegistry, target: QueueTarget) -> None:
    """在真源写锁内复查目标状态（登记设备、已登记且活动、未被归档）。"""
    if not target.console:
        if config.is_registered is None:
            raise TargetUnavailable("registration_unavailable")
        try:
            registered = await config.is_registered(target.device_id)
        except Exception as exc:
            # 不同 StateStore 实现可能抛出不同类型的数据库异常。
            raise TargetUnavailable("registration_unavailable") from exc
        if not registered:
            raise AuthorizationDenied("device_not_registered")
    if not await registry.active(target.project):
        raise AuthorizationDenied("target_inactive")
    try:
        await config.store.guard_write(target.project)
    except WriteDeferred as exc:
        if exc.reason == "archived":
            raise AuthorizationDenied("target_inactive") from None
        raise
    except OSError as exc:
        raise TargetUnavailable("archive_state_unavailable") from exc


async def _drop_seen_blocks(
    state: StateStore, target: QueueTarget, blocks: list[SessionBlock], path: Path
) -> tuple[list[SessionBlock], int]:
    """过滤已成功抽取过的消息块；返回 (保留块, 已见消息数)。

    只有带 `message_id` 的块参与过滤；无 uuid 的来源（纯文本等）行为不变。
    索引查询失败抛 `MessageIndexUnavailable`，由调用方推迟整份文件。
    """
    ids = sorted({block.message_id for block in blocks if block.message_id is not None})
    if not ids:
        return blocks, 0
    try:
        seen = await state.seen_messages(target.project, target.source_id, ids)
    except Exception as exc:
        # 不同 StateStore 实现可能抛出不同类型的数据库异常。
        raise MessageIndexUnavailable("seen_lookup") from exc
    if not seen:
        return blocks, 0
    kept = [block for block in blocks if block.message_id is None or block.message_id not in seen]
    print(
        f"[worker] dedupe {path.name}: 已见 {len(seen)} 条，剩余 {len(ids) - len(seen)} 条",
        flush=True,
    )
    if not kept:
        print(f"[worker] dedupe {path.name}: 全部消息已见过，跳过抽取", flush=True)
    return kept, len(seen)


async def _mark_blocks_seen(
    config: WorkerConfig, target: QueueTarget, blocks: list[SessionBlock], path: Path
) -> None:
    """抽取与 merge 成功后记账；失败只记 ERROR，不把已完成的文件判失败。"""
    state = config.state
    if state is None:
        return
    ids = sorted({block.message_id for block in blocks if block.message_id is not None})
    if not ids:
        return
    try:
        await state.mark_messages_seen(target.project, target.source_id, ids)
    except Exception as exc:  # noqa: BLE001 - 记账失败只能记日志，不能让已完成文件失败
        print(f"[worker] mark-seen failed {path.name}: {type(exc).__name__}", file=sys.stderr)


async def process_file(
    client: LLMClient,
    config: WorkerConfig,
    path: Path,
    *,
    templates: dict[str, str] | None = None,
) -> ProcessedFile:
    """处理一个 raw 文件；失败抛异常，由调用方隔离。"""
    try:
        payload = json.loads(await AsyncPath(path).read_text(encoding="utf-8"))
    except (ValueError, RecursionError):
        raise AuthorizationDenied("queue_payload_invalid") from None
    if not isinstance(payload, dict):
        raise AuthorizationDenied("queue_payload_invalid")
    target = _queue_target(config, payload, path)
    registry = config.registry()

    async def check_target() -> None:
        await _authorize(config, registry, target)

    # 空输入也要授权；等待模型时不持写真源的锁。
    async with config.store.write_scope(timeout=0):
        await check_target()

    file_path = payload.get("path")
    content = payload.get("content")
    if not isinstance(file_path, str) or not isinstance(content, str):
        raise AuthorizationDenied("queue_payload_invalid")
    profile = PROFILE_BY_SOURCE[target.source_type]
    is_session = profile == "sessions"
    blocks: list[SessionBlock] = []
    filtered = 0
    if is_session:
        blocks = (
            render_session_blocks(content)
            if Path(file_path).suffix.lower() == ".jsonl"
            else render_plaintext_blocks(content)
        )
        # 先去已见消息，再把输入预算留给新内容。
        if config.state is not None:
            blocks, filtered = await _drop_seen_blocks(config.state, target, blocks, path)
        all_seen = bool(filtered) and not blocks
        blocks = truncate_blocks(blocks, config.max_input_chars)
        if not blocks:
            return ProcessedFile(skipped_extraction=all_seen, filtered_messages=filtered)
    else:
        text = _document_text(content, file_path)[: config.max_input_chars]
        if not text.strip():
            return ProcessedFile()

    if templates is None:
        templates = {}
    if profile not in templates:
        templates[profile] = await load_profile(profile)
    if is_session:
        extraction = await extract_session(
            client,
            template=templates[profile],
            path=file_path,
            blocks=blocks,
            model=config.model,
            max_chars=config.max_chars,
            max_tokens=config.max_tokens,
        )
        if not extraction.nodes:
            # 抽取成功但没有节点同样记账：这条消息已经付过费、处理完了。
            await _mark_blocks_seen(config, target, blocks, path)
            return ProcessedFile(filtered_messages=filtered)
    else:
        extraction = await extract_document(
            client,
            template=templates[profile],
            path=file_path,
            text=text,
            model=config.model,
            max_chars=config.max_chars,
            max_tokens=config.max_tokens,
        )
    kind = SourceKind.SESSION if is_session else SourceKind.WIKI
    report = await merge(
        config.store,
        extraction,
        project=target.project,
        source=SourceRef(type=kind, ref=file_path, device=target.device_id),
        lock_timeout=0,
        check_target=check_target,
    )
    if is_session:
        # 只记实际进入模型输入的块；被截断掉的留给下一次推送。
        await _mark_blocks_seen(config, target, blocks, path)
    return ProcessedFile(
        created=len(report.created),
        updated=len(report.updated),
        edges=report.edges_added,
        filtered_messages=filtered,
    )


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
    attempted = 0
    for path in pending:
        if attempted >= config.limit:
            break
        relative = str(path.relative_to(config.raw_root))
        try:
            outcome = await process_file(client, config, path, templates=templates)
        except AuthorizationDenied as exc:
            try:
                await _move_to(config, path, config.pending_root)
            except FileNotFoundError:
                pass  # 另一个 worker 已移走原始文件。
            except OSError:
                print("[worker] defer: quarantine_unavailable", file=sys.stderr)
                continue
            if failures.pop(relative, None) is not None:
                dirty = True
            current.quarantined += 1
            current.errors.append(exc.reason)
            print(f"[worker] quarantine: {exc.reason}", file=sys.stderr)
            continue
        except TargetUnavailable:
            # 读不到登记不是原始文件失败，保留原字节与已有失败次数。
            print("[worker] defer: target_registry_unavailable", flush=True)
            continue
        except MessageIndexUnavailable:
            # 索引不可用（表缺失/库不可用）不是文件失败：保留 raw，不计失败次数，不调模型。
            print("[worker] defer: message_index_unavailable", flush=True)
            continue
        except WriteDeferred as exc:
            print(f"[worker] defer: {exc.reason or 'write_unavailable'}", flush=True)
            if exc.reason in {"busy", "pending"}:
                break  # 全局阻塞，下一轮再试，不逐个重复预检。
            continue
        except (ExtractionFailed, LLMError, OSError, ValueError) as exc:
            attempted += 1
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
        try:
            await _mark_processed(config, path)
        except FileNotFoundError:
            # 另一个 worker 已经把它移走了（移动是原子的，谁先得手谁负责）。
            # 内容已经提炼并写进真源，这里不能让整轮因竞态崩掉。
            print(f"[worker] skip move {path.name}: 已被其他进程处理", flush=True)
        if failures.pop(relative, None) is not None:
            dirty = True
        attempted += 1
        current.processed += 1
        current.deduped += int(outcome.skipped_extraction)
        current.created += outcome.created
        current.updated += outcome.updated
        current.edges += outcome.edges
        print(
            f"[worker] ok {path.name}: +{outcome.created} new,"
            f" {outcome.updated} updated, {outcome.edges} edges",
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
        local_now = now().astimezone(config.window_tz)
        if window is not None and not in_window(local_now.time(), window):
            print(f"[worker] 窗口外（{config.window}），休眠 {config.interval:.0f}s", flush=True)
            await sleep(config.interval)
            continue
        report = await run_round(client, config)
        if report.processed or report.failed or report.quarantined or report.deduped:
            print(
                f"[worker] round: {report.processed} ok / {report.failed} fail "
                f"/ {report.quarantined} denied / {report.deduped} dedup "
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
    "MessageIndexUnavailable",
    "ProcessedFile",
    "RoundReport",
    "WorkerConfig",
    "in_window",
    "iter_pending",
    "parse_window",
    "parse_window_tz",
    "probe_endpoint",
    "process_file",
    "prune_processed_raw",
    "purge_pending_review",
    "run_forever",
    "run_round",
]
