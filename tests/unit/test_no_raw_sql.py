"""门禁脚本自测：命中裸 SQL / 放行 ORM 构造。"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_no_raw_sql.py"


@pytest.fixture(scope="module")
def checker() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_no_raw_sql", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_text_call_is_flagged(checker: ModuleType) -> None:
    source = "from sqlalchemy import text\n\n\ndef f(conn):\n    conn.execute(text('SELECT 1'))\n"
    messages = [message for _, message in checker.find_violations(source, "x.py")]
    assert messages and "sqlalchemy.text()" in messages[0]


def test_sql_string_execute_is_flagged(checker: ModuleType) -> None:
    source = "async def f(session):\n    await session.execute('DELETE FROM batches')\n"
    assert checker.find_violations(source, "x.py")


def test_fstring_execute_is_flagged(checker: ModuleType) -> None:
    source = 'def f(conn, table):\n    conn.exec_driver_sql(f"SELECT * FROM {table}")\n'
    assert checker.find_violations(source, "x.py")


def test_orm_expression_passes(checker: ModuleType) -> None:
    source = (
        "from sqlalchemy import select\n\n\n"
        "async def f(session):\n"
        "    return await session.execute(select(1))\n"
    )
    assert checker.find_violations(source, "x.py") == []


def test_alembic_dir_is_scanned(checker: ModuleType, tmp_path: Path) -> None:
    """ADR-0013 的知识表迁移在 alembic/ 下，门禁必须覆盖它，否则「不放宽」形同虚设。"""
    (tmp_path / "src").mkdir()
    versions = tmp_path / "alembic" / "versions"
    versions.mkdir(parents=True)
    (versions / "0001_kb.py").write_text(
        "from sqlalchemy import text\n\n\ndef upgrade():\n    return text('CREATE TABLE kb')\n",
        encoding="utf-8",
    )
    assert checker.main(["--root", str(tmp_path)]) == 1


def test_src_and_alembic_both_clean_passes(checker: ModuleType, tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    versions = tmp_path / "alembic" / "versions"
    versions.mkdir(parents=True)
    (versions / "0001_kb.py").write_text(
        "from alembic import op\n\n\ndef upgrade():\n    op.create_table('kb_nodes')\n",
        encoding="utf-8",
    )
    assert checker.main(["--root", str(tmp_path)]) == 0
