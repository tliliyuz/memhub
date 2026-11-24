"""kb 运行时数据库连接（ADR-0013 §4/§6，规格 §4）。

DSN 取 **`MEMHUB_KB_DB_URL`**，指向只对 `kb_*` 有 DML 的受限角色；**不复用**
`MEMHUB_DB_URL`（那是 `memhub_app`，能碰运行态表与令牌摘要）。缺失时直接抛
`KbDsnMissing` 而不是退回内存实现：知识没有进程内替身（ADR-0013 §10）。

连接池按最小可行值 2+2（ADR-0013 §6：生产预算核定前不得抬高）。

生产落 `memhub_prod`（ADR-0013 §6 裁决）：知识表放在专用 schema `kb`，默认
`search_path` 即指向它。这样即使角色被误配，也不会默认落到 `public` 的运行态表旁。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

KB_DSN_KEY = "MEMHUB_KB_DB_URL"
MIGRATE_DSN_KEY = "MEMHUB_KB_MIGRATE_DB_URL"
KB_SCHEMA = "kb"
RUNTIME_POOL_SIZE = 2
RUNTIME_MAX_OVERFLOW = 2


class KbDsnMissing(RuntimeError):
    """没有可用的 kb 连接串；知识表没有内存/文件退路。"""


def kb_dsn(environ: Mapping[str, str] | None = None) -> str:
    """读取并校验 `MEMHUB_KB_DB_URL`；空值与缺失同样视为未配置。"""
    return _require_dsn(
        KB_DSN_KEY,
        environ,
        "kb 需要专用受限角色的连接串（只对 kb_* 有 DML）；"
        "不得复用 MEMHUB_DB_URL —— 那是运行态角色，能碰运行态表与令牌摘要",
    )


def migrate_dsn(environ: Mapping[str, str] | None = None) -> str:
    """迁移（DDL）角色连接串；带外执行 Alembic，不在 kb 容器启动时跑。"""
    return _require_dsn(
        MIGRATE_DSN_KEY,
        environ,
        "Alembic 迁移需要 kb_* 的 DDL 权限；不得复用运行时角色或 MEMHUB_DB_URL",
    )


def _require_dsn(key: str, environ: Mapping[str, str] | None, hint: str) -> str:
    source = environ if environ is not None else _environ()
    dsn = (source.get(key) or "").strip()
    if not dsn:
        raise KbDsnMissing(f"缺少 {key}：{hint}")
    return dsn


def _environ() -> Mapping[str, str]:
    import os

    return os.environ


def _async_dsn(dsn: str) -> str:
    """`postgresql://` 换成 SQLAlchemy 异步方言；已带方言或未知格式原样返回。"""
    if "+" in dsn.split("://", 1)[0]:
        return dsn
    for prefix in ("postgresql://", "postgres://"):
        if dsn.startswith(prefix):
            return "postgresql+psycopg://" + dsn[len(prefix) :]
    return dsn


def connect_args_for(schema: str | None) -> dict[str, Any]:
    """`schema` 只给隔离场景用（测试/联调）；连接建立时就设好 search_path。"""
    return {"options": f"-csearch_path={schema}"} if schema else {}


def runtime_engine_kwargs(schema: str | None = KB_SCHEMA) -> dict[str, Any]:
    """运行时引擎的固定参数：最小池 + 预检 + search_path。"""
    return {
        "pool_size": RUNTIME_POOL_SIZE,
        "max_overflow": RUNTIME_MAX_OVERFLOW,
        "pool_pre_ping": True,
        "connect_args": connect_args_for(schema),
    }


def create_engine_from_env(
    *,
    dsn: str | None = None,
    schema: str | None = KB_SCHEMA,
    environ: Mapping[str, str] | None = None,
) -> AsyncEngine:
    """建异步引擎；`dsn` 缺省时从环境读取，便于测试注入。

    `schema` 默认 `KB_SCHEMA`（生产专用 schema）；显式传 `None` 不设 search_path，
    传测试 schema 则用于隔离场景。
    """
    return create_async_engine(_async_dsn(dsn or kb_dsn(environ)), **runtime_engine_kwargs(schema))


def create_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
