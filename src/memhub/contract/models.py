"""跨端契约的唯一实现。

任何 API、worker、MCP、CLI 都从这里取模型与枚举，不允许在各自模块里重新解析或
手写字段名。契约文档见 `docs/contracts/`。
"""

from __future__ import annotations

import re
from datetime import datetime
from enum import IntEnum, StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# 知识库 id 在真源里就是一级目录名（`<knowledge>/<id>/...`），必须能安全拼路径。
# 采集端的 `sources[].project` 与桌面端「新建知识库」都按这个规则校验。
KB_ID_PATTERN = r"^[a-z0-9][a-z0-9._-]{0,63}$"
KB_ID_RE = re.compile(KB_ID_PATTERN)
# 保留值：采集端不指定知识库，由 worker 回退到 source_id（旧行为）。
PROJECT_AUTO = "auto"
_NON_KB_ID = re.compile(r"[^a-z0-9._-]")


def valid_project(value: str) -> bool:
    """`auto` 或合法知识库 id；其余一律拒绝（这个值会直接变成目录名）。"""
    return value == PROJECT_AUTO or KB_ID_RE.fullmatch(value) is not None


def sanitize_kb_id(value: str) -> str:
    """把任意串白名单化成目录名；老批次没有 project、source_id 不合规时兜底。"""
    cleaned = _NON_KB_ID.sub("-", value.strip().lower())[:64].lstrip("._-")
    return cleaned or "unknown"


def resolve_project(project: object, source_id: str) -> str:
    """worker 落库用哪个知识库：采集端指定优先，`auto`/缺失/非法回退 source_id。"""
    value = project.strip() if isinstance(project, str) else ""
    if value and value != PROJECT_AUTO and KB_ID_RE.fullmatch(value):
        return value
    return sanitize_kb_id(source_id)


class Kind(StrEnum):
    ENTITY = "entity"
    FACT = "fact"
    DECISION = "decision"
    PROCEDURE = "procedure"
    PITFALL = "pitfall"
    PREFERENCE = "preference"
    EVENT = "event"
    QUESTION = "question"


class EntityKind(StrEnum):
    SERVICE = "service"
    COMPONENT = "component"
    CONCEPT = "concept"
    TOOL = "tool"
    PERSON = "person"
    TEAM = "team"
    PROJECT = "project"
    EXTERNAL_SYSTEM = "external_system"
    CONFIG = "config"
    OTHER = "other"


class Predicate(StrEnum):
    PART_OF = "part_of"
    DEPENDS_ON = "depends_on"
    EXPOSES = "exposes"
    RUNS_ON = "runs_on"
    ABOUT = "about"
    RESOLVED_BY = "resolved_by"
    SUPERSEDES = "supersedes"
    CONTRADICTS = "contradicts"
    EVIDENCED_BY = "evidenced_by"
    RELATED_TO = "related_to"


class Tier(StrEnum):
    CANDIDATE = "candidate"
    CANONICAL = "canonical"
    DEPRECATED = "deprecated"


class QuestionStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"


class SourceKind(StrEnum):
    SESSION = "session"
    WIKI = "wiki"
    UPLOAD = "upload"
    MANUAL = "manual"


class SourceRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: SourceKind
    ref: str
    device: str | None = None
    captured_at: datetime | None = None


class NodeFrontmatter(BaseModel):
    """markdown 真源的 frontmatter。"""

    model_config = ConfigDict(extra="forbid")

    id: str
    kind: Kind
    entity_kind: EntityKind | None = None
    title: str
    tier: Tier = Tier.CANDIDATE
    confidence: float | None = Field(default=None, ge=0, le=1)
    project: str
    tags: list[str] = Field(default_factory=list)
    source: list[SourceRef] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    supersedes: list[str] = Field(default_factory=list)
    superseded_by: str | None = None
    occurred_at: datetime | None = None
    decided_at: datetime | None = None
    status: QuestionStatus | None = None

    @model_validator(mode="after")
    def check_kind_requirements(self) -> NodeFrontmatter:
        if self.kind is Kind.ENTITY and self.entity_kind is None:
            raise ValueError("kind=entity 时必须提供 entity_kind")
        if self.kind is Kind.QUESTION and self.status is None:
            raise ValueError("kind=question 时必须提供 status")
        if self.tier is Tier.DEPRECATED and not self.superseded_by:
            raise ValueError("tier=deprecated 时必须提供 superseded_by")
        return self


