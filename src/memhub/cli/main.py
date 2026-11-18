"""运维命令入口：ingest / project / serve。"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from memhub import __version__
from memhub.contract import SourceKind, SourceRef
from memhub.kb.projection import save_projection
from memhub.kb.store import KnowledgeStore
from memhub.worker.extract import ExtractionFailed, extract_document
from memhub.worker.llm import AnthropicClient, LLMError
from memhub.worker.merge import merge
from memhub.worker.prompts import load_profile
from memhub.worker.render import render_jsonl

SKELETON_PAGES = {"schema.md", "log.md", "purpose.md"}


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


def _serve(args: argparse.Namespace) -> int:
    graph = Path(args.graph)
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
    return subprocess.call(command)


if __name__ == "__main__":
    raise SystemExit(main())
