"""MCP 首版工具的参数契约，供工具列表与服务端校验共用。"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from memhub.contract.models import KB_ID_PATTERN, Kind, Predicate, SourceRef

SLUG_PATTERN = r"[a-z0-9][a-z0-9-]{0,127}"
_KINDS = "|".join(kind.value for kind in Kind)
NODE_ID_PATTERN = rf"^{KB_ID_PATTERN[1:-1]}/({_KINDS})/{SLUG_PATTERN}$"
ResultLimit = Annotated[int, Field(ge=1, le=50)]


class ToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class SearchInput(ToolInput):
    query: str = Field(max_length=512)
    project: str | None = Field(default=None, pattern=KB_ID_PATTERN)
    kinds: list[Kind] | None = Field(default=None, max_length=len(Kind))
    tier: Literal["canonical", "candidate", "all"] = "canonical"
    limit: ResultLimit = 8


class ReadInput(ToolInput):
    id: str = Field(pattern=NODE_ID_PATTERN)


class RelatedInput(ReadInput):
    depth: int = Field(default=1, ge=1, le=2)
    predicates: list[Predicate] | None = Field(default=None, max_length=len(Predicate))
    limit: ResultLimit = 30


class AuditInput(ToolInput):
    limit: ResultLimit = 50
    offset: int = Field(default=0, ge=0)


class WriteCandidateInput(ToolInput):
    """只创建候选节点；长度与内容门槛在 `memhub.kb.candidates` 里按业务规则判定。"""

    project: str = Field(pattern=KB_ID_PATTERN)
    kind: Kind
    slug: str = Field(pattern=f"^{SLUG_PATTERN}$")
    title: str
    body: str
    evidence: list[SourceRef]
    tags: list[str] = Field(default_factory=list, max_length=16)
    confidence: float | None = Field(default=None, ge=0, le=1)


class RevisionedNode(ToolInput):
    """按修订号定位候选节点；`expected_revision` 是乐观并发前置条件。"""

    id: str = Field(pattern=NODE_ID_PATTERN)
    expected_revision: str = Field(min_length=16, max_length=16, pattern=r"^[0-9a-f]{16}$")


class UpdateCandidateInput(RevisionedNode):
    """只改候选节点的标题、正文、标签与置信度；至少给一项。"""

    title: str | None = None
    body: str | None = None
    tags: list[str] | None = Field(default=None, max_length=16)
    confidence: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def at_least_one_field(self) -> UpdateCandidateInput:
        if not any(
            value is not None for value in (self.title, self.body, self.tags, self.confidence)
        ):
            raise ValueError("至少提供 title、body、tags、confidence 之一")
        return self


class DeprecateInput(RevisionedNode):
    """把候选标记为废弃并保留文件；替代节点与原因至少给一项。"""

    reason: str = Field(default="", max_length=2000)
    superseded_by: str | None = Field(default=None, pattern=NODE_ID_PATTERN)

    @model_validator(mode="after")
    def needs_reason_or_successor(self) -> DeprecateInput:
        if not self.reason.strip() and not self.superseded_by:
            raise ValueError("必须提供 reason 或 superseded_by")
        return self