class Edge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str
    predicate: Predicate
    target: str
    source_doc: str | None = None


class SourceEntry(BaseModel):
    """`sources.json` 中的单个源。"""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9-]+$")
    name: str
    type: str = Field(pattern=r"^(sessions|wiki|docs)$")
    path: str
    file_glob: str | None = None
    enabled: bool = True
    project: str = "auto"
    exclude: list[str] = Field(default_factory=list)
    scan_interval_sec: int | None = Field(default=None, gt=0)

    @field_validator("project")
    @classmethod
    def check_project(cls, value: str) -> str:
        # 桌面端写 sources.json 时就该拦住拼错的库名，别等到云端 400 才发现。
        if not valid_project(value):
            raise ValueError("project 必须是 auto 或知识库 id（小写字母/数字/./_/-，≤64 位）")
        return value


class CollectorConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    scan_interval_sec: int = Field(default=300, gt=0)
    max_batch_bytes: int = Field(default=8 * 1024 * 1024, gt=0)
    quiet_hours: list[str] = Field(default_factory=list)


class SourcesConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = 1
    device_id: str
    collector: CollectorConfig = Field(default_factory=CollectorConfig)
    sources: list[SourceEntry] = Field(default_factory=list)


class Cursor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    files: int = 0
    bytes: int = 0
    last_at: datetime | None = None


class FileCursor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    offset: int = Field(ge=0)
    size: int = Field(ge=0)
    mtime: datetime


class BatchFile(BaseModel):
    """一次推送中的单文件增量片段。"""

    model_config = ConfigDict(extra="forbid")

    path: str
    from_offset: int = Field(ge=0)
    to_offset: int = Field(ge=0)
    mtime: datetime
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    content: str

    @model_validator(mode="after")
    def check_offsets(self) -> BatchFile:
        if self.to_offset < self.from_offset:
            raise ValueError("to_offset 不得小于 from_offset")
        return self


class IngestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batch_id: str
    device_id: str
    source_id: str
    source_type: str = Field(pattern=r"^(sessions|wiki|docs)$")
    project: str = "auto"
    source_rev: int = Field(default=0, ge=0)
    cursor_before: Cursor = Field(default_factory=Cursor)
    cursor_after: Cursor = Field(default_factory=Cursor)
    files: list[BatchFile] = Field(default_factory=list)


class IngestResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batch_id: str
    replayed: bool = False
    accepted: int = 0
    duplicates: int = 0
    skipped: list[str] = Field(default_factory=list)
    cursor: Cursor = Field(default_factory=Cursor)
    queued: bool = True


class ErrorCode(IntEnum):
    """业务码；与 HTTP 状态码无关。"""

    OK = 0
    TOKEN_INVALID = 1001
    DEVICE_REVOKED = 1002
    BAD_REQUEST = 1003
    CURSOR_CONFLICT = 1004
    BATCH_TOO_LARGE = 1005
    UNPARSABLE = 1006
    RATE_LIMITED = 1007
    QUEUE_BACKPRESSURE = 1008
    SCOPE_DENIED = 1009
    KB_CONFLICT = 1010
    KB_NOT_FOUND = 1011
    KB_INVALID = 1012
    KB_QUEUE_FULL = 1013
    INTERNAL = 2001


class ErrorBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: ErrorCode
    message: str
    data: dict[str, object] = Field(default_factory=dict)
