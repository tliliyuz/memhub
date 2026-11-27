"""worker 守护进程：PG 队列 → 取正文 → 抽取 → merge 进知识真源（全异步 IO）。

单并发串行（池=1）：LLM 调用是瓶颈也是成本，串行让错峰窗口、内存预算、
失败退避都可预测。多实例并发安全：领取走 `SELECT ... FOR UPDATE SKIP LOCKED`，
领取即写 `processing/claimed_at`；崩溃留下的 `processing` 行租约过后自动回收。

窗口门控：`--window 21:00-02:00`（本地时间，跨午夜）内才处理；窗口外睡眠等待。
不传窗口则一直跑。

失败语义（ADR-0020）：
- 正文取不到 / 抽取失败 → `ingest_queue.attempts` 加一，未到上限退回 `queued`；
- 到上限或有永久的授权拒绝 → `pending_review`，不再重试；
- 目标登记、消息索引、正文存储等临时不可用 → 退回 `queued`，不消耗失败次数；
- LLM 端点启动自检失败 → exit 2（配置错误，别进循环空转把日志写满）；
- 运行期连续失败按指数退避，日志只打摘要，不打 traceback。
"""

from __future__ import annotations

import asyncio
import re
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone, tzinfo
from datetime import time as dt_time
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import anyio

from memhub.contract import SourceKind, SourceRef, explicit_project
from memhub.kb.manage import WriteDeferred
from memhub.kb.pgstore import PgKnowledgeStore
from memhub.kb.store import KnowledgeStore
from memhub.kb.target_access import TargetRegistry, TargetUnavailable
from memhub.queue.content import ContentUnavailable, RawContentStore
from memhub.queue.identity import (
    CONSOLE_DEVICE,
    collector_device_reserved,
)
from memhub.queue.tasks import QueueStore, QueueTask
from memhub.worker.extract import ExtractionFailed, extract_document, extract_session
from memhub.worker.llm import LLMClient, LLMError
from memhub.worker.memory import MemoryContext
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
    queue: QueueStore
    content: RawContentStore
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
    # 启动时固定的记忆快照；None 表示本次进程不注入，审计的 memory_snapshot 记 null。
    memory: MemoryContext | None = None

    def registry(self) -> TargetRegistry:
        return self.target_registry or TargetRegistry(self.store)


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


def _task_target(task: QueueTask) -> QueueTarget:
    """队列行的身份与目标校验；返回后再去取正文，非法行不产生外部读取。"""
    project = explicit_project(task.project)
    if project is None:
        raise AuthorizationDenied("project_required")
    if task.producer not in ("collector", "console"):
        raise AuthorizationDenied("producer_unrecognized")
    if (
        not task.device_id
        or not task.source_id
        or task.source_type not in PROFILE_BY_SOURCE
        or re.fullmatch(r"[0-9a-f]{64}", task.sha256) is None
    ):
        raise AuthorizationDenied("queue_identity_invalid")

    # 即使带管理台标记，也必须符合保留的生产者身份。
    exact_console = (
        task.device_id == CONSOLE_DEVICE
        and task.source_type == "docs"
        and task.source_id == project
    )
    if task.producer == "console":
        if not exact_console:
            raise AuthorizationDenied("console_identity_invalid")
        return QueueTarget(project, task.device_id, task.source_id, task.source_type, console=True)
    if collector_device_reserved(task.device_id):
        raise AuthorizationDenied("console_identity_invalid")
    return QueueTarget(project, task.device_id, task.source_id, task.source_type, console=False)


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
    state: StateStore, target: QueueTarget, blocks: list[SessionBlock], name: str
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
        f"[worker] dedupe {name}: 已见 {len(seen)} 条，剩余 {len(ids) - len(seen)} 条",
        flush=True,
    )
    if not kept:
        print(f"[worker] dedupe {name}: 全部消息已见过，跳过抽取", flush=True)
    return kept, len(seen)


