"""长期记忆 worker 层：快照注入、聚合输入与 `memory-aggregate` 执行体（规格 §5–§7）。

- 注入：worker 启动时读一次已发布快照并冻结；每个会话窗口按 BM25 选条目，
  项目命中禁用列表时不注入，审计版本记 `null`。
- 聚合：只读 canonical 节点与门槛所需的最小条目状态（status/conclusion/evidence），
  **不读取任何记忆条目正文或快照作为模型输入**（AC-8）。
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from memhub.kb.memory import (
    CandidateWrite,
    MemoryPlan,
    MemoryWrite,
    parse_memories,
    plan_memories,
    render_memory_block,
    select_memories,
)
from memhub.worker.llm import LLMClient
from memhub.worker.prompts import render_nodes

DEFAULT_TOP_K = 8
DEFAULT_INJECT_CHARS = 4000
BODY_CHARS = 600
TOTAL_CHARS = 60000
AGGREGATE_ACTOR = "memory-aggregate"


class MemoryAggregateStore(Protocol):
    async def recent_memory_inputs(
        self, *, since: datetime, limit: int
    ) -> list[dict[str, Any]]: ...

    async def memory_states(self, slugs: Iterable[str]) -> dict[str, dict[str, Any]]: ...

    async def apply_memory_plan(
        self,
        plan: MemoryPlan,
        *,
        expected_states: Mapping[str, Mapping[str, Any]],
        actor: str | None = None,
        reason: str | None = None,
        now: datetime | None = None,
    ) -> list[dict[str, Any]]: ...

    async def publish_memory_snapshot(
        self, *, actor: str | None = None, note: str = ""
    ) -> dict[str, Any]: ...


class MemorySnapshotStore(Protocol):
    async def published_memory_snapshot(self) -> dict[str, Any] | None: ...


@dataclass(frozen=True, slots=True)
class MemorySettings:
    """注入侧配置；非法值抛 `ValueError`，由入口转成退出码 2。"""

    top_k: int = DEFAULT_TOP_K
    inject_chars: int = DEFAULT_INJECT_CHARS
    disabled_projects: frozenset[str] = frozenset()

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> MemorySettings:
        source = env if env is not None else {}
        top_k = _env_int(source, "MEMHUB_MEMORY_TOP_K", DEFAULT_TOP_K)
        if not 1 <= top_k <= 10:
            raise ValueError(f"MEMHUB_MEMORY_TOP_K 必须在 1–10 之间：{top_k}")
        inject_chars = _env_int(source, "MEMHUB_MEMORY_INJECT_CHARS", DEFAULT_INJECT_CHARS)
        if inject_chars <= 0:
            raise ValueError(f"MEMHUB_MEMORY_INJECT_CHARS 必须为正整数：{inject_chars}")
        raw_disabled = source.get("MEMHUB_MEMORY_INJECT_DISABLED_PROJECTS", "")
        disabled = frozenset(item.strip() for item in raw_disabled.split(",") if item.strip())
        return cls(top_k=top_k, inject_chars=inject_chars, disabled_projects=disabled)


def _env_int(env: Mapping[str, str], key: str, default: int) -> int:
    raw = env.get(key, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{key} 必须是整数：{raw!r}") from exc


@dataclass(frozen=True, slots=True)
class MemoryContext:
    """进程内固定的记忆快照；快照变更需要重启 worker 才生效（规格 §6）。"""

    version: int | None = None
    entries: tuple[Mapping[str, Any], ...] = ()
    settings: MemorySettings = MemorySettings()

    def select(self, query: str, *, project: str | None = None) -> list[dict[str, Any]]:
        if self.version is None or self._disabled(project):
            return []
        return select_memories(
            self.entries,
            query,
            top_k=self.settings.top_k,
            budget_chars=self.settings.inject_chars,
        )

    def block(self, query: str, *, project: str | None = None) -> str:
        return render_memory_block(self.select(query, project=project))

    def audit_version(self, project: str | None) -> int | None:
        """本次抽取应记入审计的快照版本；未发布或项目关闭时为空。"""
        if self.version is None or self._disabled(project):
            return None
        return self.version

    def _disabled(self, project: str | None) -> bool:
        return project is not None and project in self.settings.disabled_projects


async def load_memory_context(
    store: MemorySnapshotStore, settings: MemorySettings | None = None
) -> MemoryContext:
    snapshot = await store.published_memory_snapshot()
    if snapshot is None:
        return MemoryContext(settings=settings or MemorySettings())
    entries = snapshot.get("entries")
    return MemoryContext(
        version=int(snapshot["version"]),
        entries=tuple(entries) if isinstance(entries, list) else (),
        settings=settings or MemorySettings(),
    )


def render_node_inputs(
    nodes: Sequence[Mapping[str, Any]],
    *,
    body_chars: int = BODY_CHARS,
    total_chars: int = TOTAL_CHARS,
) -> str:
    """逐行 JSON；单条正文截断，总量超限时从最旧（列表尾部）开始丢弃。"""
    lines: list[str] = []
    used = 0
    for node in nodes:
        line = json.dumps(
            {
                "id": node.get("id"),
                "project": node.get("project"),
                "kind": node.get("kind"),
                "title": node.get("title", ""),
                "body": str(node.get("body", ""))[:body_chars],
                "source": node.get("source", []),
                "updated_at": _observed_at(node.get("updated_at")),
            },
            ensure_ascii=False,
        )
        extra = len(line) + (1 if lines else 0)
        if used + extra > total_chars:
            break
        lines.append(line)
        used += extra
    return "\n".join(lines)


def _observed_at(value: object) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, str) and value:
        return value
    return None


@dataclass(frozen=True, slots=True)
class AggregateReport:
    nodes: int
    drafts: int
    writes: tuple[MemoryWrite, ...]
    candidates: tuple[CandidateWrite, ...]
    published: int | None = None
    dry_run: bool = False


async def aggregate_memories(
    client: LLMClient,
    store: MemoryAggregateStore,
    *,
    model: str,
    template: str,
    since_days: int = 7,
    min_sessions: int = 3,
    min_projects: int = 2,
    max_nodes: int = 100,
    dry_run: bool = False,
    publish: bool = False,
    now: datetime | None = None,
) -> AggregateReport:
    """读节点 → 调模型 → 按实际来源计数裁决 → 原子落库（可选发布快照）。"""
    if since_days < 1 or max_nodes < 1 or min_sessions < 1 or min_projects < 1:
        raise ValueError("聚合参数必须是正整数")
    moment = now or datetime.now(UTC)
    nodes = await store.recent_memory_inputs(
        since=moment - timedelta(days=since_days), limit=max_nodes
    )
    if not nodes:
        return AggregateReport(nodes=0, drafts=0, writes=(), candidates=(), dry_run=dry_run)

    lookup = {str(node["id"]): node for node in nodes}
    raw = await client.complete(
        render_nodes(template, nodes=render_node_inputs(nodes)), model=model
    )
    drafts = parse_memories(raw, lookup)
    states = await store.memory_states([draft.slug for draft in drafts])
    plan = plan_memories(
        drafts,
        lookup,
        states,
        min_sessions=min_sessions,
        min_projects=min_projects,
    )

    published: int | None = None
    if not dry_run:
        if plan.writes or plan.candidates:
            await store.apply_memory_plan(
                plan,
                expected_states=states,
                actor=AGGREGATE_ACTOR,
                reason="aggregate",
            )
        if publish:
            snapshot = await store.publish_memory_snapshot(
                actor=AGGREGATE_ACTOR, note=f"aggregate since={since_days}d"
            )
            published = int(snapshot["version"])

    return AggregateReport(
        nodes=len(nodes),
        drafts=len(drafts),
        writes=tuple(plan.writes),
        candidates=tuple(plan.candidates),
        published=published,
        dry_run=dry_run,
    )
