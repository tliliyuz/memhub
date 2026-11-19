"""迁移幂等性：dict 行与 tuple 行都必须成立。

回归背景：连接池配置了 `row_factory=dict_row`，而 `ensure_schema` 用 `row[0]` 读版本，
空库首次迁移不读行所以永远正常，第二次（重启 / timer / provision）立刻 KeyError。
PG 测试在本机默认跳过，所以这里用假连接把两种行工厂都钉住。
"""

from __future__ import annotations

from typing import Any

from memhub.ingest.migrations import MIGRATIONS, ensure_schema


class FakeConn:
    def __init__(self, *, dict_rows: bool) -> None:
        self.dict_rows = dict_rows
        self.applied: list[str] = []
        self.ddl: list[str] = []
        self._rows: list[Any] = []

    def _row(self, version: str) -> Any:
        return {"version": version} if self.dict_rows else (version,)

    def execute(self, sql: str, params: tuple[object, ...] | None = None) -> FakeConn:
        stripped = " ".join(sql.split())
        if stripped.startswith("CREATE TABLE IF NOT EXISTS schema_migrations"):
            return self
        if stripped.startswith("SELECT version FROM schema_migrations"):
            self._rows = [self._row(version) for version in self.applied]
            return self
        if stripped.startswith("INSERT INTO schema_migrations"):
            assert params is not None
            self.applied.append(str(params[0]))
            return self
        self.ddl.append(stripped)
        return self

    def fetchall(self) -> list[Any]:
        return self._rows

    def commit(self) -> None:
        return None


def _statement_count() -> int:
    return sum(len(statements) for _, statements in MIGRATIONS)


def test_second_migration_is_a_noop_with_dict_rows() -> None:
    conn = FakeConn(dict_rows=True)
    assert ensure_schema(conn) == [version for version, _ in MIGRATIONS]
    assert ensure_schema(conn) == [], "第二次必须是空操作，不能抛 KeyError"
    assert len(conn.ddl) == _statement_count()


def test_second_migration_is_a_noop_with_tuple_rows() -> None:
    conn = FakeConn(dict_rows=False)
    assert ensure_schema(conn) == [version for version, _ in MIGRATIONS]
    assert ensure_schema(conn) == []
    assert len(conn.ddl) == _statement_count()
