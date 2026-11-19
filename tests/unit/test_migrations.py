"""迁移幂等性：DDL 走冻结基线，`schema_migrations` 保证只应用一次。

回归背景：旧实现从连接行里取版本，dict/tuple 两种行工厂曾导致第二次迁移 KeyError。
现在 `ensure_schema` 只依赖执行器接口，用假连接把「第二次必须是空操作」钉住。
"""

from __future__ import annotations

from typing import Any

from memhub.ingest.migrations import MIGRATIONS, ensure_schema


class FakeResult:
    def __init__(self, rows: list[Any] | None = None) -> None:
        self._rows = rows or []

    def scalars(self) -> list[Any]:
        return self._rows


class FakeConn:
    def __init__(self) -> None:
        self.applied: list[str] = []
        self.ddl: list[str] = []

    def exec_driver_sql(self, sql: str, params: tuple[object, ...] | None = None) -> FakeResult:
        stripped = " ".join(sql.split())
        if stripped.startswith("CREATE TABLE IF NOT EXISTS schema_migrations"):
            return FakeResult()
        if stripped.startswith("SELECT version FROM schema_migrations"):
            return FakeResult(list(self.applied))
        if stripped.startswith("INSERT INTO schema_migrations"):
            assert params is not None
            self.applied.append(str(params[0]))
            return FakeResult()
        self.ddl.append(stripped)
        return FakeResult()


def _statement_count() -> int:
    return sum(len(statements) for _, statements in MIGRATIONS)


def test_second_migration_is_a_noop() -> None:
    conn = FakeConn()
    assert ensure_schema(conn) == [version for version, _ in MIGRATIONS]
    assert ensure_schema(conn) == [], "第二次必须是空操作，不能重复执行 DDL"
    assert len(conn.ddl) == _statement_count()
