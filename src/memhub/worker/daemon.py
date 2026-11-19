"""worker 守护进程：raw_store → 抽取 → merge 进知识真源。

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

import json
import shutil
import socket
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from datetime import time as dt_time
from pathlib import Path
from urllib.parse import urlparse

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

    @property
    def raw_root(self) -> Path:
        return self.data_dir / "raw_store"

    @property
    def processed_root(self) -> Path:
        return self.data_dir / "processed_raw"


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


def iter_pending(raw_root: Path, processed_root: Path) -> list[Path]:
    """未处理的 raw 文件，按修改时间升序（先来先提炼）。"""
    if not raw_root.is_dir():
        return []
    pending: list[Path] = []
    for path in raw_root.rglob("*.json"):
        relative = path.relative_to(raw_root)
        if (processed_root / relative).exists():
            continue
        pending.append(path)
    pending.sort(key=lambda item: item.stat().st_mtime)
    return pending


def probe_endpoint(base_url: str, *, timeout: float = 5.0) -> None:
    """启动自检：只做 DNS/TCP 可达性，不发模型请求（不发钱）。"""
    parsed = urlparse(base_url)
    host = parsed.hostname
    if not host:
        raise LLMError(f"LLM base URL 无法解析主机: {base_url!r}")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return
    except OSError as exc:
        raise LLMError(f"LLM 端点不可达 {host}:{port}: {exc}") from exc


def _mark_processed(config: WorkerConfig, path: Path) -> None:
    relative = path.relative_to(config.raw_root)
    target = config.processed_root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(path), str(target))


def _document_text(payload: dict[str, object]) -> str:
    content = str(payload.get("content", ""))
    path = str(payload.get("path", ""))
    if path.endswith(".jsonl"):
        rendered = render_jsonl(content)
        # 增量可能从事件中间切出来，整段都不是合法 JSON 行时退回原文：
        # 静默丢掉一段真实增量比抽到噪音更糟。
        return rendered or content
    return content


def process_file(
    client: LLMClient,
    config: WorkerConfig,
    path: Path,
    *,
    templates: dict[str, str] | None = None,
) -> tuple[int, int, int]:
    """处理一个 raw 文件；返回 (created, updated, edges)。失败抛异常，由调用方隔离。"""
    payload = json.loads(path.read_text(encoding="utf-8"))
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
        templates[profile] = load_profile(profile)

    extraction = extract_document(
        client,
        template=templates[profile],
        path=file_path,
        text=text,
        model=config.model,
        max_chars=config.max_chars,
    )
    store = KnowledgeStore(config.knowledge_dir)
    kind = SourceKind.SESSION if source_type == "sessions" else SourceKind.WIKI
    report = merge(
        store,
        extraction,
        project=source_id,
        source=SourceRef(type=kind, ref=file_path, device=device_id),
    )
    return len(report.created), len(report.updated), report.edges_added


def run_round(
    client: LLMClient,
    config: WorkerConfig,
    *,
    report: RoundReport | None = None,
) -> RoundReport:
    """处理一批待提炼文件；不抛单文件异常。"""
    current = report or RoundReport()
    templates: dict[str, str] = {}
    for path in iter_pending(config.raw_root, config.processed_root)[: config.limit]:
        try:
            created, updated, edges = process_file(client, config, path, templates=templates)
        except (ExtractionFailed, LLMError, OSError, ValueError) as exc:
            current.failed += 1
            current.errors.append(f"{path.name}: {type(exc).__name__}: {exc}")
            print(f"[worker] fail {path.name}: {type(exc).__name__}: {exc}", file=sys.stderr)
            continue
        _mark_processed(config, path)
        current.processed += 1
        current.created += created
        current.updated += updated
        current.edges += edges
        print(
            f"[worker] ok {path.name}: +{created} new, {updated} updated, {edges} edges",
            flush=True,
        )
    return current


def run_forever(
    client: LLMClient,
    config: WorkerConfig,
    *,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    sleep: Callable[[float], None] = time.sleep,
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
            sleep(config.interval)
            continue
        report = run_round(client, config)
        if report.processed or report.failed:
            print(
                f"[worker] round: {report.processed} ok / {report.failed} fail "
                f"/ +{report.created} new / {report.updated} updated",
                flush=True,
            )
        if report.failed:
            failure_streak += 1
            sleep(min(1800.0, config.interval * 2 ** min(failure_streak, 4)))
        else:
            failure_streak = 0
            if not report.processed:
                sleep(config.interval)
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
    "run_forever",
    "run_round",
]
