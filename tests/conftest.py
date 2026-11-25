"""测试级公共夹具。

- 事件循环：psycopg 异步实现不支持 Windows 默认的 ProactorEventLoop，本机跑 PG
  测试必须换成 SelectorEventLoop（生产/CI 在 Linux 上不受影响）。
- kb PG 夹具：每个用例一个独立 schema（schema-per-test，规格 §9.1.4），连接串取
  `MEMHUB_TEST_DB_URL`（指向云端 `memhub_dev`，角色无 CREATEDB）。未设置时 skip，
  但 skip **不计为通过**（规格 §8.10）：验收命令必须带上该变量。
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from collections.abc import AsyncIterator, Callable, Iterator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

if sys.platform == "win32":
    # 同步 `TestClient` 的 portal 走默认事件循环策略；不换掉 Proactor，
    # psycopg 异步连接在 kb-api 测试里直接报 InterfaceError。
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@pytest.fixture(scope="session")
def _asyncio_loop_factory() -> Callable[[], asyncio.AbstractEventLoop] | None:
    if sys.platform == "win32":
        return asyncio.SelectorEventLoop
    return None


def _sqlalchemy_url(dsn: str) -> str:
    """psycopg 的 `postgresql://` 转 SQLAlchemy 异步 dialect。"""
    return dsn.replace("postgresql://", "postgresql+psycopg://", 1)


async def _prepare_schema(dsn: str, schema: str) -> None:
    from memhub.kb.models import Base

    admin = create_async_engine(_sqlalchemy_url(dsn), isolation_level="AUTOCOMMIT")
    try:
        async with admin.connect() as conn:
            await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = create_async_engine(
            _sqlalchemy_url(dsn), connect_args={"options": f"-csearch_path={schema}"}
        )
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
        finally:
            await engine.dispose()
    finally:
        await admin.dispose()


async def _drop_schema(dsn: str, schema: str) -> None:
    admin = create_async_engine(_sqlalchemy_url(dsn), isolation_level="AUTOCOMMIT")
    try:
        async with admin.connect() as conn:
            await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
    finally:
        await admin.dispose()


@pytest.fixture
def test_dsn() -> str:
    """`MEMHUB_TEST_DB_URL`；未设置时 skip，且不计为通过（规格 §8.10）。"""
    dsn = os.environ.get("MEMHUB_TEST_DB_URL", "")
    if not dsn:
        pytest.skip("MEMHUB_TEST_DB_URL 未设置；kb PG 契约未执行（不计为通过）")
    return dsn


@pytest_asyncio.fixture
async def kb_schema(test_dsn: str) -> AsyncIterator[str]:
    """建一个空 schema 并返回名字；用例结束整体删除。"""
    schema = f"test_{uuid.uuid4().hex[:12]}"
    admin = create_async_engine(_sqlalchemy_url(test_dsn), isolation_level="AUTOCOMMIT")
    try:
        async with admin.connect() as conn:
            await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        yield schema
    finally:
        async with admin.connect() as conn:
            await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await admin.dispose()


@pytest_asyncio.fixture
async def kb_engine(kb_schema: str, test_dsn: str) -> AsyncIterator[AsyncEngine]:
    """search_path 固定在独立 schema 的异步引擎。"""
    engine = create_async_engine(
        _sqlalchemy_url(test_dsn),
        pool_size=1,
        max_overflow=1,
        connect_args={"options": f"-csearch_path={kb_schema}"},
    )
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
def kb_pg_schema(test_dsn: str) -> Iterator[str]:
    """同步用例用：建 schema 并建好 `kb_*` 表，交给 `create_app(schema=...)` 自管引擎。

    同步 `TestClient` 会在自己的 portal 事件循环里使用引擎，因此引擎必须由应用
    构造与释放，不能跨循环借用异步夹具的引擎。
    """
    schema = f"test_{uuid.uuid4().hex[:12]}"
    asyncio.run(_prepare_schema(test_dsn, schema))
    try:
        yield schema
    finally:
        asyncio.run(_drop_schema(test_dsn, schema))
