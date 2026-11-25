"""Alembic 基线迁移与模型的一致性契约（规格 §4）。

做法：在独立 schema 内跑 Alembic `upgrade head`，再用 `compare_metadata` 断言
「迁移建出的结构与 `Base.metadata` 零差异」——模型与迁移任何一侧漏改都会失败，
而不是等到生产上才发现漂移。
"""

from __future__ import annotations

import io
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import Connection

from memhub.kb.models import Base

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"
KB_TABLES = {
    "kb_projects",
    "kb_nodes",
    "kb_edges",
    "kb_node_revisions",
    "kb_archives",
    "kb_write_audit",
    "kb_mcp_trace",
}


def _sync_url(dsn: str) -> str:
    """Alembic 的同步路径用 psycopg 3 同步方言。"""
    for prefix in ("postgresql://", "postgres://"):
        if dsn.startswith(prefix):
            return "postgresql+psycopg://" + dsn[len(prefix) :]
    return dsn


@pytest.fixture
def migrated(kb_schema: str, test_dsn: str) -> Iterator[Connection]:
    """在测试 schema 内跑 `upgrade head`，产出带该 search_path 的连接。"""
    dsn = _sync_url(test_dsn)
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", dsn)

    engine = create_engine(dsn, connect_args={"options": f"-csearch_path={kb_schema}"})
    try:
        with engine.connect() as conn:
            cfg.attributes["connection"] = conn
            command.upgrade(cfg, "head")
            yield conn
    finally:
        engine.dispose()


def test_alembic_baseline_matches_models(migrated: Connection) -> None:
    """迁移建出的结构必须与 ORM 模型完全一致（索引、约束、默认值都算）。"""
    diff = compare_metadata(MigrationContext.configure(migrated), Base.metadata)
    assert diff == []


def test_version_table_and_kb_tables_only(migrated: Connection) -> None:
    """两套版本表共存（ADR-0013 §4）：知识表迁移只写 `alembic_version`。"""
    tables = set(inspect(migrated).get_table_names())
    assert "alembic_version" in tables
    assert "schema_migrations" not in tables
    assert KB_TABLES <= tables


def test_downgrade_removes_kb_tables(migrated: Connection) -> None:
    """空库演练用的 `downgrade base` 必须干净（生产回滚仍以 pg_dump 为准）。"""
    cfg = Config(str(ALEMBIC_INI))
    cfg.attributes["connection"] = migrated
    command.downgrade(cfg, "base")
    remaining = set(inspect(migrated).get_table_names()) - {"alembic_version"}
    assert remaining == set()


def test_version_table_is_qualified_with_kb_schema() -> None:
    """生产路径（未注入连接）版本表固定落 `kb`，不靠 search_path 兜底（ADR-0013 §6）。"""
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", "postgresql+psycopg://kb@127.0.0.1:1/memhub_prod")
    buffer = io.StringIO()
    cfg.output_buffer = buffer
    command.upgrade(cfg, "head", sql=True)
    sql = buffer.getvalue()
    assert "kb.alembic_version" in sql
    assert "public.alembic_version" not in sql
