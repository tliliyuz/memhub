"""MCP 写候选：只创建 `tier=candidate` 节点，不动 canonical。

第一阶段的写路径复用管理端的跨进程写锁、归档门禁与文件原子写，不新增第二个
真源写者。拒绝都带稳定的 `data.reason`（见 `docs/contracts/mcp-tools.md` §3）：

- `slug_conflict_canonical` / `slug_conflict_candidate`：slug 已被占用，绝不覆盖。
- `content_duplicate`：归一化正文哈希命中同项目已有候选。
- `evidence_missing` / `evidence_invalid` / `evidence_out_of_scope`：证据结构与归属。
- `secret_detected`：证据、标题或正文命中敏感串形态。
- `content_rejected`：过短、寒暄/确认、日志倾倒等可机械识别的垃圾。
- `daily_limit_exceeded`：同一凭据同一 UTC 日写入达到上限。
- `project_unavailable`：项目不在授权范围、未登记或已归档。
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import UTC, datetime
from typing import Any

from memhub.contract import ErrorCode, NodeFrontmatter, SourceKind, SourceRef, Tier
from memhub.contract.mcp import DeprecateInput, UpdateCandidateInput, WriteCandidateInput
from memhub.contract.models import KB_ID_RE
from memhub.kb import archive, query, target_access
from memhub.kb.manage import (
    ConflictError,
    ManageError,
    NotFoundError,
    WriteDeferred,
    commit_source,
    guard_project_write,
    node_revision,
    write_lock,
)
from memhub.kb.reader import ActiveReader
from memhub.kb.store import KnowledgeStore

DAILY_LIMIT = 50
MIN_TITLE = 2
MAX_TITLE = 200
MIN_BODY = 20
MAX_BODY = 20_000
MAX_EVIDENCE = 16
MAX_REF = 512

_ABSOLUTE = re.compile(r"^(?:[\\/]|[A-Za-z]:)")
_LOG_LINE = re.compile(
    r"^(?:\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}"
    r"|\[?\d{2}:\d{2}:\d{2}"
    r"|(?:INFO|WARN|WARNING|ERROR|DEBUG|TRACE|CRITICAL)\b)"
)
_SECRET = re.compile(
    r"(?:sk-[A-Za-z0-9_-]{16,}"
    r"|gh[pousr]_[A-Za-z0-9]{16,}"
    r"|xox[baprs]-[A-Za-z0-9-]{10,}"
    r"|AKIA[0-9A-Z]{16}"
    r"|-----BEGIN [A-Z ]{0,40}PRIVATE KEY-----"
    r"|(?i:bearer|token|password|passwd|secret)\s*[:=]\s*\S{8,})"
)
# 寒暄、确认与「继续」类纯噪声；归一化后整条命中才拒绝。
_ACKS = frozenset(
    {
        "好的",
        "好",
        "收到",
        "明白",
        "了解",
        "知道了",
        "已完成",
        "完成",
        "继续",
        "开始吧",
        "可以",
        "谢谢",
        "感谢",
        "ok",
        "okay",
        "thanks",
        "thank you",
    }
)


class CandidateRejected(ManageError):
    """输入层面的拒绝（`400/1003`），`data.reason` 给出细分原因。"""

    status = 400
    code = ErrorCode.BAD_REQUEST

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message, {"reason": reason})
        self.reason = reason


class CandidateConflict(ConflictError):
    """与既有节点冲突（`409/1010`），不覆盖。"""

    def __init__(self, reason: str, message: str, data: dict[str, Any] | None = None) -> None:
        super().__init__(message, {"reason": reason, **(data or {})})
        self.reason = reason


def _normalize(text: str) -> str:
    """NFKC、折叠空白、小写；用于正文哈希与寒暄判定。"""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text)).strip().lower()


def _content_digest(body: str) -> str:
    return hashlib.sha256(_normalize(body).encode("utf-8")).hexdigest()


def _reject(reason: str, message: str) -> CandidateRejected:
    return CandidateRejected(reason, message)


def _check_content(draft: WriteCandidateInput) -> None:
    _check_text(draft.title, draft.body)


def _check_text(title: str, body: str) -> None:
    """标题与正文的确定性门槛；更新与创建共用。"""
    title = title.strip()
    body = body.strip()
    if not MIN_TITLE <= len(title) <= MAX_TITLE:
        raise _reject("content_rejected", f"title 必须在 {MIN_TITLE}–{MAX_TITLE} 字符之间")
    if not MIN_BODY <= len(body) <= MAX_BODY:
        raise _reject("content_rejected", f"body 必须在 {MIN_BODY}–{MAX_BODY} 字符之间")
    if _normalize(title) in _ACKS or _normalize(body) in _ACKS:
        raise _reject("content_rejected", "寒暄、确认或临时进度不是可复用的知识")
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    if len(lines) >= 10:
        hits = sum(1 for line in lines if _LOG_LINE.match(line))
        if hits / len(lines) >= 0.6:
            raise _reject("content_rejected", "原始日志不是可复用的知识")
    for value in (title, body):
        if _SECRET.search(value):
            raise _reject("secret_detected", "内容命中凭据或密钥形态，拒绝写入真源")


async def _check_evidence(
    store: KnowledgeStore,
    evidence: list[SourceRef],
    *,
    projects: frozenset[str] | None,
) -> None:
    if not evidence:
        raise _reject("evidence_missing", "至少提供一条可追溯的证据")
    if len(evidence) > MAX_EVIDENCE:
        raise _reject("evidence_invalid", f"evidence 最多 {MAX_EVIDENCE} 条")
    for item in evidence:
        ref = item.ref
        if (
            not ref
            or ref != ref.strip()
            or len(ref) > MAX_REF
            or any(ord(char) < 0x20 for char in ref)
            or ref.lower().startswith("mcp:")
        ):
            raise _reject("evidence_invalid", "证据引用不合法或使用了服务端保留前缀")
        if _ABSOLUTE.match(ref) or ".." in re.split(r"[\\/]", ref):
            raise _reject("evidence_invalid", "证据引用不得是绝对路径或包含路径穿越")
        if item.captured_at is not None and item.captured_at.utcoffset() is None:
            raise _reject("evidence_invalid", "captured_at 必须带时区")
        if _SECRET.search(ref):
            raise _reject("secret_detected", "证据引用命中凭据或密钥形态")
        if projects is None:
            continue
        first = re.split(r"[\\/]", ref, maxsplit=1)[0]
        if first in projects:
            continue
        # 只在首段确实是已登记知识库目录时判越权，避免误伤 `wiki/...` 等普通引用。
        if KB_ID_RE.fullmatch(first) and await target_access.registered_active(store, first):
            raise _reject("evidence_out_of_scope", "证据指向未授权的知识库")


def _check_project(project: str, projects: frozenset[str] | None) -> None:
    if projects is not None and project not in projects:
        raise _reject("project_unavailable", "该知识库不在授权范围")


async def _existing_tier(store: KnowledgeStore, node_id: str) -> Tier | None:
    try:
        node, _ = await store.read(node_id)
    except FileNotFoundError:
        return None
    return node.tier


def _daily_count(records: list[query.NodeRecord], grant_id: str, now: datetime) -> int:
    marker = f"mcp:{grant_id}"
    count = 0
    for record in records:
        created = record.node.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=UTC)
        if created.astimezone(UTC).date() == now.date() and any(
            source.type is SourceKind.MANUAL and source.ref == marker
            for source in record.node.source
        ):
            count += 1
    return count


async def _open_candidate(
    store: KnowledgeStore,
    node_id: str,
    *,
    projects: frozenset[str] | None,
) -> tuple[NodeFrontmatter, str, str]:
    """持锁后确认目标可用且仍是候选；返回 (frontmatter, 正文, 当前修订号)。

    调用方必须已在 `write_lock` 内。越权与不存在一律按不存在处理，不泄露存在性。
    """
    project = node_id.split("/", 1)[0]
    if projects is not None and project not in projects:
        raise NotFoundError(f"节点不存在: {node_id}")
    try:
        await guard_project_write(store.root, project)
    except WriteDeferred as exc:
        raise _reject("project_unavailable", "知识库已归档或正在归档，暂不能写入") from exc
    if not await target_access.registered_active(store, project):
        raise _reject("project_unavailable", "知识库未登记或不可用")
    path = await archive.checked_path(store.root, f"{node_id}.md")
    if await archive.path_kind(path) != "file":
        raise NotFoundError(f"节点不存在: {node_id}")
    node, body = await store.read(node_id)
    if node.tier is not Tier.CANDIDATE:
        raise CandidateConflict(
            "not_candidate", "只有 tier=candidate 的节点可以这样修改", {"id": node_id}
        )
    revision = await node_revision(store, node_id)
    assert revision is not None
    return node, body, revision


def _require_revision(node_id: str, expected: str, current: str) -> None:
    if expected != current:
        raise CandidateConflict(
            "revision_conflict",
            "节点已被其他人/进程修改，请重新读取后再试",
            {"id": node_id, "expected": expected, "current": current},
        )


async def _body_taken_by_other(
    store: KnowledgeStore,
    *,
    node_id: str,
    project: str,
    body: str,
    projects: frozenset[str] | None,
) -> bool:
    """同项目内是否已有其它候选使用归一化后相同的正文。"""
    records = await query.records(ActiveReader(store, projects))
    digest = _content_digest(body)
    return any(
        record.id != node_id
        and record.node.tier is Tier.CANDIDATE
        and record.id.split("/", 1)[0] == project
        and _content_digest(record.body) == digest
        for record in records
    )


async def update_candidate(
    store: KnowledgeStore,
    draft: UpdateCandidateInput,
    *,
    grant_id: str,
    projects: frozenset[str] | None,
) -> dict[str, Any]:
    """按修订号更新自己的候选；只改标题、正文、标签与置信度。"""
    node_id = draft.id
    async with write_lock(store.root, timeout=0):
        node, body, revision = await _open_candidate(store, node_id, projects=projects)
        _require_revision(node_id, draft.expected_revision, revision)

        title = node.title if draft.title is None else draft.title
        new_body = body if draft.body is None else draft.body
        _check_text(title, new_body)
        if draft.body is not None and await _body_taken_by_other(
            store,
            node_id=node_id,
            project=node.project,
            body=new_body,
            projects=projects,
        ):
            raise CandidateConflict("content_duplicate", "同项目已存在正文相同的候选")

        data = node.model_dump(mode="json")
        data["id"] = node_id
        data["title"] = title.strip()
        if draft.tags is not None:
            data["tags"] = draft.tags
        if draft.confidence is not None:
            data["confidence"] = draft.confidence
        data["updated_at"] = datetime.now(UTC)
        try:
            updated = NodeFrontmatter.model_validate(data)
        except ValueError as exc:
            raise _reject("content_rejected", "更新后的元数据不满足节点契约") from exc
        await store.write(node_id, updated, new_body)
        new_revision = await node_revision(store, node_id)
        commit = await commit_source(
            store.root,
            f"kb: 更新候选 kb_update_candidate {node_id} mcp:{grant_id}",
            node_path=f"{node_id}.md",
        )
    return {
        "id": node_id,
        "tier": Tier.CANDIDATE.value,
        "revision": new_revision,
        "commit": commit,
    }


async def deprecate_candidate(
    store: KnowledgeStore,
    draft: DeprecateInput,
    *,
    grant_id: str,
    projects: frozenset[str] | None,
) -> dict[str, Any]:
    """把候选标为 deprecated 并保留文件；替代节点可省，原因必留。"""
    node_id = draft.id
    reason = draft.reason.strip()
    async with write_lock(store.root, timeout=0):
        node, body, revision = await _open_candidate(store, node_id, projects=projects)
        _require_revision(node_id, draft.expected_revision, revision)

        successor = draft.superseded_by
        if successor is not None:
            if successor == node_id:
                raise _reject("superseded_by_invalid", "替代节点不能是节点自己")
            successor_project = successor.split("/", 1)[0]
            if projects is not None and successor_project not in projects:
                raise _reject("superseded_by_unavailable", "替代节点不在授权范围")
            successor_path = await archive.checked_path(store.root, f"{successor}.md")
            if await archive.path_kind(successor_path) != "file":
                raise _reject("superseded_by_unavailable", "替代节点不存在")

        data = node.model_dump(mode="json")
        data["id"] = node_id
        data["tier"] = Tier.DEPRECATED
        data["superseded_by"] = successor
        data["deprecated_reason"] = reason or None
        data["updated_at"] = datetime.now(UTC)
        try:
            updated = NodeFrontmatter.model_validate(data)
        except ValueError as exc:
            raise _reject("content_rejected", "废弃后的元数据不满足节点契约") from exc
        new_body = body
        if reason:
            new_body = body.rstrip() + f"\n\n## 废弃说明\n\n{reason}（mcp:{grant_id}）\n"
            if len(new_body.strip()) > MAX_BODY:
                raise _reject("content_rejected", f"追加废弃说明后正文超过 {MAX_BODY} 字符")
        await store.write(node_id, updated, new_body)
        new_revision = await node_revision(store, node_id)
        commit = await commit_source(
            store.root,
            f"kb: 废弃候选 kb_deprecate {node_id} mcp:{grant_id}",
            node_path=f"{node_id}.md",
        )
    return {
        "id": node_id,
        "tier": Tier.DEPRECATED.value,
        "revision": new_revision,
        "commit": commit,
    }


async def create_candidate(
    store: KnowledgeStore,
    draft: WriteCandidateInput,
    *,
    grant_id: str,
    projects: frozenset[str] | None,
) -> dict[str, Any]:
    """校验并创建一个候选节点；成功即提交一次真源 git commit。"""
    _check_project(draft.project, projects)
    _check_content(draft)

    node_id = f"{draft.project}/{draft.kind.value}/{draft.slug}"
    async with write_lock(store.root, timeout=0):
        try:
            await guard_project_write(store.root, draft.project)
        except WriteDeferred as exc:
            raise _reject("project_unavailable", "知识库已归档或正在归档，暂不能写入") from exc
        if not await target_access.registered_active(store, draft.project):
            raise _reject("project_unavailable", "知识库未登记或不可用")

        await _check_evidence(store, draft.evidence, projects=projects)
        try:
            path = await archive.checked_path(store.root, f"{node_id}.md")
            if await archive.path_kind(path) not in {None, "file"}:
                raise ConflictError("节点路径不是普通文件")
        except ConflictError as exc:
            raise _reject("project_unavailable", "目标节点路径不可用") from exc

        tier = await _existing_tier(store, node_id)
        if tier is Tier.CANONICAL or tier is Tier.DEPRECATED:
            raise CandidateConflict(
                "slug_conflict_canonical", f"slug 已被权威节点占用: {node_id}", {"id": node_id}
            )
        if tier is Tier.CANDIDATE:
            raise CandidateConflict(
                "slug_conflict_candidate", f"slug 已有候选节点: {node_id}", {"id": node_id}
            )
        reader = ActiveReader(store, projects)
        records = await query.records(reader)
        digest = _content_digest(draft.body)
        if any(
            record.node.tier is Tier.CANDIDATE
            and record.id.split("/", 1)[0] == draft.project
            and _content_digest(record.body) == digest
            for record in records
        ):
            raise CandidateConflict("content_duplicate", "同项目已存在正文相同的候选")
        now = datetime.now(UTC)
        if _daily_count(records, grant_id, now) >= DAILY_LIMIT:
            raise CandidateConflict(
                "daily_limit_exceeded", f"同一凭据每日最多写入 {DAILY_LIMIT} 条候选"
            )
        source = [
            *draft.evidence,
            SourceRef(type=SourceKind.MANUAL, ref=f"mcp:{grant_id}", captured_at=now),
        ]
        node = NodeFrontmatter(
            id=node_id,
            kind=draft.kind,
            title=draft.title.strip(),
            tier=Tier.CANDIDATE,
            confidence=draft.confidence,
            project=draft.project,
            tags=draft.tags,
            source=source,
            created_at=now,
            updated_at=now,
        )
        await store.write(node_id, node, draft.body)
        revision = await node_revision(store, node_id)
        commit = await commit_source(
            store.root,
            f"kb: 写入候选 kb_write_candidate {node_id} mcp:{grant_id}",
            node_path=f"{node_id}.md",
        )

    return {"id": node_id, "tier": Tier.CANDIDATE.value, "revision": revision, "commit": commit}
