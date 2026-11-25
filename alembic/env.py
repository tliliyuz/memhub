"""Alembic 运行环境：只管理 `kb_*` 六张表（ADR-0013 §4，规格 §4）。

DSN 优先级：
1. `cfg.attributes["connection"]`：测试与 `memhub migrate-kb` 已有连接时直接复用
   （调用方负责把 search_path 固定到目标 schema）。
2. `sqlalchemy.url`：调用方显式注入。
3. 环境变量 `MEMHUB_KB_MIGRATE_DB_URL`：迁移角色的带外执行入口。

**不读 `MEMHUB_DB_URL`**：那是运行态角色，能碰运行态表与令牌摘要。
`target_metadata` 只含知识表，运行态 5 表仍由 `ingest/migrations.py` 的冻结基线管理。
"""

from __future__ import annotations

import os
from logging.config import fileConfig
from typing import Any, cast

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlalchemy.engine import Connection

from memhub.kb.models import Base
from memhub.kb.session import KB_SCHEMA, migrate_dsn, psycopg_dsn

config = context.config

_attrs: dict[str, Any] = config.attributes
if config.config_file_name is not None and _attrs.get("configure_logging", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _injected_schema(connection: Connection) -> str:
    """注入连接（测试隔离、`migrate-kb`）跟随其 `search_path` 当前 schema。

    生产路径不注入连接，固定 `KB_SCHEMA`，不靠 `search_path` 兜底（ADR-0013 §6）。
    """
    return connection.dialect.default_schema_name or KB_SCHEMA


def run_migrations_offline() -> None:
    """`--sql` 模式：只生成语句，不连库。"""
    url = psycopg_dsn(config.get_main_option("sqlalchemy.url") or migrate_dsn(environ=os.environ))
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table_schema=KB_SCHEMA,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = cast("Connection | None", config.attributes.get("connection"))
    if connection is not None:
        _run_with(connection, schema=_injected_schema(connection))
        return

    section = config.get_section(config.config_ini_section, {})
    if not section.get("sqlalchemy.url"):
        section["sqlalchemy.url"] = migrate_dsn(environ=os.environ)
    section["sqlalchemy.url"] = psycopg_dsn(section["sqlalchemy.url"])
    engine = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with engine.connect() as connection:
        _run_with(connection, schema=KB_SCHEMA)


def _run_with(connection: Connection, *, schema: str) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        version_table_schema=schema,
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
