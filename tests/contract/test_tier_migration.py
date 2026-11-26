"""ADR-0014 存量迁移的验收测试（规格 docs/plans/tier-canonical-spec.md §4.4）。

做法与 `test_kb_migrations.py` 一致：独立 schema 跑 Alembic 到 `0002`，
插入存量 `candidate` 行，再 `upgrade head` 验证数据迁移与 `compare_metadata`。
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Connection

from memhub.kb.models import Base

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"

NOW = datetime(2026, 11, 25, tzinfo=UTC)
CANDIDATE_NODE = {
    "id": "demo/fact/legacy",
    "project": "demo",
    "kind": "fact",
    "title": "存量候选",
    "tier": "candidate",
    "body": "这是一段至少二十个字符的存量候选正文，用于迁移验收。",
    "source": [],
    "tags": [],
    "supersedes": [],
    "revision": "0123456789abcdef",
    "created_at": NOW,
    "updated_at": NOW,
}
CANONICAL_NODE = CANDIDATE_NODE | {
    "id": "demo/fact/alive",
    "tier": "canonical",
    "title": "已有正式",
}


def _sync_url(dsn: str) -> str:
    for prefix in ("postgresql://", "postgres://"):
        if dsn.startswith(prefix):
            return "postgresql+psycopg://" + dsn[len(prefix) :]
    return dsn


def _config(dsn: str) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", _sync_url(dsn))
    return cfg


@pytest.fixture
def conn(kb_schema: str, test_dsn: str) -> Iterator[Connection]:
    dsn = _sync_url(test_dsn)
    engine = create_engine(dsn, connect_args={"options": f"-csearch_path={kb_schema}"})
    cfg = _config(dsn)
    with engine.connect() as connection:
        cfg.attributes["connection"] = connection
        command.upgrade(cfg, "0002_kb_mcp_trace")
        yield connection
        command.downgrade(cfg, "base")
    engine.dispose()


def _insert_node(connection: Connection, row: dict) -> None:
    connection.execute(
        Base.metadata.tables["kb_nodes"].insert().values(**row)  # type: ignore[arg-type]
    )


def test_migration_promotes_candidates_and_records_revision(
    conn: Connection, test_dsn: str
) -> None:
    project = {
        "id": "demo",
        "name": "demo",
        "revision": "0123456789abcdef",
        "created_at": NOW,
        "updated_at": NOW,
    }
    conn.execute(Base.metadata.tables["kb_projects"].insert().values(**project))
    _insert_node(conn, CANDIDATE_NODE)
    _insert_node(conn, CANONICAL_NODE)
    conn.commit()

    cfg = _config(_sync_url(test_dsn))
    cfg.attributes["connection"] = conn
    command.upgrade(cfg, "head")

    nodes = Base.metadata.tables["kb_nodes"]
    row = conn.execute(
        select(nodes.c.tier, nodes.c.revision).where(nodes.c.id == "demo/fact/legacy")
    ).one()
    assert row.tier == "canonical"
    assert row.revision != "0123456789abcdef"

    revisions = Base.metadata.tables["kb_node_revisions"]
    history = conn.execute(
        select(revisions.c.actor, revisions.c.reason, revisions.c.before, revisions.c.after).where(
            revisions.c.node_id == "demo/fact/legacy"
        )
    ).fetchall()
    migrated = [item for item in history if item.reason == "ADR-0014"]
    assert len(migrated) == 1
    assert migrated[0].actor == "system"
    assert migrated[0].before["tier"] == "candidate"
    assert migrated[0].after["tier"] == "canonical"

    # 已是 canonical 的行不写迁移修订。
    other = conn.execute(
        select(revisions.c.reason).where(revisions.c.node_id == "demo/fact/alive")
    ).fetchall()
    assert all(reason != "ADR-0014" for (reason,) in other)

    # 列默认值同步进模型，结构零差异。
    diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []


def test_migration_is_idempotent_without_candidates(conn: Connection, test_dsn: str) -> None:
    project = {
        "id": "demo",
        "name": "demo",
        "revision": "0123456789abcdef",
        "created_at": NOW,
        "updated_at": NOW,
    }
    conn.execute(Base.metadata.tables["kb_projects"].insert().values(**project))
    _insert_node(conn, CANONICAL_NODE)
    conn.commit()

    cfg = _config(_sync_url(test_dsn))
    cfg.attributes["connection"] = conn
    command.upgrade(cfg, "head")
    revisions = Base.metadata.tables["kb_node_revisions"]
    count = len(
        conn.execute(select(revisions.c.reason).where(revisions.c.reason == "ADR-0014")).fetchall()
    )
    assert count == 0
