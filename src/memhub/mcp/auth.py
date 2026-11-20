"""HTTP 只读凭据：仅载入摘要，不从浏览器或采集请求获取权限。"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, field_validator

from memhub.contract.models import KB_ID_PATTERN

_TOKEN = re.compile(r"[A-Za-z0-9_-]{43,128}")
Project = Annotated[str, Field(pattern=KB_ID_PATTERN)]


class Grant(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$", repr=False)]
    scope: Literal["mcp:read"]
    expires_at: datetime
    projects: Annotated[frozenset[Project], Field(min_length=1, max_length=128)]

    @field_validator("expires_at")
    @classmethod
    def utc_only(cls, value: datetime) -> datetime:
        if value.utcoffset() != timedelta(0):
            raise ValueError("必须使用 UTC 有效期")
        return value


_GRANTS = TypeAdapter(Annotated[list[Grant], Field(max_length=128)])


def load_grants(raw: str) -> dict[str, Grant]:
    if not raw:
        return {}
    try:
        grants = _GRANTS.validate_json(raw)
    except ValidationError:
        # 不向启动日志暴露任何配置输入。
        raise ValueError("MEMHUB_MCP_GRANTS 配置无效") from None
    result = {grant.sha256: grant for grant in grants}
    if len(result) != len(grants):
        raise ValueError("MEMHUB_MCP_GRANTS 存在重复摘要")
    return result


def authorized_projects(grants: dict[str, Grant], authorization: str) -> frozenset[str] | None:
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not _TOKEN.fullmatch(token):
        return None
    grant = grants.get(hashlib.sha256(token.encode("ascii")).hexdigest())
    if grant is None or grant.expires_at <= datetime.now(UTC):
        return None
    return grant.projects
