"""kb 运行时连接的验收条件（规格 §4：DSN 分角色、不复用 `MEMHUB_DB_URL`）。"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from memhub.kb.session import (
    KB_DSN_KEY,
    KB_SCHEMA,
    RUNTIME_MAX_OVERFLOW,
    RUNTIME_POOL_SIZE,
    KbDsnMissing,
    connect_args_for,
    create_engine_from_env,
    create_sessionmaker,
    kb_dsn,
    runtime_engine_kwargs,
)


def test_kb_dsn_requires_its_own_key() -> None:
    """只有 `MEMHUB_DB_URL` 时必须报错：那是运行态角色，不能拿来写知识表。"""
    with pytest.raises(KbDsnMissing) as err:
        kb_dsn(environ={"MEMHUB_DB_URL": "postgresql://memhub_app@h:5432/memhub_prod"})
    message = str(err.value)
    assert KB_DSN_KEY in message
    assert "MEMHUB_DB_URL" in message


def test_kb_dsn_reads_env_key() -> None:
    dsn = "postgresql://memhub_kb_app@10.0.0.1:5432/memhub_prod?sslmode=require"
    assert kb_dsn(environ={KB_DSN_KEY: dsn}) == dsn


def test_kb_dsn_rejects_blank_value() -> None:
    with pytest.raises(KbDsnMissing):
        kb_dsn(environ={KB_DSN_KEY: "   "})


def test_engine_normalizes_dsn_to_async_psycopg() -> None:
    engine = create_engine_from_env(dsn="postgresql://kb@127.0.0.1:5432/memhub_prod")
    assert engine.url.drivername == "postgresql+psycopg"

    already = create_engine_from_env(dsn="postgresql+psycopg://kb@127.0.0.1:5432/memhub_prod")
    assert already.url.drivername == "postgresql+psycopg"


def test_runtime_pool_budget_is_minimal() -> None:
    """ADR-0013 §6：生产预算未定前按最小可行 2+2 配置。"""
    assert (RUNTIME_POOL_SIZE, RUNTIME_MAX_OVERFLOW) == (2, 2)
    engine = create_engine_from_env(dsn="postgresql://kb@127.0.0.1:5432/memhub_prod")
    assert engine.pool.size() == RUNTIME_POOL_SIZE
    assert engine.pool._max_overflow == RUNTIME_MAX_OVERFLOW


def test_connect_args_pin_search_path_only_when_schema_given() -> None:
    assert connect_args_for(None) == {}
    assert connect_args_for("test_abc123") == {"options": "-csearch_path=test_abc123"}


def test_default_schema_is_the_dedicated_kb_schema() -> None:
    """生产落 `memhub_prod`（ADR-0013 §6 裁决）：知识表在专用 schema，不与 public 混放。"""
    assert KB_SCHEMA == "kb"
    assert runtime_engine_kwargs()["connect_args"] == {"options": "-csearch_path=kb"}
    assert runtime_engine_kwargs(schema=None)["connect_args"] == {}


def test_sessionmaker_does_not_expire_on_commit(engine: AsyncEngine) -> None:
    """对象提交后仍可读，避免每次读回都要重新查库。"""
    assert create_sessionmaker(engine).kw["expire_on_commit"] is False


@pytest.fixture
def engine() -> AsyncEngine:
    return create_engine_from_env(dsn="postgresql://kb@127.0.0.1:5432/memhub_prod")
