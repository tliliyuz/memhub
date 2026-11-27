#!/usr/bin/env python3
"""kb-api 连接预算并发冒烟（ADR-0021 上线验收）。

同时并发请求 graph / stats / nodes，确认角色连接上限没有被多进程共用打爆：
任何 5xx（尤其是 PG `too many connections` 引起的 500）或请求异常都判失败。
脚本只读，不写库；默认打本机回环的 kb-api（公网入口有登录墙，不适合脚本）。

退出码：0 全部非 5xx；1 有 5xx / 请求失败；2 参数或前置条件错误（如没有可测的库）。

用法：
    python scripts/kb_concurrency_smoke.py
    python scripts/kb_concurrency_smoke.py --base-url http://127.0.0.1:8701 \
        --project memhub --concurrency 8 --rounds 5
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass

import httpx

_TARGETS = ("graph", "stats", "nodes")


@dataclass(frozen=True)
class Attempt:
    target: str
    status: int | None
    error: str | None


def _urls(base: str, project: str) -> dict[str, str]:
    root = base.rstrip("/")
    return {
        "graph": f"{root}/api/v1/kb/graph?project={project}",
        "stats": f"{root}/api/v1/kb/stats",
        "nodes": f"{root}/api/v1/kb/nodes?project={project}&limit=200",
    }


async def _pick_project(client: httpx.AsyncClient, base: str) -> str | None:
    response = await client.get(f"{base.rstrip('/')}/api/v1/kb/projects")
    response.raise_for_status()
    body = response.json()
    items = body.get("data") or body.get("items") or []
    if isinstance(items, dict):
        items = items.get("projects") or items.get("items") or []
    for item in items:
        if isinstance(item, dict):
            project = item.get("id") or item.get("project") or item.get("name")
        else:
            project = str(item)
        if project:
            return str(project)
    return None


async def _hit(client: httpx.AsyncClient, target: str, url: str) -> Attempt:
    try:
        response = await client.get(url)
    except httpx.HTTPError as exc:
        return Attempt(target, None, f"{type(exc).__name__}: {exc}")
    if response.status_code >= 500:
        snippet = response.text[:200].replace("\n", " ")
        return Attempt(target, response.status_code, snippet)
    return Attempt(target, response.status_code, None)


async def _run(base: str, project: str, concurrency: int, rounds: int) -> list[Attempt]:
    urls = _urls(base, project)
    async with httpx.AsyncClient(timeout=30.0) as client:
        semaphore = asyncio.Semaphore(concurrency)

        async def one(target: str) -> Attempt:
            async with semaphore:
                return await _hit(client, target, urls[target])

        attempts: list[Attempt] = []
        tasks = [one(target) for _ in range(rounds) for target in _TARGETS]
        attempts.extend(await asyncio.gather(*tasks))
        return attempts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8701")
    parser.add_argument("--project", default=None, help="缺省取第一个已登记库")
    parser.add_argument("--concurrency", type=int, default=6)
    parser.add_argument("--rounds", type=int, default=3)
    args = parser.parse_args(argv)
    if args.concurrency < 1 or args.rounds < 1:
        print("--concurrency / --rounds 必须是正整数", file=sys.stderr)
        return 2

    async def outcome() -> int:
        async with httpx.AsyncClient(timeout=30.0) as client:
            project = args.project
            if project is None:
                try:
                    project = await _pick_project(client, args.base_url)
                except httpx.HTTPError as exc:
                    print(
                        f"无法读取 /api/v1/kb/projects：{type(exc).__name__}: {exc}",
                        file=sys.stderr,
                    )
                    return 2
            if not project:
                print("没有可测的已登记库；请用 --project 指定", file=sys.stderr)
                return 2
        attempts = await _run(args.base_url, project, args.concurrency, args.rounds)
        failures = [item for item in attempts if item.status is None or item.status >= 500]
        by_target: dict[str, list[int]] = {target: [] for target in _TARGETS}
        for item in attempts:
            if item.status is not None:
                by_target[item.target].append(item.status)
        summary = "，".join(
            f"{target}: {len(statuses)} 次，最高 {max(statuses)}" if statuses else f"{target}: 0 次"
            for target, statuses in by_target.items()
        )
        print(f"项目 {project}；{summary}")
        if failures:
            for item in failures:
                print(
                    f"失败 {item.target}: {item.status if item.status is not None else item.error}",
                    file=sys.stderr,
                )
            print("有 5xx 或请求失败：检查连接上限与容器日志", file=sys.stderr)
            return 1
        print("全部非 5xx：连接预算未见打爆")
        return 0

    return asyncio.run(outcome())


if __name__ == "__main__":
    raise SystemExit(main())
