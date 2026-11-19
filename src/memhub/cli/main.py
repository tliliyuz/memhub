"""运维命令入口：ingest / project / serve。"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

from memhub import __version__
from memhub.contract import SourceKind, SourceRef
from memhub.kb.projection import save_projection
from memhub.kb.store import KnowledgeStore
from memhub.mcp.server import serve as serve_mcp
from memhub.worker.extract import ExtractionFailed, extract_document
from memhub.worker.llm import AnthropicClient, LLMError
from memhub.worker.merge import merge
from memhub.worker.prompts import load_profile
from memhub.worker.render import render_jsonl

SKELETON_PAGES = {"schema.md", "log.md", "purpose.md"}
DEVICE_ID_RE = re.compile(
    r"(?i)^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="memhub")
    parser.add_argument("--version", action="store_true", help="打印版本后退出")
    sub = parser.add_subparsers(dest="command")

    ingest = sub.add_parser("ingest", help="把本地目录/文件抽成 markdown 真源")
    ingest.add_argument("--path", required=True)
    ingest.add_argument("--profile", choices=["sessions", "wiki", "docs"], default="sessions")
    ingest.add_argument("--project", default=None)
    ingest.add_argument("--limit", type=int, default=0)
    ingest.add_argument("--knowledge-dir", default=None)
    ingest.add_argument("--max-chars", type=int, default=12000)
    ingest.add_argument("--max-input-chars", type=int, default=0, help="截断输入（0 表示不截断）")
    ingest.add_argument("--dry-run", action="store_true")

    project_cmd = sub.add_parser("project", help="重建 semantica 图谱投影")
    project_cmd.add_argument("--knowledge-dir", default=None)
    project_cmd.add_argument("--out", default="kb/kg.json")

    serve = sub.add_parser("serve", help="启动 semantica explorer 看图")
    serve.add_argument("--graph", default="kb/kg.json")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--no-browser", action="store_true")

    mcp = sub.add_parser("mcp", help="以 MCP stdio 服务暴露检索组给 agent")
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
        "--spawn-graph", action="store_true", help="同时托管 explorer，并在投影重建后自动重启"
    )
    kb.add_argument("--graph-port", type=int, default=8703, help="explorer 端口（默认 8703）")

    provision = sub.add_parser(
        "provision-device", help="在库里登记设备并把 per-device token 打到标准输出"
    )
    provision.add_argument("--device-id", required=True, help="客户端生成的 UUID v4")
    provision.add_argument("--name", required=True)
    provision.add_argument("--platform", required=True)

    args = parser.parse_args(argv)
    if args.version:
        print(__version__)
        return 0
    if args.command == "ingest":
        return _ingest(args)
    if args.command == "project":
        return _project(args)
    if args.command == "serve":
        return _serve(args)
    if args.command == "mcp":
        return _mcp(args)
    if args.command == "purge-expired":
        return _purge_expired(args)
    if args.command == "worker":
        return _worker(args)
    if args.command == "api":
        return _api(args)
    if args.command == "kb":
        return _kb(args)
    if args.command == "provision-device":
        return _provision_device(args)
    parser.print_help()
    return 0


def _knowledge_dir(override: str | None) -> Path:
    return Path(override or os.environ.get("MEMHUB_KNOWLEDGE_DIR", "./knowledge"))


def _llm_client() -> tuple[AnthropicClient, str]:
    base_url = os.environ.get("MEMHUB_LLM_BASE_URL") or os.environ.get("ANTHROPIC_BASE_URL", "")
    api_key = os.environ.get("MEMHUB_LLM_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN", "")
    model = os.environ.get("MEMHUB_LLM_MODEL_EXTRACT", "claude-sonnet-4-5")
    if not base_url or not api_key:
        raise SystemExit("缺少 MEMHUB_LLM_BASE_URL / MEMHUB_LLM_API_KEY（或开发态 ANTHROPIC_*）")
    return AnthropicClient(base_url, api_key), model


def _iter_files(path: Path, profile: str) -> list[Path]:
    if path.is_file():
        return [path]
    pattern = "*.jsonl" if profile == "sessions" else "*.md"
    return sorted(path.rglob(pattern))


def _ingest(args: argparse.Namespace) -> int:
    source_path = Path(args.path)
    if not source_path.exists():
        print(f"路径不存在: {source_path}", file=sys.stderr)
        return 2
    files = _iter_files(source_path, args.profile)
    if args.limit:
        files = files[: args.limit]
    files = [path for path in files if path.name not in SKELETON_PAGES]
    if not files:
        print("没有可处理的文件")
        return 0

    project = args.project or source_path.name
    store = KnowledgeStore(_knowledge_dir(args.knowledge_dir))
    template = load_profile(args.profile)
    client, model = (None, "") if args.dry_run else _llm_client()
    if client is None:
        print(f"[dry-run] {len(files)} 个文件 → project={project}, profile={args.profile}")
        for path in files:
            print(f"  - {path}")
        return 0

    source_kind = SourceKind.SESSION if args.profile == "sessions" else SourceKind.WIKI
    device = os.environ.get("MEMHUB_DEVICE_NAME", "local")
    created = updated = skipped = failed = 0

    for path in files:
        raw = path.read_text(encoding="utf-8", errors="replace")
        text = render_jsonl(raw) if path.suffix == ".jsonl" else raw
        if args.max_input_chars:
            text = text[: args.max_input_chars]
        if not text.strip():
            print(f"  skip {path.name}: 无可抽取文本")
            continue
        try:
            extraction = extract_document(
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

        report = merge(
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

    print(
        f"\n完成: {created} 新建 / {updated} 更新 / {skipped} 跳过(canonical) / {failed} 失败；"
        f"真源目录 {store.root}"
    )
    return 1 if failed else 0


def _project(args: argparse.Namespace) -> int:
    store = KnowledgeStore(_knowledge_dir(args.knowledge_dir))
    out = Path(args.out)
    report = save_projection(store, out)
    print(f"投影已写入 {out}: {report.nodes} 节点 / {report.edges} 边")
    if report.unresolved:
        print(f"未解析关系 {len(report.unresolved)} 条（目标不在真源中）:")
        for item in report.unresolved[:20]:
            print(f"  - {item}")
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


def _serve(args: argparse.Namespace) -> int:
    graph = Path(args.graph).resolve()
    if not graph.is_file():
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
    return subprocess.call(command, env=_serve_env())


def _mcp(args: argparse.Namespace) -> int:
    store = KnowledgeStore(_knowledge_dir(args.knowledge_dir))
    if not store.root.is_dir():
        print(f"知识库目录不存在: {store.root}", file=sys.stderr)
        return 2
    return serve_mcp(store)


def _purge_expired(args: argparse.Namespace) -> int:
    """批次 TTL 与隔离区清理：给 systemd timer 单独调用，不拉起 API 进程。"""
    from datetime import timedelta

    from memhub.worker.daemon import PROCESSED_MAX_BYTES, prune_processed_raw, purge_pending_review

    data_dir = os.environ.get("MEMHUB_DATA_DIR", "")
    if data_dir and args.pending_review_days > 0:
        # 隔离区不属于批次记录，DSN 缺省时也要清理：毒文件不清理会无限占盘。
        files, size = purge_pending_review(
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
        files, size = prune_processed_raw(
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
        store.migrate()  # 幂等：库是空的也能自建表，timer 不依赖部署顺序
        deleted = store.purge_expired(keep=timedelta(hours=args.keep_hours))
    finally:
        store.close()
    print(f"已清理 {deleted} 条过期批次记录")
    return 0


def _worker(args: argparse.Namespace) -> int:
    """提炼守护进程。退出码：0 无失败；1 有失败；2 配置/LLM 端点错误。"""
    from memhub.worker.daemon import WorkerConfig, probe_endpoint, run_forever, run_round

    data_dir = args.data_dir or os.environ.get("MEMHUB_DATA_DIR", "")
    knowledge_dir = args.knowledge_dir or os.environ.get("MEMHUB_KNOWLEDGE_DIR", "")
    if not data_dir or not knowledge_dir:
        print("缺少 MEMHUB_DATA_DIR / MEMHUB_KNOWLEDGE_DIR", file=sys.stderr)
        return 2
    if args.dry_run:
        # 容器冒烟用：只验证入口、环境与目录布局，不探 LLM、不碰文件。
        raw_root = Path(data_dir) / "raw_store"
        print(
            f"[dry-run] data={data_dir} knowledge={knowledge_dir} "
            f"raw_root={'exists' if raw_root.is_dir() else 'missing'} "
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
        probe_endpoint(base_url)
    except LLMError as exc:
        # 端点不可达时直接退出：进循环只会空转把日志写满（上次事故的教训）。
        print(f"LLM 端点自检失败: {exc}", file=sys.stderr)
        return 2

    client, model = _llm_client()
    config = WorkerConfig(
        data_dir=Path(data_dir),
        knowledge_dir=Path(knowledge_dir),
        model=model,
        window=args.window or None,
        interval=args.interval,
        limit=args.limit,
    )
    if args.once:
        report = run_round(client, config)
        return 1 if report.failed else 0
    return run_forever(client, config)


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


def _provision_device(args: argparse.Namespace) -> int:
    """运维侧登记设备并取回 token。

    生产把 `/devices/register` 用 provision token 关掉了（开放注册等于任何人都能
    往知识库灌内容）；桌面端用户态注册还没做，这一版由运维在服务器上执行本命令。
    token 只打到标准输出：调用方自己写进 OS 凭据库，不得落 json / shell history。
    """
    from memhub.ingest.app import issue_device_token

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
    from memhub.ingest.postgres import PostgresStore

    store = PostgresStore(dsn, min_size=1, max_size=1)
    try:
        store.migrate()
        store.register_device(args.device_id, name=args.name, platform=args.platform)
    finally:
        store.close()
    print(issue_device_token(secret, args.device_id))
    return 0


def _kb(args: argparse.Namespace) -> int:
    """本地知识库管理台：kb-api + （可选）explorer 子进程。

    只绑回环：这是单用户管理面，没有公网入口。前端构建产物缺失时纯 API 运行，
    开发期用 Vite 的 5173 端口直连。
    """
    import uvicorn

    knowledge = _knowledge_dir(args.knowledge_dir).resolve()
    if not knowledge.is_dir():
        print(f"知识库目录不存在: {knowledge}", file=sys.stderr)
        return 2
    graph_out = Path(args.graph_out or os.environ.get("MEMHUB_KB_GRAPH", "kb/kg.json")).resolve()
    web_dist = args.web_dist or os.environ.get("MEMHUB_KB_WEB_DIST", "")
    os.environ["MEMHUB_KNOWLEDGE_DIR"] = str(knowledge)
    os.environ["MEMHUB_KB_GRAPH"] = str(graph_out)
    if web_dist:
        os.environ["MEMHUB_KB_WEB_DIST"] = str(Path(web_dist).resolve())
    if args.spawn_graph:
        os.environ["MEMHUB_KB_GRAPH_PORT"] = str(args.graph_port)
    port = args.port or int(os.environ.get("MEMHUB_KB_HTTP_PORT", "8701"))
    print(f"memhub kb-api: http://127.0.0.1:{port}/  真源={knowledge}", flush=True)
    if graph_out.is_file():
        print(f"投影: {graph_out}", flush=True)
    if args.spawn_graph:
        print(f"explorer 由 kb-api 托管: http://127.0.0.1:{args.graph_port}/", flush=True)
    uvicorn.run(
        "memhub.kb.api:create_app",
        factory=True,
        host="127.0.0.1",
        port=port,
        log_level=os.environ.get("MEMHUB_LOG_LEVEL", "INFO").lower(),
    )
    return 0


def _api(args: argparse.Namespace) -> int:
    import uvicorn

    host = resolve_bind_host(args.allow_non_loopback)
    port = int(os.environ.get("MEMHUB_HTTP_PORT", "8700"))
    dsn = os.environ.get("MEMHUB_DB_URL", "")
    if dsn:
        # 启动时把表建出来：容器重启不该依赖有人先跑一次 purge 才有表。
        # 幂等，重复启动只会打印 "already up to date"。
        from memhub.ingest.postgres import PostgresStore

        store = PostgresStore(dsn, min_size=1, max_size=1)
        try:
            applied = store.migrate()
        finally:
            store.close()
        print(f"schema: {applied or 'already up to date'}", flush=True)
    print(f"memhub ingest-api: http://{host}:{port}/", flush=True)
    uvicorn.run(
        "memhub.ingest.app:create_app",
        factory=True,
        host=host,
        port=port,
        log_level=os.environ.get("MEMHUB_LOG_LEVEL", "INFO").lower(),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
