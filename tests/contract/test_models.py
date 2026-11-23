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


def test_deprecated_requires_superseded_by_or_reason() -> None:
    with pytest.raises(ValidationError):
        NodeFrontmatter(**_base(tier=Tier.DEPRECATED))
    node = NodeFrontmatter(**_base(tier=Tier.DEPRECATED, superseded_by="x/y"))
    assert node.superseded_by == "x/y"
    # 结论被证伪时没有替代节点可指，只记原因也是合法废弃。
    reason_only = NodeFrontmatter(**_base(tier=Tier.DEPRECATED, deprecated_reason="已被证伪"))
    assert reason_only.deprecated_reason == "已被证伪"
    assert reason_only.superseded_by is None


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
    entry = SourceEntry(
        id="cc-sessions", name="x", type="sessions", path="C:/x", project="example-kb"
    )
    assert entry.enabled is True


def test_sources_config_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        SourcesConfig(device_id="d", unexpected=1)


def test_error_code_is_integer() -> None:
    body = ErrorBody(code=ErrorCode.CURSOR_CONFLICT, message="offset rollback")
    assert body.model_dump()["code"] == 1004


@pytest.mark.parametrize("project", ["auto", "", " example-kb", "Sdp Tag", "../kb", 42])
def test_source_project_must_be_explicit(project: str) -> None:
    with pytest.raises(ValidationError):
        SourceEntry(id="cc", name="x", type="sessions", path="C:/x", project=project)


def test_source_project_is_required() -> None:
    with pytest.raises(ValidationError):
        SourceEntry.model_validate({"id": "cc", "name": "x", "type": "sessions", "path": "C:/x"})
