"""运维命令入口：ingest / worker / mcp（全异步 IO）。"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import secrets
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from anyio import Path as AsyncPath

from memhub import __version__
from memhub.contract import SourceKind, SourceRef
from memhub.kb import archive, catalog, manage, target_access
from memhub.kb.memory import MemoryAggregateError
from memhub.kb.pgstore import PgKnowledgeStore
from memhub.kb.session import (
    WORKER_MAX_OVERFLOW,
    WORKER_POOL_SIZE,
    KbDsnMissing,
    create_rt_store,
    create_runtime_store,
)
from memhub.kb.store import KnowledgeStore
from memhub.mcp.server import serve as serve_mcp
from memhub.worker.extract import ExtractionFailed, extract_document, extract_session
from memhub.worker.llm import AnthropicClient, LLMError
from memhub.worker.memory import (
    MemoryContext,
    MemorySettings,
    aggregate_memories,
    load_memory_context,
)
from memhub.worker.merge import merge
from memhub.worker.prompts import load_profile
from memhub.worker.render import (
    render_jsonl,
    render_plaintext_blocks,
    render_session_blocks,
    truncate_blocks,
)

if TYPE_CHECKING:
    from memhub.kb.migrate_db import VerifyDiff

SKELETON_PAGES = {"schema.md", "log.md", "purpose.md"}
DEVICE_ID_RE = re.compile(
    r"(?i)^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)


def _prepare_event_loop() -> None:
    """psycopg 异步实现不支持 Windows 默认的 ProactorEventLoop，入口处先切 Selector。"""
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="memhub")
    parser.add_argument("--version", action="store_true", help="打印版本后退出")
    sub = parser.add_subparsers(dest="command")

    ingest = sub.add_parser("ingest", help="把本地目录/文件抽成 markdown 真源")
    ingest.add_argument("--path", required=True)
    ingest.add_argument("--profile", choices=["sessions", "wiki", "docs"], default="sessions")
    ingest.add_argument("--project", default=None)
    ingest.add_argument(
        "--create-project",
        action="store_true",
        help="目标知识库未登记时，在本次抽取前显式建库（默认只写已登记且活动的库）",
    )
    ingest.add_argument("--limit", type=int, default=0)
    ingest.add_argument("--max-chars", type=int, default=12000)
    ingest.add_argument("--max-input-chars", type=int, default=0, help="截断输入（0 表示不截断）")
    ingest.add_argument("--dry-run", action="store_true")

    recover = sub.add_parser("recover-kb-archive", help="核对并续做未完成的整库归档或恢复")
    recover.add_argument("--knowledge-dir", default=None)

    mcp = sub.add_parser("mcp", help="启动知识检索与写候选的 MCP stdio 服务")
    mcp_sub = mcp.add_subparsers(dest="mcp_command")
    token = mcp_sub.add_parser("token", help="本地生成 MCP HTTP 令牌与 grant 配置")
    token.add_argument("--name", default=None, help="凭据展示名，可选")
    token.add_argument("--projects", required=True, help="逗号分隔的知识库 id，至少一个")
    token.add_argument("--scope", choices=["read", "write"], default="read")
    token.add_argument(
        "--memory", action="store_true", help="允许读取已发布的跨项目长期记忆（默认关闭）"
    )
    token.add_argument("--days", type=int, default=90, help="有效期天数（默认 90）")
    token.add_argument("--json", action="store_true", help="输出单行 JSON，供脚本读取")

    purge = sub.add_parser(
        "purge-expired", help="删掉重放窗口（24h）外的批次记录并裁剪队列，供 systemd timer 调用"
    )
    purge.add_argument(
        "--keep-hours", type=int, default=25, help="保留最近 N 小时的批次（默认 25）"
    )
    purge.add_argument(
        "--processed-days",
        type=int,
        default=7,
        help="processed 队列行保留天数（默认 7；0 表示不裁剪）",
    )

    forget = sub.add_parser(
        "forget-messages", help="清理已见消息索引，让重推内容重新抽取（不动游标与 raw）"
    )
    forget.add_argument("--project", required=True, help="知识库 id")
    forget.add_argument("--source", dest="source_id", default=None, help="只清该源；缺省清整库")

    worker = sub.add_parser("worker", help="提炼守护进程：PG 队列 + CH 原文 → 知识真源（串行）")
    worker.add_argument("--once", action="store_true", help="只跑一轮后退出（timer 用）")
    worker.add_argument(
        "--window", default="21:00-02:00", help="处理窗口（本地时间，HH:MM-HH:MM；空串=全天）"
    )
    worker.add_argument("--interval", type=float, default=300.0, help="轮询间隔秒数")
    worker.add_argument("--limit", type=int, default=20, help="每轮最多处理文件数")
    worker.add_argument("--data-dir", default=None, help="dev 本地正文目录（缺省 MEMHUB_DATA_DIR）")
    worker.add_argument(
        "--dry-run", action="store_true", help="只校验配置并打印计划后退出（冒烟用）"
    )

    aggregate = sub.add_parser(
        "memory-aggregate", help="从跨项目 canonical 节点聚合长期记忆（周任务用）"
    )
    aggregate.add_argument("--since-days", type=int, default=7)
    aggregate.add_argument("--min-sessions", type=int, default=3)
    aggregate.add_argument("--min-projects", type=int, default=2)
    aggregate.add_argument("--max-nodes", type=int, default=100)
    aggregate.add_argument(
        "--dry-run", action="store_true", help="仍然调用模型，只打印计划，不写库"
    )
    aggregate.add_argument("--publish", action="store_true", help="写入成功后发布新快照")

    api = sub.add_parser("api", help="启动 ingest-api（绑定地址由 MEMHUB_HTTP_HOST 决定）")
    api.add_argument("--allow-non-loopback", action="store_true", help="允许绑定非回环地址")

    kb = sub.add_parser("kb", help="启动知识库管理 API（本地管理台后端 + 静态前端）")
    kb.add_argument("--port", type=int, default=None, help="默认 8701（MEMHUB_KB_HTTP_PORT）")
    kb.add_argument("--web-dist", default=None, help="前端构建产物目录（含 index.html）")

    provision = sub.add_parser(
        "provision-device", help="在库里登记设备并把 per-device token 打到标准输出"
    )
    provision.add_argument("--device-id", required=True, help="客户端生成的 UUID v4")
    provision.add_argument("--name", required=True)
    provision.add_argument("--platform", required=True)

    migrate_kb = sub.add_parser(
        "migrate-kb", help="一次性把 markdown 真源迁移到 PG（默认 dry-run，只读）"
    )
    migrate_kb.add_argument("--knowledge-dir", default=None)
    migrate_kb.add_argument("--dsn", default=None, help="缺省取 MEMHUB_KB_DB_URL（运行时角色）")
    migrate_kb.add_argument(
        "--schema",
        default=None,
        help="目标 schema（search_path）；缺省不设，生产用专用 schema kb",
    )
    migrate_kb.add_argument("--dry-run", action="store_true", help="只解析与统计，不写库不删文件")
    migrate_kb.add_argument("--verify-only", action="store_true", help="与库内数据逐项比对")
    migrate_kb.add_argument(
        "--delete-source",
        action="store_true",
        help="校验通过且已备份后删除 markdown 真源（默认不删）",
    )
    migrate_kb.add_argument(
        "--archives",
        choices=["skip", "migrate"],
        default="skip",
        help="整库归档快照的处理方式；dry-run 下两者都只统计",
    )

    backfill = sub.add_parser(
        "import-raw-store", help="一次性把旧 raw_store 积压导入 CH 正文与 PG 队列"
    )
    backfill.add_argument("--data-dir", default=None, help="旧 DATA_DIR（缺省 MEMHUB_DATA_DIR）")
    backfill.add_argument("--dry-run", action="store_true", help="只校验与统计，不写库不删文件")
    backfill.add_argument("--verify-only", action="store_true", help="逐条核验正文与队列行，不写库")

    check_store = sub.add_parser(
        "check-content-store", help="自检正文存储（ClickHouse TLS 或本地目录），容器冒烟用"
    )
    check_store.add_argument(
        "--data-dir", default=None, help="本地正文目录（缺省 MEMHUB_DATA_DIR）"
    )

    args = parser.parse_args(argv)
    if args.version:
        print(__version__)
        return 0
    if not args.command:
        parser.print_help()
        return 0
    _prepare_event_loop()
    try:
        return asyncio.run(_dispatch(args))
    except KeyboardInterrupt:
        return 130


async def _dispatch(args: argparse.Namespace) -> int:
    if args.command == "mcp" and getattr(args, "mcp_command", None) == "token":
        return _mcp_token(args)
    handlers = {
        "ingest": _ingest,
        "recover-kb-archive": _recover_kb_archive,
        "mcp": _mcp,
        "purge-expired": _purge_expired,
        "forget-messages": _forget_messages,
        "worker": _worker,
        "memory-aggregate": _memory_aggregate,
        "api": _api,
        "kb": _kb,
        "provision-device": _provision_device,
        "migrate-kb": _migrate_kb,
        "import-raw-store": _import_raw_store,
        "check-content-store": _check_content_store,
    }
    handler = handlers.get(args.command or "")
    if handler is None:
        return 0
    return await handler(args)


def _knowledge_dir(override: str | None) -> Path:
    return Path(override or os.environ.get("MEMHUB_KNOWLEDGE_DIR", "./knowledge"))


def _runtime_store(args: argparse.Namespace) -> PgKnowledgeStore:
    """kb-api / MCP 统一构造 PG 存储；缺 `MEMHUB_KB_DB_URL` 直接抛 `KbDsnMissing`。

    `store` 属性只给测试注入独立 schema 用，命令行不会传。
    """
    injected = getattr(args, "store", None)
    if isinstance(injected, PgKnowledgeStore):
        return injected
    return create_runtime_store()


def _rt_store(args: argparse.Namespace) -> PgKnowledgeStore:
    """ingest / worker / CLI 的运行态知识存储（ADR-0021，角色 `memhub_rt_app`）。

    缺 `MEMHUB_KB_RT_DB_URL` 直接抛 `KbDsnMissing`，不回退 kb-api 的角色。
    单并发使用，池按 1+1；ingest API 进程自己用 2+2（`create_rt_store` 默认值）。
    """
    injected = getattr(args, "store", None)
    if isinstance(injected, PgKnowledgeStore):
        return injected
    return create_rt_store(pool_size=WORKER_POOL_SIZE, max_overflow=WORKER_MAX_OVERFLOW)


def _llm_client() -> tuple[AnthropicClient, str]:
    base_url = os.environ.get("MEMHUB_LLM_BASE_URL") or os.environ.get("ANTHROPIC_BASE_URL", "")
    api_key = os.environ.get("MEMHUB_LLM_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN", "")
    model = os.environ.get("MEMHUB_LLM_MODEL_EXTRACT", "claude-sonnet-4-5")
    if not base_url or not api_key:
        raise SystemExit("缺少 MEMHUB_LLM_BASE_URL / MEMHUB_LLM_API_KEY（或开发态 ANTHROPIC_*）")
    return AnthropicClient(base_url, api_key), model


def _memory_client() -> tuple[AnthropicClient, str]:
    """聚合模型：`MEMHUB_LLM_MODEL_MEMORY` 优先，回退抽取模型；两者都缺不猜默认值。"""
    base_url = os.environ.get("MEMHUB_LLM_BASE_URL") or os.environ.get("ANTHROPIC_BASE_URL", "")
    api_key = os.environ.get("MEMHUB_LLM_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN", "")
    if not base_url or not api_key:
        raise ValueError("缺少 MEMHUB_LLM_BASE_URL / MEMHUB_LLM_API_KEY（或开发态 ANTHROPIC_*）")
    model = (
        os.environ.get("MEMHUB_LLM_MODEL_MEMORY", "").strip()
        or os.environ.get("MEMHUB_LLM_MODEL_EXTRACT", "").strip()
    )
    if not model:
        raise ValueError("缺少 MEMHUB_LLM_MODEL_MEMORY（且未设置 MEMHUB_LLM_MODEL_EXTRACT）")
    return AnthropicClient(base_url, api_key), model


def _memory_settings() -> MemorySettings:
    """注入侧配置；非法值抛 ValueError，由入口按配置错误退出 2。"""
    return MemorySettings.from_env(os.environ)


async def _iter_files(path: Path, profile: str) -> list[Path]:
    if await AsyncPath(path).is_file():
        return [path]
    pattern = "*.jsonl" if profile == "sessions" else "*.md"
    return sorted([Path(item) async for item in AsyncPath(path).rglob(pattern)])


async def _ingest(args: argparse.Namespace) -> int:
    source_path = Path(args.path)
    if not await AsyncPath(source_path).exists():
        print(f"路径不存在: {source_path}", file=sys.stderr)
        return 2
    files = await _iter_files(source_path, args.profile)
    if args.limit:
        files = files[: args.limit]
    files = [path for path in files if path.name not in SKELETON_PAGES]
    if not files:
        print("没有可处理的文件")
        return 0

    project = args.project or source_path.name
    store = _rt_store(args)
    if args.create_project and not args.dry_run:
        try:
            await catalog.create_kb(store, kb_id=project)
            print(f"已建库: {project}")
        except manage.InvalidError as exc:
            print(f"知识库 id 不合法: {exc}", file=sys.stderr)
            return 2
        except manage.ConflictError as exc:
            print(f"无法建库: {exc}", file=sys.stderr)
            return 2
    try:
        writable = await target_access.registered_active(store, project)
    except target_access.TargetUnavailable as exc:
        print(f"无法确认知识库登记状态: {exc}", file=sys.stderr)
        return 2
    if not writable:
        hint = "" if args.create_project else "；先在管理台建库，或加 --create-project"
        print(f"知识库 {project!r} 未登记或不在活动状态{hint}", file=sys.stderr)
        return 2
    memory: MemoryContext | None = None
    if args.profile == "sessions" and not args.dry_run:
        # 手工路径与 worker 同口径：启动时读一次已发布快照；非法配置按退出码 2 处理。
        try:
            memory = await load_memory_context(store, _memory_settings())
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
    template = await load_profile(args.profile)
    client, model = (None, "") if args.dry_run else _llm_client()
    if client is None:
        print(f"[dry-run] {len(files)} 个文件 → project={project}, profile={args.profile}")
        for path in files:
            print(f"  - {path}")
        return 0

    source_kind = SourceKind.SESSION if args.profile == "sessions" else SourceKind.WIKI
    device = os.environ.get("MEMHUB_DEVICE_NAME", "local")
    created = updated = failed = 0

    try:
        for path in files:
            raw = await AsyncPath(path).read_text(encoding="utf-8", errors="replace")
            try:
                if args.profile == "sessions":
                    blocks = (
                        render_session_blocks(raw)
                        if path.suffix.lower() == ".jsonl"
                        else render_plaintext_blocks(raw)
                    )
                    if args.max_input_chars:
                        blocks = truncate_blocks(blocks, args.max_input_chars)
                    if not blocks:
                        print(f"  skip {path.name}: 无可抽取文本")
                        continue
                    extraction = await extract_session(
                        client,
                        template=template,
                        path=path.name,
                        blocks=blocks,
                        model=model,
                        max_chars=args.max_chars,
                        memory=memory,
                        project=project,
                    )
                    await store.record_write_audit(
                        actor="worker",
                        project=project,
                        node_id=None,
                        action="extract_session",
                        result="ok" if extraction.nodes else "empty",
                        memory_snapshot=memory.audit_version(project) if memory else None,
                    )
                    if not extraction.nodes:
                        print(f"  skip {path.name}: 无可合并的会话证据")
                        continue
                else:
                    text = render_jsonl(raw) if path.suffix == ".jsonl" else raw
                    if args.max_input_chars:
                        text = text[: args.max_input_chars]
                    if not text.strip():
                        print(f"  skip {path.name}: 无可抽取文本")
                        continue
                    extraction = await extract_document(
                        client,
                        template=template,
                        path=path.name,
                        text=text,
                        model=model,
                        max_chars=args.max_chars,
                    )
            except (ExtractionFailed, LLMError) as exc:
                failed += 1
                print(f"  FAIL {path.name}: {exc}", file=sys.stderr)
                continue

            report = await merge(
                store,
                extraction,
                project=project,
                source=SourceRef(type=source_kind, ref=path.name, device=device),
            )
            created += len(report.created)
            updated += len(report.updated)
            print(
                f"  ok {path.name}: +{len(report.created)} new, {len(report.updated)} updated,"
                f" {report.edges_added} edges"
            )
    finally:
        await client.aclose()

    print(f"\n完成: {created} 新建 / {updated} 更新 / {failed} 失败；真源=PG（schema kb）")
    return 1 if failed else 0


async def _memory_aggregate(args: argparse.Namespace) -> int:
    """周期聚合入口（规格 §5.5）。退出码：0 成功（含无节点）；1 聚合失败；2 配置错误。"""
    try:
        store = _rt_store(args)
    except KbDsnMissing as exc:
        print(str(exc), file=sys.stderr)
        return 2
    try:
        template = await load_profile("memory")
        try:
            client, model = _memory_client()
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        try:
            report = await aggregate_memories(
                client,
                store,
                model=model,
                template=template,
                since_days=args.since_days,
                min_sessions=args.min_sessions,
                min_projects=args.min_projects,
                max_nodes=args.max_nodes,
                dry_run=args.dry_run,
                publish=args.publish,
            )
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        except (MemoryAggregateError, LLMError) as exc:
            print(f"聚合失败: {exc}", file=sys.stderr)
            return 1
        finally:
            await client.aclose()
    finally:
        await store.aclose()

    if report.nodes == 0:
        print("没有可聚合节点")
        return 0
    print(
        f"输入节点 {report.nodes}，产出记忆 {report.drafts}，"
        f"{'dry-run' if report.dry_run else '已写库'}"
    )
    for write in report.writes:
        print(
            f"  [{write.action}] {write.slug} "
            f"sessions={write.session_count} projects={write.project_count}"
        )
    for candidate in report.candidates:
        print(
            f"  [{candidate.status}] {candidate.slug} "
            f"sessions={candidate.session_count} projects={candidate.project_count} "
            f"reason={candidate.reason}"
        )
    if report.published is not None:
        print(f"已发布快照 v{report.published}")
    return 0


async def _recover_kb_archive(args: argparse.Namespace) -> int:
    store = KnowledgeStore(_knowledge_dir(args.knowledge_dir))
    try:
        recovered = await archive.recover(store)
    except (manage.ManageError, OSError) as exc:
        print(f"未能完成归档恢复：{exc}", file=sys.stderr)
        return 1
    print("已续做归档操作。" if recovered else "没有待续做的归档操作。")
    return 0


def _mcp_token(args: argparse.Namespace) -> int:
    """生成本地 MCP HTTP 令牌与可直接粘贴的 grant；令牌只写 stdout。"""
    from datetime import UTC, datetime, timedelta

    from pydantic import ValidationError

    from memhub.mcp.auth import Grant

    if not 1 <= args.days <= 3650:
        print("--days 必须在 1–3650 之间", file=sys.stderr)
        return 2
    projects = [item.strip() for item in args.projects.split(",") if item.strip()]
    token_value = secrets.token_urlsafe(32)
    expires_at = (datetime.now(UTC) + timedelta(days=args.days)).replace(microsecond=0)
    try:
        grant = Grant(
            sha256=hashlib.sha256(token_value.encode("ascii")).hexdigest(),
            scope="mcp:read" if args.scope == "read" else "mcp:write",
            expires_at=expires_at,
            projects=frozenset(projects),
            name=args.name,
            memory=args.memory,
        )
    except ValidationError as exc:
        print(f"参数无效，未生成令牌：{exc}", file=sys.stderr)
        return 2
    payload = {
        "sha256": grant.sha256,
        "scope": grant.scope,
        "expires_at": grant.expires_at.isoformat(),
        "projects": projects,
        "name": grant.name,
        "memory": grant.memory,
    }
    if args.json:
        print(json.dumps({"token": token_value, "grant": payload}, ensure_ascii=False))
        return 0
    print("令牌（只显示一次，请只写入本机环境变量）：")
    print(token_value)
    print()
    print("可粘贴到 MEMHUB_MCP_GRANTS 数组的 grant：")
    print(json.dumps(payload, ensure_ascii=False))
    print("不要把令牌写入仓库、文档或聊天记录。", file=sys.stderr)
    return 0


async def _mcp(args: argparse.Namespace) -> int:
    store = _runtime_store(args)
    try:
        return await serve_mcp(store)
    finally:
        await store.aclose()


async def _purge_expired(args: argparse.Namespace) -> int:
    """批次 TTL 与队列行裁剪：给 systemd timer 单独调用，不拉起 API 进程。

    队列行不含正文（正文在 ClickHouse，按 180 天 TTL 清理），因此只按天数裁剪
    `processed` 行；`pending_review` 保留给人复核，不自动删除。
    """
    from datetime import UTC, datetime, timedelta

    dsn = os.environ.get("MEMHUB_DB_URL", "")
    if not dsn:
        print("MEMHUB_DB_URL 未设置；批次与队列都在共享库，跳过清理", file=sys.stderr)
        return 0
    from memhub.ingest.postgres import PostgresStore
    from memhub.queue.tasks import PostgresQueue

    store = PostgresStore(dsn, min_size=1, max_size=1)
    try:
        await store.migrate()  # 幂等：库是空的也能自建表，timer 不依赖部署顺序
        if args.processed_days > 0:
            queue = PostgresQueue(store.sessions)
            trimmed = await queue.trim(
                before=datetime.now(UTC) - timedelta(days=args.processed_days)
            )
            print(f"已裁剪 {trimmed} 条已处理队列行")
        deleted = await store.purge_expired(keep=timedelta(hours=args.keep_hours))
    finally:
        await store.close()
    print(f"已清理 {deleted} 条过期批次记录")
    return 0


async def _forget_messages(args: argparse.Namespace) -> int:
    """清理已见消息索引；只动运行态记录，不动游标与 raw（规格 §6）。"""
    state = getattr(args, "state", None)
    if state is not None:
        deleted = await state.forget_messages(args.project, source_id=args.source_id)
    else:
        dsn = os.environ.get("MEMHUB_DB_URL", "")
        if not dsn:
            print("缺少 MEMHUB_DB_URL（已见消息索引只在共享库）", file=sys.stderr)
            return 2
        from memhub.ingest.postgres import PostgresStore

        store = PostgresStore(dsn, min_size=1, max_size=1)
        try:
            # 幂等建表：入口不依赖部署顺序。
            await store.migrate()
            deleted = await store.forget_messages(args.project, source_id=args.source_id)
        finally:
            await store.close()
    scope = f"{args.project}/{args.source_id}" if args.source_id else f"{args.project}（整库）"
    print(f"已清理 {deleted} 条已见消息记录：{scope}")
    return 0


async def _worker(args: argparse.Namespace) -> int:
    """提炼守护进程。退出码：0 无失败；1 有失败；2 配置/LLM 端点错误。

    队列在 PG（`ingest_queue`），正文在 ClickHouse（ADR-0020）。两者都必须是共享
    存储：独立进程用本机内存队列只会空转，因此缺 `MEMHUB_DB_URL` 直接退出。
    dev 未接 ClickHouse 时可用 `--data-dir` / `MEMHUB_DATA_DIR` 退回本地正文目录。
    """
    from memhub.ingest.app import build_store
    from memhub.queue.content import build_content_store
    from memhub.queue.flow import build_queue
    from memhub.worker.daemon import (
        WorkerConfig,
        parse_window_tz,
        probe_endpoint,
        run_forever,
        run_round,
    )

    dsn = os.environ.get("MEMHUB_DB_URL", "").strip()
    ch_url = os.environ.get("MEMHUB_CH_URL", "").strip()
    data_dir = args.data_dir or os.environ.get("MEMHUB_DATA_DIR", "")
    if not dsn:
        print("缺少 MEMHUB_DB_URL（提炼队列在共享库）", file=sys.stderr)
        return 2
    if not ch_url and not data_dir:
        print("缺少 MEMHUB_CH_URL（正文存储）或 MEMHUB_DATA_DIR（dev 本地正文）", file=sys.stderr)
        return 2
    try:
        memory_settings = _memory_settings()
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    store = _rt_store(args)
    state = build_store()
    queue_store = build_queue(state)
    content = build_content_store(Path(data_dir) if data_dir else None)
    try:
        if args.dry_run:
            # 容器冒烟用：只验证入口与配置，不探 LLM、不碰真源。
            backend = "clickhouse" if ch_url else str(Path(data_dir) / "content_store")
            print(
                f"[dry-run] 队列=PG 正文={backend} "
                f"window={args.window or 'all-day'} once={args.once}",
                flush=True,
            )
            return 0
        memory = await load_memory_context(store, memory_settings)
        base_url = os.environ.get("MEMHUB_LLM_BASE_URL") or os.environ.get("ANTHROPIC_BASE_URL", "")
        api_key = os.environ.get("MEMHUB_LLM_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN", "")
        if not base_url or not api_key:
            print("缺少 MEMHUB_LLM_BASE_URL / MEMHUB_LLM_API_KEY", file=sys.stderr)
            return 2
        try:
            await probe_endpoint(base_url)
        except LLMError as exc:
            # 端点不可达时直接退出：进循环只会空转把日志写满（上次事故的教训）。
            print(f"LLM 端点自检失败: {exc}", file=sys.stderr)
            return 2

        # 输出预算含 thinking：默认 8000 时模型会把预算全花在思考上、不给 text 块
        # （stop_reason=max_tokens, blocks=[thinking]，线上首跑已踩）。默认 32000，
        # 用 MEMHUB_LLM_MAX_TOKENS 覆盖；非法值按配置错误退出（2），不静默回退。
        raw_max_tokens = os.environ.get("MEMHUB_LLM_MAX_TOKENS", "").strip()
        try:
            max_tokens = int(raw_max_tokens) if raw_max_tokens else 32000
        except ValueError:
            print(f"MEMHUB_LLM_MAX_TOKENS 必须是整数：{raw_max_tokens!r}", file=sys.stderr)
            return 2
        if max_tokens <= 0:
            print(f"MEMHUB_LLM_MAX_TOKENS 必须为正数：{max_tokens}", file=sys.stderr)
            return 2

        # 窗口时区：容器默认 UTC，`--window 21:00-02:00` 会实际跑在 05:00-10:00 CST。
        # 生产用 MEMHUB_WINDOW_TZ=+08:00（显式偏移，不依赖镜像里的 tzdata）。
        try:
            window_tz = parse_window_tz(os.environ.get("MEMHUB_WINDOW_TZ", ""))
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2

        client, model = _llm_client()
        config = WorkerConfig(
            queue=queue_store,
            content=content,
            store=store,
            model=model,
            max_tokens=max_tokens,
            window=args.window or None,
            window_tz=window_tz,
            interval=args.interval,
            limit=args.limit,
            is_registered=state.is_registered,
            state=state,
            memory=memory,
        )
        try:
            if args.once:
                report = await run_round(client, config)
                return 1 if report.failed else 0
            return await run_forever(client, config)
        finally:
            await client.aclose()
    finally:
        try:
            await content.close()
            await state.close()
        finally:
            await store.aclose()


async def _import_raw_store(args: argparse.Namespace) -> int:
    """旧 raw_store 一次性导入（DEVELOPMENT §9.2）；不是采集入口，不推进游标。"""
    from memhub.ingest.app import DEFAULT_QUEUE_MAX_BYTES, _env_bytes, build_store
    from memhub.queue.backfill import run_backfill
    from memhub.queue.content import build_content_store
    from memhub.queue.flow import build_queue

    if args.dry_run and args.verify_only:
        print("--dry-run 与 --verify-only 不能同时使用", file=sys.stderr)
        return 2
    data_dir_text = args.data_dir or os.environ.get("MEMHUB_DATA_DIR", "")
    if not data_dir_text:
        print("缺少 --data-dir 或 MEMHUB_DATA_DIR（旧队列根目录）", file=sys.stderr)
        return 2
    data_dir = Path(data_dir_text)
    if not await AsyncPath(data_dir).is_dir():
        print(f"数据目录不存在：{data_dir}", file=sys.stderr)
        return 2
    if not os.environ.get("MEMHUB_DB_URL", "").strip():
        print("缺少 MEMHUB_DB_URL（提炼队列在共享库）", file=sys.stderr)
        return 2
    try:
        limit = _env_bytes("MEMHUB_QUEUE_MAX_BYTES", DEFAULT_QUEUE_MAX_BYTES)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    try:
        content = build_content_store(data_dir)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    state = build_store()
    if not (args.dry_run or args.verify_only):
        # 导入会直接写 ingest_queue；本命令不经过 `memhub api` 的启动建表，
        # 空库或落后版本必须自己补迁移（幂等）。盘点与核验保持只读。
        await state.migrate()
    queue_store = build_queue(state)
    try:
        report = await run_backfill(
            data_dir,
            queue=queue_store,
            content=content,
            limit=limit,
            dry_run=args.dry_run,
            verify_only=args.verify_only,
        )
    finally:
        try:
            await content.close()
        finally:
            await state.close()
    for failure in report.failures:
        print(f"失败：{failure}", file=sys.stderr)
    mode = "核验" if report.verify_only else ("盘点" if report.dry_run else "导入")
    counts = (
        f"核验通过 {report.verified}/{report.valid}"
        if report.verify_only
        else f"导入 {report.imported}，重复 {report.duplicates}"
    )
    print(
        f"{mode}：扫描 {report.scanned} 条（有效 {report.valid}）→ {counts}；"
        f"失败 {len(report.failures)}；processed_raw {report.processed_raw}、"
        f"pending_review {report.pending_review} 未导入"
    )
    return 1 if report.failures else 0


async def _check_content_store(args: argparse.Namespace) -> int:
    """容器内正文存储自检：验证 CH 的 TLS/httpx 链路或本地目录可读写。"""
    from memhub.queue.content import ContentUnavailable, build_content_store

    data_dir_text = args.data_dir or os.environ.get("MEMHUB_DATA_DIR", "")
    try:
        store = build_content_store(Path(data_dir_text) if data_dir_text else None)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    backend = "clickhouse" if os.environ.get("MEMHUB_CH_URL", "").strip() else data_dir_text
    try:
        # 只做一次按 (project, sha) 的不存在性查询；命中与否不影响连通性判定。
        await store.get("memhub-smoke", "0" * 64)
    except ContentUnavailable as exc:
        print(f"正文存储不可用（{backend}）：{exc}", file=sys.stderr)
        return 1
    finally:
        await store.close()
    print(f"正文存储可用：{backend}")
    return 0


LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def resolve_bind_host(allow_non_loopback: bool = False) -> str:
    """ingest-api 的绑定地址：`MEMHUB_HTTP_HOST` 优先，默认回环。

    host 网络下没有 `ports:` 兜底，绑错就是公网裸奔；因此非回环地址必须显式放行，
    生产环境默认拒绝。
    """
    host = os.environ.get("MEMHUB_HTTP_HOST", "127.0.0.1").strip() or "127.0.0.1"
    if host not in LOOPBACK_HOSTS and not allow_non_loopback:
        print(f"拒绝绑定非回环地址 {host}（需要 --allow-non-loopback 显式放行）", file=sys.stderr)
        raise SystemExit(2)  # 2 = 配置错误（与 worker 的退出码约定一致）
    return host


async def _provision_device(args: argparse.Namespace) -> int:
    """运维侧登记设备并取回 token。

    生产把 `/devices/register` 用 provision token 关掉了（开放注册等于任何人都能
    往知识库灌内容）；桌面端用户态注册还没做，这一版由运维在服务器上执行本命令。
    token 只打到标准输出：调用方自己写进 OS 凭据库，不得落 json / shell history。
    """
    from memhub.ingest.app import issue_device_token
    from memhub.ingest.postgres import PostgresStore

    if not DEVICE_ID_RE.match(args.device_id):
        print(f"device_id 必须是 UUID v4：{args.device_id!r}", file=sys.stderr)
        return 2
    dsn = os.environ.get("MEMHUB_DB_URL", "")
    secret = os.environ.get("MEMHUB_DEVICE_TOKEN_SECRET", "")
    if not dsn:
        print("缺少 MEMHUB_DB_URL（登记必须落到共享库）", file=sys.stderr)
        return 2
    if not secret:
        print("缺少 MEMHUB_DEVICE_TOKEN_SECRET", file=sys.stderr)
        return 2
    store = PostgresStore(dsn, min_size=1, max_size=1)
    try:
        await store.migrate()
        await store.register_device(args.device_id, name=args.name, platform=args.platform)
    finally:
        await store.close()
    print(issue_device_token(secret, args.device_id))
    return 0


async def _run_server(
    target: str, *, host: str, port: int, log_level: str, factory: bool = True
) -> None:
    """在已经运行的（Selector）事件循环里起 uvicorn，不另开事件循环。"""
    import uvicorn

    server = uvicorn.Server(
        uvicorn.Config(
            target,
            factory=factory,
            host=host,
            port=port,
            log_level=log_level,
        )
    )
    await server.serve()


async def _migrate_kb(args: argparse.Namespace) -> int:
    """一次性迁移入口（规格 §5）：默认只 dry-run，写库需 DSN，删真源需校验通过。

    前三步（解析、阻塞判定、差异清单）只读磁盘；`--verify-only` 与写库走
    `memhub.kb.migrate_db`。任何「没做」都显式失败，不报告成通过。
    """
    from memhub.kb import migrate

    root = Path(await AsyncPath(_knowledge_dir(args.knowledge_dir)).resolve())
    if not await AsyncPath(root).is_dir():
        print(f"知识库目录不存在: {root}", file=sys.stderr)
        return 2
    if args.delete_source and not args.verify_only:
        print("--delete-source 必须与 --verify-only 同时使用", file=sys.stderr)
        return 2

    plan = await migrate.parse_tree(root)
    diff = plan.diff.as_dict()
    print(
        f"解析结果: projects={len(plan.projects)} nodes={len(plan.nodes)} edges={len(plan.edges)}"
    )
    print(f"归档与回收站: archives={len(plan.archives)} trash_events={len(plan.trash_events)}")
    if diff["unregistered_projects"]:
        print(f"未登记库（将按目录导入）: {', '.join(diff['unregistered_projects'])}")
    if diff["missing_projects"]:
        print(f"已登记但目录不存在: {', '.join(diff['missing_projects'])}")
    if diff["dangling_edges"]:
        print(f"悬空边（原样迁入）: {len(diff['dangling_edges'])} 条")
    for label, key in (
        ("无效节点", "invalid_nodes"),
        ("无效边", "invalid_edges"),
        ("无效归档", "invalid_archives"),
        ("无表列的字段", "unsupported_fields"),
        ("无法识别的文件", "unknown_files"),
        ("重复节点 id", "duplicate_ids"),
    ):
        if diff[key]:
            print(f"{label}: {len(diff[key])} 处")

    if plan.blocking:
        reasons = []
        if plan.diff.pending_archive:
            reasons.append("存在未完成的归档事务（pending.json）")
        if plan.diff.registry_error:
            reasons.append(f"登记文件损坏：{plan.diff.registry_error}")
        if plan.diff.duplicate_ids:
            reasons.append("存在重复节点 id")
        if plan.diff.invalid_archives:
            reasons.append("归档数据损坏")
        print(f"迁移被阻断：{'；'.join(reasons)}", file=sys.stderr)
        return 1

    if args.dry_run:
        return 0

    dsn = (args.dsn or os.environ.get("MEMHUB_KB_DB_URL", "")).strip()
    if not dsn:
        print("缺少 MEMHUB_KB_DB_URL（运行时角色 DSN），无法写库", file=sys.stderr)
        return 2
    from memhub.kb import migrate_db
    from memhub.kb.session import create_engine_from_env

    # 迁移工具按调用方给的 DSN 走，不强制生产 schema `kb`：目标 schema 由
    # search_path 决定，测试/联调可以指向独立 schema。
    engine = create_engine_from_env(dsn=dsn, schema=args.schema)
    try:
        if args.verify_only:
            stored = await migrate_db.read_stored(engine)
            report = migrate_db.diff_plan(plan, stored, archives=args.archives)
            _print_verify_report(report)
            if not report.ok:
                return 1
            print("校验通过：库内内容与磁盘真源逐节点、逐边一致")
            if args.delete_source:
                print(
                    "--delete-source 的删除动作需负责人授权后在服务器执行；本次未删除任何文件",
                    file=sys.stderr,
                )
                return 3
            return 0
        await migrate_db.apply_plan(engine, plan, archives=args.archives)
        print(
            f"写入完成: projects={len(plan.projects)} nodes={len(plan.nodes)} "
            f"edges={len(plan.edges)} archives={len(plan.archives) if args.archives == 'migrate' else 0}"
        )
        return 0
    finally:
        await engine.dispose()


def _print_verify_report(report: VerifyDiff) -> None:
    """逐项打印差异；空清单不占终端行。"""
    payload = report.as_dict()
    labels = {
        "missing_projects": "库内缺少的知识库",
        "extra_projects": "库内多出的知识库",
        "changed_projects": "内容不一致的知识库",
        "missing_nodes": "库内缺少的节点",
        "extra_nodes": "库内多出的节点",
        "changed_nodes": "内容不一致的节点",
        "missing_edges": "库内缺少的边",
        "extra_edges": "库内多出的边",
        "archive_mismatches": "归档快照不一致",
    }
    for key, label in labels.items():
        if payload[key]:
            print(f"{label}: {len(payload[key])} 处", file=sys.stderr)
            for item in payload[key]:
                print(f"  {item}", file=sys.stderr)


async def _kb(args: argparse.Namespace) -> int:
    """本地知识库管理台：kb-api + 静态前端。

    只绑回环：这是单用户管理面，没有公网入口。前端构建产物缺失时纯 API 运行，
    开发期用 Vite 的 5173 端口直连。上传经 ingest 内部接口（ADR-0020），
    kb-api 不碰本机目录、运行态 DSN 或 ClickHouse 凭据。
    """
    web_dist = args.web_dist or os.environ.get("MEMHUB_KB_WEB_DIST", "")
    if web_dist:
        os.environ["MEMHUB_KB_WEB_DIST"] = str(await AsyncPath(web_dist).resolve())
    port = args.port or int(os.environ.get("MEMHUB_KB_HTTP_PORT", "8701"))
    print(f"memhub kb-api: http://127.0.0.1:{port}/  真源=PG（schema kb）", flush=True)
    ingest_url = os.environ.get("MEMHUB_INGEST_URL", "").strip()
    internal_token = os.environ.get("MEMHUB_INTERNAL_TOKEN", "").strip()
    if ingest_url and internal_token:
        print(f"上传→ingest 内部接口: {ingest_url}", flush=True)
    else:
        print("上传未启用（需要 MEMHUB_INGEST_URL 与 MEMHUB_INTERNAL_TOKEN）", flush=True)
    await _run_server(
        "memhub.kb.api:create_app",
        host="127.0.0.1",
        port=port,
        log_level=os.environ.get("MEMHUB_LOG_LEVEL", "INFO").lower(),
    )
    return 0


async def _api(args: argparse.Namespace) -> int:
    host = resolve_bind_host(args.allow_non_loopback)
    port = int(os.environ.get("MEMHUB_HTTP_PORT", "8700"))
    dsn = os.environ.get("MEMHUB_DB_URL", "")
    if dsn:
        # 启动时把表建出来：容器重启不该依赖有人先跑一次 purge 才有表。
        # 幂等，重复启动只会打印 "already up to date"。
        from memhub.ingest.postgres import PostgresStore

        store = PostgresStore(dsn, min_size=1, max_size=1)
        try:
            applied = await store.migrate()
        finally:
            await store.close()
        print(f"schema: {applied or 'already up to date'}", flush=True)
    print(f"memhub ingest-api: http://{host}:{port}/", flush=True)
    await _run_server(
        "memhub.ingest.app:create_app",
        host=host,
        port=port,
        log_level=os.environ.get("MEMHUB_LOG_LEVEL", "INFO").lower(),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
