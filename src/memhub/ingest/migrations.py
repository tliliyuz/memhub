"""运行态库的表结构与迁移（云上共享 PG 实例里的独立 database）。

迁移是**前向追加**的：每条只增不改，版本号写进 `schema_migrations`；没有回滚脚本。
理由：这张库只存运行态（设备/游标/批次幂等），丢了可以从设备重推重建，
回滚带来的复杂度不值得——知识真源在 git，不在这里（ADR-0002）。

语句拆成列表逐条执行，不用 `execute()` 塞多语句：psycopg 的扩展协议不接受多语句，
拆开也让「哪条 DDL 失败」在日志里直接可读。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from psycopg import Connection

MIGRATIONS: list[tuple[str, Sequence[str]]] = [
    (
        "0001_state",
        (
            """
            CREATE TABLE IF NOT EXISTS devices (
                device_id   text PRIMARY KEY,
                name        text NOT NULL DEFAULT '',
                platform    text NOT NULL DEFAULT '',
                created_at  timestamptz NOT NULL DEFAULT now(),
                last_seen_at timestamptz,
                revoked_at  timestamptz
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS sources (
                device_id   text NOT NULL REFERENCES devices (device_id) ON DELETE CASCADE,
                source_id   text NOT NULL,
                source_rev  integer NOT NULL DEFAULT 0,
                last_at     timestamptz,
                PRIMARY KEY (device_id, source_id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS file_cursors (
                device_id   text NOT NULL,
                source_id   text NOT NULL,
                path        text NOT NULL,
                "offset"    bigint NOT NULL CHECK ("offset" >= 0),
                size        bigint NOT NULL CHECK (size >= 0),
                mtime       timestamptz NOT NULL,
                PRIMARY KEY (device_id, source_id, path),
                FOREIGN KEY (device_id, source_id)
                    REFERENCES sources (device_id, source_id) ON DELETE CASCADE
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS batches (
                device_id   text NOT NULL,
                batch_id    text NOT NULL,
                received_at timestamptz NOT NULL DEFAULT now(),
                result      jsonb NOT NULL,
                PRIMARY KEY (device_id, batch_id)
            )
            """,
            "CREATE INDEX IF NOT EXISTS batches_received_at_idx ON batches (received_at)",
            """
            CREATE TABLE IF NOT EXISTS seen_shas (
                source_id     text NOT NULL,
                sha256        text NOT NULL,
                first_seen_at timestamptz NOT NULL DEFAULT now(),
                PRIMARY KEY (source_id, sha256)
            )
            """,
        ),
    ),
]


def ensure_schema(conn: Connection[Any]) -> list[str]:
    """幂等建表；返回本次实际应用的迁移版本。"""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version    text PRIMARY KEY,
            applied_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    applied = {
        str(row[0]) for row in conn.execute("SELECT version FROM schema_migrations").fetchall()
    }
    newly = [version for version, _ in MIGRATIONS if version not in applied]
    for version, statements in MIGRATIONS:
        if version in applied:
            continue
        for statement in statements:
            conn.execute(statement)
        conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (version,))
    conn.commit()
    return newly


__all__ = ["MIGRATIONS", "ensure_schema"]
