"""运维命令入口：ingest / project / serve（全异步 IO）。"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from pathlib import Path

from anyio import Path as AsyncPath

from memhub import __version__
from memhub.contract import SourceKind, SourceRef
from memhub.kb import archive, catalog, manage, proc, target_access
from memhub.kb.projection import save_projection
from memhub.kb.store import KnowledgeStore
from memhub.mcp.server import serve as serve_mcp
from memhub.worker.extract import ExtractionFailed, extract_document, extract_session
from memhub.worker.llm import AnthropicClient, LLMError
from memhub.worker.merge import merge
from memhub.worker.prompts import load_profile
from memhub.worker.render import (
    render_jsonl,
    render_plaintext_blocks,
    render_session_blocks,
    truncate_blocks,
)

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
    ingest.add_argument("--knowledge-dir", default=None)
    ingest.add_argument("--max-chars", type=int, default=12000)
    ingest.add_argument("--max-input-chars", type=int, default=0, help="截断输入（0 表示不截断）")
    ingest.add_argument("--dry-run", action="store_true")

    project_cmd = sub.add_parser("project", help="重建 semantica 图谱投影")
    project_cmd.add_argument("--knowledge-dir", default=None)
    project_cmd.add_argument("--out", default="kb/kg.json")

    recover = sub.add_parser("recover-kb-archive", help="核对并续做未完成的整库归档或恢复")
    recover.add_argument("--knowledge-dir", default=None)

    serve = sub.add_parser("serve", help="启动 semantica explorer 看图")
    serve.add_argument("--graph", default="kb/kg.json")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--no-browser", action="store_true")

    mcp = sub.add_parser("mcp", help="启动知识检索与写候选的 MCP stdio 服务")
    mcp.add_argument("--knowledge-dir", default=None)

    purge = sub.add_parser(
        "purge-expired", help="删掉重放窗口（24h）外的批次记录，供 systemd timer 调用"
    )
    purge.add_argument(
        "--keep-hours", type=int, default=25, help="保留最近 N 小时的批次（默认 25）"
    )
    purge.add_argument(
        "--pending-review-days",
        type=int,
        default=30,
        help="pending_review/ 隔离文件保留天数（默认 30；0 表示不清理）",
    )
    purge.add_argument(
        "--processed-raw-days",
        type=int,
        default=7,
        help="processed_raw/ 副本保留天数（默认 7；0 表示不按时间清理）",
    )

    worker = sub.add_parser("worker", help="提炼守护进程：raw_store → 知识真源（串行）")
    worker.add_argument("--once", action="store_true", help="只跑一轮后退出（timer 用）")
    worker.add_argument(
        "--window", default="21:00-02:00", help="处理窗口（本地时间，HH:MM-HH:MM；空串=全天）"
    )
    worker.add_argument("--interval", type=float, default=300.0, help="轮询间隔秒数")
    worker.add_argument("--limit", type=int, default=20, help="每轮最多处理文件数")
    worker.add_argument("--data-dir", default=None)
    worker.add_argument("--knowledge-dir", default=None)
    worker.add_argument(
        "--dry-run", action="store_true", help="只校验目录/配置并打印计划后退出（冒烟用）"
    )

    api = sub.add_parser("api", help="启动 ingest-api（绑定地址由 MEMHUB_HTTP_HOST 决定）")
    api.add_argument("--allow-non-loopback", action="store_true", help="允许绑定非回环地址")

    kb = sub.add_parser("kb", help="启动知识库管理 API（本地管理台后端 + 静态前端）")
    kb.add_argument("--knowledge-dir", default=None)
    kb.add_argument("--graph-out", default=None, help="投影输出路径（默认 kb/kg.json）")
    kb.add_argument("--port", type=int, default=None, help="默认 8701（MEMHUB_KB_HTTP_PORT）")
    kb.add_argument("--web-dist", default=None, help="前端构建产物目录（含 index.html）")
    kb.add_argument(
        "--data-dir",
        default=None,
        help="提炼队列数据目录（缺省 MEMHUB_DATA_DIR）；配置后开放 /api/v1/kb/uploads",
    )
    kb.add_argument(
        "--spawn-graph", action="store_true", help="同时托管 explorer，并在投影重建后自动重启"
    )
    kb.add_argument("--graph-port", type=int, default=8703, help="explorer 端口（默认 8703）")

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
    handlers = {
        "ingest": _ingest,
        "project": _project,
        "recover-kb-archive": _recover_kb_archive,
        "serve": _serve,
        "mcp": _mcp,
        "purge-expired": _purge_expired,
        "worker": _worker,
        "api": _api,
        "kb": _kb,
        "provision-device": _provision_device,
        "migrate-kb": _migrate_kb,
    }
    handler = handlers.get(args.command or "")
    if handler is None:
        return 0
    return await handler(args)


def _knowledge_dir(override: str | None) -> Path:
    return Path(override or os.environ.get("MEMHUB_KNOWLEDGE_DIR", "./knowledge"))


def _llm_client() -> tuple[AnthropicClient, str]:
    base_url = os.environ.get("MEMHUB_LLM_BASE_URL") or os.environ.get("ANTHROPIC_BASE_URL", "")
    api_key = os.environ.get("MEMHUB_LLM_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN", "")
    model = os.environ.get("MEMHUB_LLM_MODEL_EXTRACT", "claude-sonnet-4-5")
    if not base_url or not api_key:
        raise SystemExit("缺少 MEMHUB_LLM_BASE_URL / MEMHUB_LLM_API_KEY（或开发态 ANTHROPIC_*）")
    return AnthropicClient(base_url, api_key), model


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
    store = KnowledgeStore(_knowledge_dir(args.knowledge_dir))
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
    template = await load_profile(args.profile)
    client, model = (None, "") if args.dry_run else _llm_client()
    if client is None:
        print(f"[dry-run] {len(files)} 个文件 → project={project}, profile={args.profile}")
        for path in files:
            print(f"  - {path}")
        return 0

    source_kind = SourceKind.SESSION if args.profile == "sessions" else SourceKind.WIKI
    device = os.environ.get("MEMHUB_DEVICE_NAME", "local")
    created = updated = skipped = failed = 0

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
            skipped += len(report.skipped_canonical)
            print(
                f"  ok {path.name}: +{len(report.created)} new, {len(report.updated)} updated,"
                f" {report.edges_added} edges"
            )
    finally:
        await client.aclose()

    print(
        f"\n完成: {created} 新建 / {updated} 更新 / {skipped} 跳过(canonical) / {failed} 失败；"
        f"真源目录 {store.root}"
    )
    return 1 if failed else 0


async def _project(args: argparse.Namespace) -> int:
    store = KnowledgeStore(_knowledge_dir(args.knowledge_dir))
    out = Path(args.out)
    report = await save_projection(store, out)
    print(f"投影已写入 {out}: {report.nodes} 节点 / {report.edges} 边")
    if report.unresolved:
        print(f"未解析关系 {len(report.unresolved)} 条（目标不在真源中）:")
        for item in report.unresolved[:20]:
            print(f"  - {item}")
    return 0


async def _recover_kb_archive(args: argparse.Namespace) -> int:
    store = KnowledgeStore(_knowledge_dir(args.knowledge_dir))
    try:
        recovered = await archive.recover(store)
    except (manage.ManageError, OSError) as exc:
        print(f"未能完成归档恢复：{exc}", file=sys.stderr)
        return 1
    print("已续做归档操作；请重建投影。" if recovered else "没有待续做的归档操作。")
    return 0


def _serve_env() -> dict[str, str]:
    """explorer 只绑回环地址；补齐它启动所需的运行环境。

    - UTF-8：semantica 启动日志含 `✓`，Windows 默认 GBK 会直接 UnicodeEncodeError。
    - 匿名只读：explorer API 要求 token 或显式匿名，否则返回
      "Server is not configured for authentication"。服务不对外暴露，故默认允许匿名；
      调用方已显式设置的环境变量优先。
    """
    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("SEMANTICA_ALLOW_ANONYMOUS", "true")
    return env


async def _serve(args: argparse.Namespace) -> int:
    graph = Path(await AsyncPath(args.graph).resolve())
    if not await AsyncPath(graph).is_file():
        print(f"图谱不存在: {graph}（先运行 memhub project）", file=sys.stderr)
        return 2
    command = [
        sys.executable,
        "-m",
        "semantica.explorer",
        "--graph",
        str(graph),
        "--port",
        str(args.port),
        "--host",
        "127.0.0.1",
    ]
    if args.no_browser:
        command.append("--no-browser")
    print(f"memhub explorer: http://127.0.0.1:{args.port}/  graph={graph}", flush=True)
    # 前台长驻，子进程直接继承本进程的 stdio。
    result = await proc.run_command(command, env=_serve_env(), capture=False)
    return result.returncode


async def _mcp(args: argparse.Namespace) -> int:
    store = KnowledgeStore(_knowledge_dir(args.knowledge_dir))
    if not await AsyncPath(store.root).is_dir():
        print(f"知识库目录不存在: {store.root}", file=sys.stderr)
        return 2
    return await serve_mcp(store)


async def _purge_expired(args: argparse.Namespace) -> int:
    """批次 TTL 与隔离区清理：给 systemd timer 单独调用，不拉起 API 进程。"""
    from datetime import timedelta

    from memhub.worker.daemon import PROCESSED_MAX_BYTES, prune_processed_raw, purge_pending_review

    data_dir = os.environ.get("MEMHUB_DATA_DIR", "")
    if data_dir and args.pending_review_days > 0:
        # 隔离区不属于批次记录，DSN 缺省时也要清理：毒文件不清理会无限占盘。
        files, size = await purge_pending_review(
            Path(data_dir), older_than=timedelta(days=args.pending_review_days)
        )
        print(f"已清理隔离区 {files} 个文件（{size} 字节）")

    if data_dir and args.processed_raw_days > 0:
        # processed_raw 是 raw_store 的完整副本，不受配额约束；不裁剪同样会写满磁盘。
        raw = os.environ.get("MEMHUB_PROCESSED_MAX_BYTES", "").strip()
        try:
            max_bytes = int(raw) if raw else PROCESSED_MAX_BYTES
        except ValueError:
            print(f"MEMHUB_PROCESSED_MAX_BYTES 必须是整数：{raw!r}", file=sys.stderr)
            return 2
        if max_bytes <= 0:
            print(f"MEMHUB_PROCESSED_MAX_BYTES 必须大于 0：{max_bytes}", file=sys.stderr)
            return 2
        files, size = await prune_processed_raw(
            Path(data_dir),
            max_bytes=max_bytes,
            older_than=timedelta(days=args.processed_raw_days),
        )
        print(f"已裁剪 processed_raw {files} 个文件（{size} 字节）")

    dsn = os.environ.get("MEMHUB_DB_URL", "")
    if not dsn:
        print("MEMHUB_DB_URL 未设置；内存实现无需清理批次", file=sys.stderr)
        return 0
    from memhub.ingest.postgres import PostgresStore

    store = PostgresStore(dsn, min_size=1, max_size=1)
    try:
        await store.migrate()  # 幂等：库是空的也能自建表，timer 不依赖部署顺序
        deleted = await store.purge_expired(keep=timedelta(hours=args.keep_hours))
    finally:
        await store.close()
    print(f"已清理 {deleted} 条过期批次记录")
    return 0


async def _worker(args: argparse.Namespace) -> int:
    """提炼守护进程。退出码：0 无失败；1 有失败；2 配置/LLM 端点错误。"""
    from memhub.worker.daemon import (
        WorkerConfig,
        parse_window_tz,
        probe_endpoint,
        run_forever,
        run_round,
    )

    data_dir = args.data_dir or os.environ.get("MEMHUB_DATA_DIR", "")
    knowledge_dir = args.knowledge_dir or os.environ.get("MEMHUB_KNOWLEDGE_DIR", "")
    if not data_dir or not knowledge_dir:
        print("缺少 MEMHUB_DATA_DIR / MEMHUB_KNOWLEDGE_DIR", file=sys.stderr)
        return 2
    if args.dry_run:
        # 容器冒烟用：只验证入口、环境与目录布局，不探 LLM、不碰文件。
        raw_root = Path(data_dir) / "raw_store"
        exists = await AsyncPath(raw_root).is_dir()
        print(
            f"[dry-run] data={data_dir} knowledge={knowledge_dir} "
            f"raw_root={'exists' if exists else 'missing'} "
            f"window={args.window or 'all-day'} once={args.once}",
            flush=True,
        )
        return 0
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

    # 数据库迁移由 ingest 负责；worker 只查设备登记。
    # 独立进程的内存状态无法感知 ingest 登记的设备。
    state = None
    if os.environ.get("MEMHUB_DB_URL"):
        from memhub.ingest.app import build_store

        state = build_store()
    client, model = _llm_client()
    config = WorkerConfig(
        data_dir=Path(data_dir),
        knowledge_dir=Path(knowledge_dir),
        model=model,
        max_tokens=max_tokens,
        window=args.window or None,
        window_tz=window_tz,
        interval=args.interval,
        limit=args.limit,
        is_registered=state.is_registered if state is not None else None,
    )
    try:
        if args.once:
            report = await run_round(client, config)
            return 1 if report.failed else 0
        return await run_forever(client, config)
    finally:
        try:
            await client.aclose()
        finally:
            close = getattr(state, "close", None)
            if close is not None:
                await close()


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

    写库半段依赖 `kb_*` ORM（另一条 lane），这里只把关只读统计、阻塞判定与删除
    前置条件；未具备写库条件时显式失败，绝不把「没做」报告成「通过」。
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
    print(
        "写库半段尚未接入：本次只完成只读解析与校验。"
        "数据库写入与 --verify-only 的逐节点比对在 ORM 落地后启用。",
        file=sys.stderr,
    )
    return 2


async def _kb(args: argparse.Namespace) -> int:
    """本地知识库管理台：kb-api + （可选）explorer 子进程。

    只绑回环：这是单用户管理面，没有公网入口。前端构建产物缺失时纯 API 运行，
    开发期用 Vite 的 5173 端口直连。
    """
    knowledge = Path(await AsyncPath(_knowledge_dir(args.knowledge_dir)).resolve())
    if not await AsyncPath(knowledge).is_dir():
        print(f"知识库目录不存在: {knowledge}", file=sys.stderr)
        return 2
    graph_out = Path(
        await AsyncPath(args.graph_out or os.environ.get("MEMHUB_KB_GRAPH", "kb/kg.json")).resolve()
    )
    web_dist = args.web_dist or os.environ.get("MEMHUB_KB_WEB_DIST", "")
    data_dir_raw = args.data_dir or os.environ.get("MEMHUB_DATA_DIR", "")
    if data_dir_raw:
        # 上传要落 raw_store：解析成绝对路径再交给 create_app，避免受启动目录影响。
        os.environ["MEMHUB_DATA_DIR"] = str(await AsyncPath(data_dir_raw).resolve())
    os.environ["MEMHUB_KNOWLEDGE_DIR"] = str(knowledge)
    os.environ["MEMHUB_KB_GRAPH"] = str(graph_out)
    if web_dist:
        os.environ["MEMHUB_KB_WEB_DIST"] = str(await AsyncPath(web_dist).resolve())
    if args.spawn_graph:
        os.environ["MEMHUB_KB_GRAPH_PORT"] = str(args.graph_port)
    port = args.port or int(os.environ.get("MEMHUB_KB_HTTP_PORT", "8701"))
    print(f"memhub kb-api: http://127.0.0.1:{port}/  真源={knowledge}", flush=True)
    if await AsyncPath(graph_out).is_file():
        print(f"投影: {graph_out}", flush=True)
    if args.spawn_graph:
        print(f"explorer 由 kb-api 托管: http://127.0.0.1:{args.graph_port}/", flush=True)
    if data_dir_raw:
        print(f"上传→提炼队列: {os.environ['MEMHUB_DATA_DIR']}", flush=True)
    else:
        print("上传未启用（未配置 MEMHUB_DATA_DIR / --data-dir）", flush=True)
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