async def _mark_blocks_seen(
    config: WorkerConfig, target: QueueTarget, blocks: list[SessionBlock], name: str
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
        print(f"[worker] mark-seen failed {name}: {type(exc).__name__}", file=sys.stderr)


async def _audit_session(config: WorkerConfig, project: str, result: str) -> None:
    """记录一次会话抽取用了哪版记忆；文件存储没有审计表，只在 PG 上执行。"""
    record = getattr(config.store, "record_write_audit", None)
    if record is None:
        return
    version = config.memory.audit_version(project) if config.memory is not None else None
    await record(
        actor="worker",
        project=project,
        node_id=None,
        action="extract_session",
        result=result,
        memory_snapshot=version,
    )


async def process_task(
    client: LLMClient,
    config: WorkerConfig,
    task: QueueTask,
    *,
    templates: dict[str, str] | None = None,
) -> ProcessedFile:
    """处理一条队列任务；失败抛异常，由调用方更新队列状态。"""
    target = _task_target(task)
    registry = config.registry()

    async def check_target() -> None:
        await _authorize(config, registry, target)

    # 空输入也要授权；等待模型时不持写真源的锁。
    async with config.store.write_scope(timeout=0):
        await check_target()

    file_path = task.path
    name = Path(file_path).name
    content = await config.content.get(task.project, task.sha256)
    if content is None:
        # 队列行在而正文不在：要么已被 TTL 清掉，要么写入不完整。重试不会自愈。
        raise AuthorizationDenied("content_missing")
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
            blocks, filtered = await _drop_seen_blocks(config.state, target, blocks, name)
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
            memory=config.memory,
            project=target.project,
        )
        await _audit_session(config, target.project, "ok" if extraction.nodes else "empty")
        if not extraction.nodes:
            # 抽取成功但没有节点同样记账：这条消息已经付过费、处理完了。
            await _mark_blocks_seen(config, target, blocks, name)
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
        await _mark_blocks_seen(config, target, blocks, name)
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
    """领取一批队列任务并处理；不抛单任务异常。

    每条任务的终态在队列里落定：`processed` / `pending_review` / 退回 `queued`。
    没有「本轮领了但没来得及处理」的残留：提前结束时把剩余任务 release，
    而不是让它们等到租约过期。
    """
    current = report or RoundReport()
    templates: dict[str, str] = {}
    tasks = await config.queue.claim(limit=config.limit)
    for index, task in enumerate(tasks):
        name = Path(task.path).name
        try:
            outcome = await process_task(client, config, task, templates=templates)
        except AuthorizationDenied as exc:
            await config.queue.review(task, exc.reason)
            current.quarantined += 1
            current.errors.append(exc.reason)
            print(f"[worker] quarantine {name}: {exc.reason}", file=sys.stderr)
            continue
        except TargetUnavailable:
            # 读不到登记不是任务失败：退回队列，不消耗失败次数。
            await config.queue.release(task)
            print("[worker] defer: target_registry_unavailable", flush=True)
            continue
        except MessageIndexUnavailable:
            # 索引不可用（表缺失/库不可用）不是任务失败：退回队列，不调模型。
            await config.queue.release(task)
            print("[worker] defer: message_index_unavailable", flush=True)
            continue
        except ContentUnavailable:
            # 正文存储临时不可用：退回队列，避免整轮空转并消耗失败次数。
            await config.queue.release(task)
            print("[worker] defer: content_store_unavailable", flush=True)
            continue
        except WriteDeferred as exc:
            await config.queue.release(task)
            print(f"[worker] defer: {exc.reason or 'write_unavailable'}", flush=True)
            if exc.reason in {"busy", "pending"}:
                # 全局阻塞，下一轮再试；剩余任务还回队列，不等租约过期。
                for rest in tasks[index + 1 :]:
                    await config.queue.release(rest)
                break
            continue
        except (ExtractionFailed, LLMError, OSError, ValueError) as exc:
            status = await config.queue.retry(
                task, f"{type(exc).__name__}: {exc}", max_attempts=config.max_attempts
            )
            current.failed += 1
            current.errors.append(f"{name}: {type(exc).__name__}: {exc}")
            if status == "pending_review":
                # 毒内容不能让队列永远红着：再试下去每轮都在同一处付费失败。
                current.quarantined += 1
                print(
                    f"[worker] quarantine {name}: 连续 {task.attempts} 次失败"
                    f" → pending_review ({type(exc).__name__}: {exc})",
                    file=sys.stderr,
                )
            else:
                print(
                    f"[worker] fail {name} ({task.attempts}/{config.max_attempts}):"
                    f" {type(exc).__name__}: {exc}",
                    file=sys.stderr,
                )
            continue
        await config.queue.complete(task)
        current.processed += 1
        current.deduped += int(outcome.skipped_extraction)
        current.created += outcome.created
        current.updated += outcome.updated
        current.edges += outcome.edges
        print(
            f"[worker] ok {name}: +{outcome.created} new,"
            f" {outcome.updated} updated, {outcome.edges} edges",
            flush=True,
        )
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
    "parse_window",
    "parse_window_tz",
    "probe_endpoint",
    "process_task",
    "run_forever",
    "run_round",
]
