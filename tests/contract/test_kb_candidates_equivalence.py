"""MCP 写候选在文件存储与 PG 存储下行为等价（规格 §8.4/§8.5）。

验收条件从规格导出，不看实现形状：同一串 `candidates` 调用分别喂给
`KnowledgeStore`（markdown，迁移前的真源）与 `PgKnowledgeStore`（`kb_*` 表），
断言拒绝码、`data.reason`、状态码与落库结果一致。任一侧不成立即为行为变更，
必须回到规格裁决。

覆盖：
- §8.4 tier 边界：canonical 上的 `kb_update_candidate` / `kb_deprecate` → `not_candidate`。
- §8.5 去重与拒绝码：slug 冲突、正文哈希去重、证据校验、每日上限；
  `daily_limit_exceeded` 仍是 409/1010（原实现是 `CandidateConflict`，不是 429）。
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine

from memhub.contract import ErrorCode, Kind, NodeFrontmatter, SourceKind, SourceRef, Tier
from memhub.contract.mcp import DeprecateInput, UpdateCandidateInput, WriteCandidateInput
from memhub.kb import candidates, catalog
from memhub.kb.models import Base
from memhub.kb.pgstore import PgKnowledgeStore
from memhub.kb.session import create_sessionmaker
from memhub.kb.store import KnowledgeStore

REVISION_RE = re.compile(r"^[0-9a-f]{16}$")
PROJECT = "sample"
OTHER = "other"
GRANT = "abcdef012345"
BODY = "这是一段至少二十个字符的正文，用来通过内容门槛的最低长度检查。"


@pytest_asyncio.fixture(params=["file", "pg"])
async def store(
    request: pytest.FixtureRequest, tmp_path: Path, kb_engine: AsyncEngine
) -> AsyncIterator[KnowledgeStore | PgKnowledgeStore]:
    if request.param == "file":
        kb = KnowledgeStore(tmp_path)
        await catalog.create_kb(kb, kb_id=PROJECT, name=PROJECT)
        await catalog.create_kb(kb, kb_id=OTHER, name=OTHER)
        yield kb
        return

    async with kb_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    pg = PgKnowledgeStore(create_sessionmaker(kb_engine))
    await pg.register_project(PROJECT, name=PROJECT)
    await pg.register_project(OTHER, name=OTHER)
    yield pg


def _draft(**overrides: Any) -> WriteCandidateInput:
    data: dict[str, Any] = {
        "project": PROJECT,
        "kind": Kind.FACT,
        "slug": "mcp-write-fixture",
        "title": "MCP 写候选夹具",
        "body": BODY,
        "evidence": [
            SourceRef(
                type=SourceKind.SESSION,
                ref="session:abc",
                captured_at=datetime.now(UTC),
            )
        ],
    }
    data.update(overrides)
    return WriteCandidateInput(**data)


def _node(node_id: str, *, tier: Tier) -> NodeFrontmatter:
    now = datetime.now(UTC)
    return NodeFrontmatter(
        id=node_id,
        project=node_id.split("/", 1)[0],
        kind=Kind.FACT,
        title="既有节点",
        tier=tier,
        created_at=now,
        updated_at=now,
    )


async def _create(
    store: KnowledgeStore | PgKnowledgeStore,
    *,
    projects: frozenset[str] | None = None,
    **overrides: Any,
) -> dict[str, Any]:
    return await candidates.create_candidate(
        store, _draft(**overrides), grant_id=GRANT, projects=projects
    )


async def test_create_candidate_round_trip(store: KnowledgeStore | PgKnowledgeStore) -> None:
    created = await _create(store)
    assert created["id"] == "sample/fact/mcp-write-fixture"
    assert created["tier"] == Tier.CANDIDATE.value
    assert REVISION_RE.fullmatch(created["revision"])
    assert created["revision"] == await store.revision(created["id"])
    assert created["commit"] is None or isinstance(created["commit"], str)

    node, body = await store.read(created["id"])
    assert node.tier is Tier.CANDIDATE
    assert node.title == "MCP 写候选夹具"
    assert body.rstrip() == BODY.rstrip()
    refs = {source.ref for source in node.source}
    assert f"mcp:{GRANT}" in refs and "session:abc" in refs


async def test_slug_conflicts_never_overwrite(store: KnowledgeStore | PgKnowledgeStore) -> None:
    node_id = "sample/fact/mcp-write-fixture"
    await store.write(node_id, _node(node_id, tier=Tier.CANONICAL), "既有正文")

    with pytest.raises(candidates.CandidateConflict) as canonical:
        await _create(store)
    assert canonical.value.data["reason"] == "slug_conflict_canonical"
    assert (canonical.value.status, canonical.value.code) == (409, ErrorCode.KB_CONFLICT)
    assert (await store.read(node_id))[0].tier is Tier.CANONICAL

    await _create(store, slug="occupied")
    with pytest.raises(candidates.CandidateConflict) as candidate:
        await _create(store, slug="occupied", title="另一个标题")
    assert candidate.value.data["reason"] == "slug_conflict_candidate"
    assert (candidate.value.status, candidate.value.code) == (409, ErrorCode.KB_CONFLICT)


async def test_content_duplicate_rejected(store: KnowledgeStore | PgKnowledgeStore) -> None:
    await _create(store, slug="first")
    with pytest.raises(candidates.CandidateConflict) as info:
        await _create(store, slug="second")
    assert info.value.data["reason"] == "content_duplicate"
    assert not await store.exists("sample/fact/second")


async def test_daily_limit_is_conflict(
    store: KnowledgeStore | PgKnowledgeStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(candidates, "DAILY_LIMIT", 1)
    await _create(store, slug="first")
    with pytest.raises(candidates.CandidateConflict) as info:
        await _create(store, slug="second", body=BODY + "（第二段，正文不同）")
    assert info.value.data["reason"] == "daily_limit_exceeded"
    assert (info.value.status, info.value.code) == (409, ErrorCode.KB_CONFLICT)
    assert not await store.exists("sample/fact/second")


async def test_update_and_stale_revision(store: KnowledgeStore | PgKnowledgeStore) -> None:
    created = await _create(store)
    updated = await candidates.update_candidate(
        store,
        UpdateCandidateInput(
            id=created["id"], expected_revision=created["revision"], title="改过的标题"
        ),
        grant_id=GRANT,
        projects=None,
    )
    assert REVISION_RE.fullmatch(updated["revision"])
    assert updated["revision"] != created["revision"]
    assert updated["revision"] == await store.revision(created["id"])
    node, body = await store.read(created["id"])
    assert node.title == "改过的标题"
    assert body.rstrip() == BODY.rstrip()

    with pytest.raises(candidates.CandidateConflict) as stale:
        await candidates.update_candidate(
            store,
            UpdateCandidateInput(
                id=created["id"], expected_revision=created["revision"], title="旧版本覆盖"
            ),
            grant_id=GRANT,
            projects=None,
        )
    assert stale.value.data["reason"] == "revision_conflict"
    assert stale.value.data["current"] == updated["revision"]
    assert (await store.read(created["id"]))[0].title == "改过的标题"


async def test_tier_boundary_rejects_canonical(store: KnowledgeStore | PgKnowledgeStore) -> None:
    node_id = "sample/fact/canonical-node"
    await store.write(node_id, _node(node_id, tier=Tier.CANONICAL), "权威正文")
    revision = await store.revision(node_id)
    assert revision is not None

    with pytest.raises(candidates.CandidateConflict) as update:
        await candidates.update_candidate(
            store,
            UpdateCandidateInput(id=node_id, expected_revision=revision, title="试图改权威"),
            grant_id=GRANT,
            projects=None,
        )
    assert update.value.data["reason"] == "not_candidate"
    assert (update.value.status, update.value.code) == (409, ErrorCode.KB_CONFLICT)

    with pytest.raises(candidates.CandidateConflict) as deprecate:
        await candidates.deprecate_candidate(
            store,
            DeprecateInput(id=node_id, expected_revision=revision, reason="试图废弃权威"),
            grant_id=GRANT,
            projects=None,
        )
    assert deprecate.value.data["reason"] == "not_candidate"
    node, body = await store.read(node_id)
    assert node.tier is Tier.CANONICAL
    assert body.rstrip() == "权威正文"


async def test_deprecate_candidate_keeps_node(store: KnowledgeStore | PgKnowledgeStore) -> None:
    created = await _create(store)
    result = await candidates.deprecate_candidate(
        store,
        DeprecateInput(
            id=created["id"], expected_revision=created["revision"], reason="被新事实取代"
        ),
        grant_id=GRANT,
        projects=None,
    )
    assert result["tier"] == Tier.DEPRECATED.value
    assert REVISION_RE.fullmatch(result["revision"])
    assert result["revision"] == await store.revision(created["id"])
    node, body = await store.read(created["id"])
    assert node.tier is Tier.DEPRECATED
    assert node.deprecated_reason == "被新事实取代"
    assert "废弃说明" in body and "被新事实取代" in body


async def test_evidence_reasons(store: KnowledgeStore | PgKnowledgeStore) -> None:
    with pytest.raises(candidates.CandidateRejected) as missing:
        await _create(store, evidence=[])
    assert missing.value.data["reason"] == "evidence_missing"
    assert (missing.value.status, missing.value.code) == (400, ErrorCode.BAD_REQUEST)

    for ref in ("/etc/passwd", "../escape.md", "mcp:forged"):
        with pytest.raises(candidates.CandidateRejected) as invalid:
            await _create(
                store,
                evidence=[SourceRef(type=SourceKind.SESSION, ref=ref)],
            )
        assert invalid.value.data["reason"] == "evidence_invalid", ref

    with pytest.raises(candidates.CandidateRejected) as scope:
        await _create(
            store,
            evidence=[SourceRef(type=SourceKind.SESSION, ref=f"{OTHER}/fact/secret.md")],
            projects=frozenset({PROJECT}),
        )
    assert scope.value.data["reason"] == "evidence_out_of_scope"
    assert not await store.exists("sample/fact/mcp-write-fixture")


async def test_project_unavailable(store: KnowledgeStore | PgKnowledgeStore) -> None:
    with pytest.raises(candidates.CandidateRejected) as ghost:
        await _create(store, project="ghost")
    assert ghost.value.data["reason"] == "project_unavailable"
    assert (ghost.value.status, ghost.value.code) == (400, ErrorCode.BAD_REQUEST)


async def test_archived_project_unavailable(store: KnowledgeStore | PgKnowledgeStore) -> None:
    if isinstance(store, PgKnowledgeStore):
        await store.archive_project(PROJECT)
    else:
        await catalog.delete_kb(store, PROJECT, actor="fixture")

    with pytest.raises(candidates.CandidateRejected) as info:
        await _create(store)
    assert info.value.data["reason"] == "project_unavailable"
    assert not await store.exists("sample/fact/mcp-write-fixture")


async def test_secret_detected(store: KnowledgeStore | PgKnowledgeStore) -> None:
    with pytest.raises(candidates.CandidateRejected) as info:
        await _create(store, body="配置说明如下，token: abcdefghijklmnop 请勿外传。")
    assert info.value.data["reason"] == "secret_detected"
