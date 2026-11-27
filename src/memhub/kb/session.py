"""kb 运行时数据库连接（ADR-0013 §4/§6，ADR-0021，规格 §4）。

kb-api 用 **`MEMHUB_KB_DB_URL`**（角色 `memhub_kb_app`），ingest / worker / CLI 用
**`MEMHUB_KB_RT_DB_URL`**（角色 `memhub_rt_app`）；两者都指向只对 `kb_*` 有 DML 的受限角色，
**都不复用** `MEMHUB_DB_URL`（那是 `memhub_app`，能碰运行态表与令牌摘要）。拆分是为了让
连接预算与凭据轮换各自独立（ADR-0021）：三进程共用一个角色时，任意一方并发就会耗尽
`CONNECTION LIMIT`。两把键互不回退，缺失时直接抛 `KbDsnMissing`。

连接池按最小可行值：kb-api 与 ingest 2+2，worker/CLI 1+1；角色上限按
`Σ(容器数 × (pool + overflow)) + 余量` 核算（ADR-0021）。

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

from memhub.kb.pgstore import PgKnowledgeStore

KB_DSN_KEY = "MEMHUB_KB_DB_URL"
RT_DSN_KEY = "MEMHUB_KB_RT_DB_URL"
MIGRATE_DSN_KEY = "MEMHUB_KB_MIGRATE_DB_URL"
KB_SCHEMA = "kb"
RUNTIME_POOL_SIZE = 2
RUNTIME_MAX_OVERFLOW = 2
WORKER_POOL_SIZE = 1
WORKER_MAX_OVERFLOW = 1

_KB_HINT = (
    "kb-api / MCP 需要专用受限角色的连接串（只对 kb_* 有 DML）；"
    "不得复用 MEMHUB_DB_URL —— 那是运行态角色，能碰运行态表与令牌摘要"
)
_RT_HINT = (
    "ingest / worker / CLI 需要运行态知识角色的连接串（ADR-0021，与 kb-api 分开核算连接）；"
    f"缺 {RT_DSN_KEY} 时不回退 {KB_DSN_KEY}，否则会静默回到多进程共用一个角色的冲突状态"
)


class KbDsnMissing(RuntimeError):
    """没有可用的 kb 连接串；知识表没有内存/文件退路。"""


def kb_dsn(environ: Mapping[str, str] | None = None) -> str:
    """读取并校验 `MEMHUB_KB_DB_URL`（kb-api / MCP）；空值与缺失同样视为未配置。"""
    return _require_dsn(KB_DSN_KEY, environ, _KB_HINT)


def rt_dsn(environ: Mapping[str, str] | None = None) -> str:
    """读取并校验 `MEMHUB_KB_RT_DB_URL`（ingest / worker / CLI，ADR-0021）。"""
    return _require_dsn(RT_DSN_KEY, environ, _RT_HINT)


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


def psycopg_dsn(dsn: str) -> str:
    """`postgresql://` 换成 psycopg 3 方言；已带方言或未知格式原样返回。

    运行态（异步引擎）与迁移（Alembic 同步引擎）都用这一条：镜像里只有 psycopg 3，
    不归一化时 SQLAlchemy 会去找 psycopg2，在连库之前就以 ModuleNotFoundError 失败。
    """
    if "+" in dsn.split("://", 1)[0]:
        return dsn
    for prefix in ("postgresql://", "postgres://"):
        if dsn.startswith(prefix):
            return "postgresql+psycopg://" + dsn[len(prefix) :]
    return dsn


def connect_args_for(schema: str | None) -> dict[str, Any]:
    """`schema` 只给隔离场景用（测试/联调）；连接建立时就设好 search_path。"""
    return {"options": f"-csearch_path={schema}"} if schema else {}


def runtime_engine_kwargs(
    schema: str | None = KB_SCHEMA,
    *,
    pool_size: int = RUNTIME_POOL_SIZE,
    max_overflow: int = RUNTIME_MAX_OVERFLOW,
) -> dict[str, Any]:
    """运行时引擎的固定参数：最小池 + 预检 + search_path。"""
    return {
        "pool_size": pool_size,
        "max_overflow": max_overflow,
        "pool_pre_ping": True,
        "connect_args": connect_args_for(schema),
    }


def create_engine_from_env(
    *,
    dsn: str | None = None,
    schema: str | None = KB_SCHEMA,
    environ: Mapping[str, str] | None = None,
    pool_size: int = RUNTIME_POOL_SIZE,
    max_overflow: int = RUNTIME_MAX_OVERFLOW,
    key: str = KB_DSN_KEY,
) -> AsyncEngine:
    """建异步引擎；`dsn` 缺省时按 `key` 从环境读取，便于测试注入。

    `key` 决定缺省来源：kb-api 用 `MEMHUB_KB_DB_URL`，ingest / worker / CLI 用
    `MEMHUB_KB_RT_DB_URL`（ADR-0021）。`schema` 默认 `KB_SCHEMA`（生产专用 schema）；
    显式传 `None` 不设 search_path，传测试 schema 则用于隔离场景。
    """
    if dsn is None:
        dsn = rt_dsn(environ) if key == RT_DSN_KEY else kb_dsn(environ)
    return create_async_engine(
        psycopg_dsn(dsn),
        **runtime_engine_kwargs(schema, pool_size=pool_size, max_overflow=max_overflow),
    )


def create_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


def create_runtime_store(
    *,
    dsn: str | None = None,
    schema: str | None = KB_SCHEMA,
    environ: Mapping[str, str] | None = None,
) -> PgKnowledgeStore:
    """kb-api / MCP 的存储构造方式（`MEMHUB_KB_DB_URL`，ADR-0013 §6）。

    不提供文件存储退路；`KnowledgeStore` 只留给测试夹具、迁移工具与迁移源。
    """
    engine = create_engine_from_env(dsn=dsn, schema=schema, environ=environ)
    return PgKnowledgeStore(create_sessionmaker(engine), engine=engine)


def create_rt_store(
    *,
    dsn: str | None = None,
    schema: str | None = KB_SCHEMA,
    environ: Mapping[str, str] | None = None,
    pool_size: int = RUNTIME_POOL_SIZE,
    max_overflow: int = RUNTIME_MAX_OVERFLOW,
) -> PgKnowledgeStore:
    """ingest / worker / CLI 的存储构造方式（`MEMHUB_KB_RT_DB_URL`，ADR-0021）。

    池预算由调用方给：ingest 2+2，worker/CLI 传 `WORKER_POOL_SIZE` / `WORKER_MAX_OVERFLOW`。
    缺失新键直接失败，不回退主角色。
    """
    engine = create_engine_from_env(
        dsn=dsn,
        schema=schema,
        environ=environ,
        pool_size=pool_size,
        max_overflow=max_overflow,
        key=RT_DSN_KEY,
    )
    return PgKnowledgeStore(create_sessionmaker(engine), engine=engine)
