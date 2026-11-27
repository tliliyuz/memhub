"""MCP 首版工具的参数契约，供工具列表与服务端校验共用。"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from memhub.contract.models import KB_ID_PATTERN, Kind, Predicate, SourceRef

SLUG_PATTERN = r"[a-z0-9][a-z0-9-]{0,127}"
_KINDS = "|".join(kind.value for kind in Kind)
NODE_ID_PATTERN = rf"^{KB_ID_PATTERN[1:-1]}/({_KINDS})/{SLUG_PATTERN}$"
ResultLimit = Annotated[int, Field(ge=1, le=50)]
# 长期记忆 slug 规则由记忆条目定义（ADR-0019），输入校验与聚合侧共用同一套字符集。
MEMORY_SLUG_PATTERN = r"^[a-z0-9][a-z0-9-]{0,99}$"


class ToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class SearchInput(ToolInput):
    query: str = Field(max_length=512, description="用户问题或关键词；中英文均可，最多 512 字符。")
    project: str | None = Field(
        default=None,
        pattern=KB_ID_PATTERN,
        description="限定知识库 id；省略时在凭据授权的全部库内检索。",
    )
    kinds: list[Kind] | None = Field(
        default=None, max_length=len(Kind), description="限定节点类型；省略时不限。"
    )
    tier: Literal["canonical", "all"] = Field(
        default="canonical",
        description="canonical 只含有效节点；all 才包含 deprecated。",
    )
    limit: ResultLimit = Field(default=8, description="返回条数上限，1–50。")


class ReadInput(ToolInput):
    id: str = Field(pattern=NODE_ID_PATTERN, description="完整节点 id，形如 project/kind/slug。")


class RelatedInput(ReadInput):
    depth: int = Field(default=1, ge=1, le=2, description="扩展跳数，1–2。")
    predicates: list[Predicate] | None = Field(
        default=None, max_length=len(Predicate), description="只沿指定关系扩展；省略时不限。"
    )
    limit: ResultLimit = Field(default=30, description="返回节点上限，1–50。")


class AuditInput(ToolInput):
    limit: ResultLimit = Field(default=50, description="返回条数上限，1–50。")
    offset: int = Field(default=0, ge=0, description="分页偏移，从 0 开始。")


class MemorySearchInput(ToolInput):
    query: str = Field(
        min_length=1,
        max_length=512,
        description="检索已发布长期记忆的关键词或结论片段；中英文均可，最多 512 字符。",
    )
    limit: int = Field(default=5, ge=1, le=20, description="返回条数上限，1–20。")


class MemoryReadInput(ToolInput):
    slug: str = Field(
        pattern=MEMORY_SLUG_PATTERN,
        description="记忆 slug，形如 retry-backoff；取自 kb_memory_search 的结果。",
    )


class WriteCandidateInput(ToolInput):
    """只创建候选节点；长度与内容门槛在 `memhub.kb.candidates` 里按业务规则判定。"""

    project: str = Field(pattern=KB_ID_PATTERN, description="目标知识库 id，必须已登记且活动。")
    kind: Kind = Field(description="节点类型。")
    slug: str = Field(
        pattern=f"^{SLUG_PATTERN}$", description="库内唯一 slug；命中已有节点会被拒绝。"
    )
    title: str = Field(description="标题，2–200 字符。")
    body: str = Field(description="正文 markdown，20–20000 字符。")
    evidence: list[SourceRef] = Field(
        description="原文来源引用，至少一条，形状与节点 source 一致。"
    )
    tags: list[str] = Field(default_factory=list, max_length=16, description="标签，最多 16 个。")
    confidence: float | None = Field(
        default=None, ge=0, le=1, description="置信度 0–1；不确定时省略。"
    )


class RevisionedNode(ToolInput):
    """按修订号定位候选节点；`expected_revision` 是乐观并发前置条件。"""

    id: str = Field(pattern=NODE_ID_PATTERN, description="完整节点 id，形如 project/kind/slug。")
    expected_revision: str = Field(
        min_length=16,
        max_length=16,
        pattern=r"^[0-9a-f]{16}$",
        description="取自 kb_read 的当前修订号，用于乐观并发校验。",
    )


class UpdateCandidateInput(RevisionedNode):
    """只改候选节点的标题、正文、标签与置信度；至少给一项。"""

    title: str | None = Field(default=None, description="新标题，2–200 字符。")
    body: str | None = Field(default=None, description="新正文 markdown，20–20000 字符。")
    tags: list[str] | None = Field(default=None, max_length=16, description="新标签，最多 16 个。")
    confidence: float | None = Field(default=None, ge=0, le=1, description="新置信度 0–1。")

    @model_validator(mode="after")
    def at_least_one_field(self) -> UpdateCandidateInput:
        if not any(
            value is not None for value in (self.title, self.body, self.tags, self.confidence)
        ):
            raise ValueError("至少提供 title、body、tags、confidence 之一")
        return self


class DeprecateInput(RevisionedNode):
    """把候选标记为废弃并保留文件；替代节点与原因至少给一项。"""

    reason: str = Field(
        default="", max_length=2000, description="废弃原因，写入 deprecated_reason。"
    )
    superseded_by: str | None = Field(
        default=None, pattern=NODE_ID_PATTERN, description="替代节点 id，可选。"
    )

    @model_validator(mode="after")
    def needs_reason_or_successor(self) -> DeprecateInput:
        if not self.reason.strip() and not self.superseded_by:
            raise ValueError("必须提供 reason 或 superseded_by")
        return self
