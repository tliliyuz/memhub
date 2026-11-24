"""kb 契约测试共用 PG 夹具：每个用例一个独立 schema（schema-per-test）。

规格 §9.1.4：`CREATE SCHEMA test_<uuid>` / `DROP SCHEMA CASCADE`，连接串取
`MEMHUB_TEST_DB_URL`（指向云端 `memhub_dev`，角色无 CREATEDB）。未设置时 skip，
但 skip **不计为通过**（规格 §8.10）：验收命令必须带上该变量。
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


def _sqlalchemy_url(dsn: str) -> str:
    """psycopg 的 `postgresql://` 转 SQLAlchemy 异步 dialect。"""
    return dsn.replace("postgresql://", "postgresql+psycopg://", 1)


@pytest_asyncio.fixture
async def kb_engine() -> AsyncIterator[AsyncEngine]:
    """search_path 固定在独立 schema 的异步引擎；用例结束整体删除该 schema。"""
    from sqlalchemy import text

    dsn = os.environ.get("MEMHUB_TEST_DB_URL", "")
    if not dsn:
        pytest.skip("MEMHUB_TEST_DB_URL 未设置；kb PG 契约未执行（不计为通过）")
    schema = f"test_{uuid.uuid4().hex[:12]}"
    engine = create_async_engine(
        _sqlalchemy_url(dsn),
        pool_size=1,
        max_overflow=1,
        connect_args={"options": f"-csearch_path={schema}"},
    )
    admin = create_async_engine(_sqlalchemy_url(dsn), isolation_level="AUTOCOMMIT")
    try:
        async with admin.connect() as conn:
            await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        yield engine
    finally:
        await engine.dispose()
        async with admin.connect() as conn:
            await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await admin.dispose()
