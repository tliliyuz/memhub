"""契约模型验收：字段约束必须与 docs/contracts/ 的写法一致。"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from memhub.contract import (
    BatchFile,
    ErrorBody,
    ErrorCode,
    Kind,
    NodeFrontmatter,
    SourceEntry,
    SourcesConfig,
    Tier,
)


def _base(**overrides: object) -> dict[str, object]:
    now = datetime(2026, 11, 18, tzinfo=UTC)
    data: dict[str, object] = {
        "id": "memory-hub/entity/memory-hub",
        "kind": Kind.ENTITY,
        "entity_kind": "service",
        "title": "Memory Hub",
        "project": "memory-hub",
        "created_at": now,
        "updated_at": now,
    }
    data.update(overrides)
    return data


def test_entity_requires_entity_kind() -> None:
    with pytest.raises(ValidationError):
        NodeFrontmatter(**_base(entity_kind=None))


def test_question_requires_status() -> None:
    with pytest.raises(ValidationError):
        NodeFrontmatter(**_base(kind=Kind.QUESTION, entity_kind=None))


def test_deprecated_requires_superseded_by() -> None:
    with pytest.raises(ValidationError):
        NodeFrontmatter(**_base(tier=Tier.DEPRECATED))
    node = NodeFrontmatter(**_base(tier=Tier.DEPRECATED, superseded_by="x/y"))
    assert node.superseded_by == "x/y"


def test_batch_file_rejects_reversed_offsets() -> None:
    with pytest.raises(ValidationError):
        BatchFile(
            path="a.jsonl",
            from_offset=10,
            to_offset=5,
            mtime=datetime(2026, 11, 18, tzinfo=UTC),
            sha256="0" * 64,
            content="",
        )


def test_source_entry_id_is_slug() -> None:
    with pytest.raises(ValidationError):
        SourceEntry(id="CC-Sessions", name="x", type="sessions", path="C:/x")
    entry = SourceEntry(id="cc-sessions", name="x", type="sessions", path="C:/x")
    assert entry.enabled is True


def test_sources_config_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        SourcesConfig(device_id="d", unexpected=1)


def test_error_code_is_integer() -> None:
    body = ErrorBody(code=ErrorCode.CURSOR_CONFLICT, message="offset rollback")
    assert body.model_dump()["code"] == 1004


def test_source_project_must_be_auto_or_kb_id() -> None:
    """sources[].project 会变成真源目录名；桌面端写配置时就要拦住非法值。"""
    ok = SourceEntry(id="cc", name="x", type="sessions", path="C:/x", project="sdp-tag")
    assert ok.project == "sdp-tag"
    with pytest.raises(ValidationError):
        SourceEntry(id="cc", name="x", type="sessions", path="C:/x", project="Sdp Tag")


def test_resolve_project_falls_back_to_source_id() -> None:
    from memhub.contract import resolve_project

    assert resolve_project("sdp-tag", "claude-session-abc") == "sdp-tag"
    assert resolve_project("auto", "claude-session-abc") == "claude-session-abc"
    assert resolve_project(None, "claude-session-abc") == "claude-session-abc"
    # 非法值不能当目录名：白名单化，且不留下可逃逸真源的路径片段。
    assert resolve_project("../../etc", "My Source") == "my-source"
    assert "/" not in resolve_project("a/b", "src")
