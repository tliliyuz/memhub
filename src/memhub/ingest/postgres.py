"""运行态存储的 PostgreSQL 实现（云上共享实例，独立 database）。

只存「推到哪儿了」这类运行状态；知识与原始增量都不进这里（见 `store.py` 模块注释）。
连接参数由 `MEMHUB_DB_URL` 提供，示例：

    postgresql://memhub_app@127.0.0.1:5432/memhub_prod

并发语义：
- 同一 `(device_id, batch_id)` 用事务级 advisory lock 串行化，保证并发重放只应用一次；
- 同一 `(device_id, source_id)` 先用 `INSERT ... ON CONFLICT DO NOTHING` 建行，再 `FOR UPDATE`
  锁行，游标推进因此是串行的，不会出现两个请求各写一半；
- 幂等窗口 24 小时，窗口外同 batch_id 视为新批次（契约 0.3），内容 `sha256` 兜底去重。
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from memhub.contract import Cursor, FileCursor, IngestRequest, IngestResult
from memhub.ingest.migrations import ensure_schema
from memhub.ingest.store import CursorConflict

REPLAY_WINDOW = timedelta(hours=24)


def _schema_configurer(schema: str) -> Callable[[Connection[dict[str, Any]]], None]:
    """每根新连接都设 search_path；schema 名来自配置，不拼接 SQL 字符串。"""

    def configure(conn: Connection[dict[str, Any]]) -> None:
        conn.execute("SELECT set_config('search_path', %s, false)", (schema,))
        # configure 不是业务事务的一部分：不提交会话停在 INTRANS，池会把连接整个丢弃。
        conn.commit()

    return configure


class PostgresStore:
    """`StateStore` 的生产实现。线程安全，连接由池管理。

    `schema` 只给隔离场景用（测试、联调各占一个 schema）；生产不传，落在库的默认 schema。
    """

    def __init__(
        self,
        dsn: str,
        *,
        min_size: int = 1,
        max_size: int = 5,
        schema: str | None = None,
    ) -> None:
        self.pool: ConnectionPool[Connection[dict[str, Any]]] = ConnectionPool(
            dsn,
            min_size=min_size,
            max_size=max_size,
            kwargs={"row_factory": dict_row, "autocommit": False},
            configure=_schema_configurer(schema) if schema else None,
            open=True,
        )

    def close(self) -> None:
        self.pool.close()

    def migrate(self) -> list[str]:
        """建表/补迁移；返回本次应用的版本。启动时调用一次。"""
        with self.pool.connection() as conn:
            return ensure_schema(conn)

    # -- devices ---------------------------------------------------------
    def register_device(self, device_id: str, *, name: str = "", platform: str = "") -> None:
        with self.pool.connection() as conn, conn.transaction():
            conn.execute(
                """
                INSERT INTO devices (device_id, name, platform)
                VALUES (%s, %s, %s)
                ON CONFLICT (device_id) DO UPDATE
                    SET name = EXCLUDED.name,
                        platform = EXCLUDED.platform,
                        last_seen_at = now(),
                        revoked_at = NULL
                """,
                (device_id, name, platform),
            )

    def is_registered(self, device_id: str) -> bool:
        with self.pool.connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM devices WHERE device_id = %s AND revoked_at IS NULL",
                (device_id,),
            ).fetchone()
        return row is not None

    # -- cursors ---------------------------------------------------------
    def get_cursor(self, device_id: str, source_id: str) -> tuple[int, list[FileCursor]]:
        with self.pool.connection() as conn:
            source = conn.execute(
                "SELECT source_rev FROM sources WHERE device_id = %s AND source_id = %s",
                (device_id, source_id),
            ).fetchone()
            rows = conn.execute(
                """
                SELECT path, "offset", size, mtime
                FROM file_cursors
                WHERE device_id = %s AND source_id = %s
                ORDER BY path
                """,
                (device_id, source_id),
            ).fetchall()
        files = [
            FileCursor(path=row["path"], offset=row["offset"], size=row["size"], mtime=row["mtime"])
            for row in rows
        ]
        return (int(source["source_rev"]) if source else 0), files

    def cursor_summary(self, device_id: str, source_id: str) -> Cursor:
        with self.pool.connection() as conn:
            return self._cursor_summary(conn, device_id, source_id)

    @staticmethod
    def _cursor_summary(conn: Connection[dict[str, Any]], device_id: str, source_id: str) -> Cursor:
        row = conn.execute(
            """
            SELECT count(*) AS files, coalesce(sum("offset"), 0) AS bytes
            FROM file_cursors
            WHERE device_id = %s AND source_id = %s
            """,
            (device_id, source_id),
        ).fetchone()
        source = conn.execute(
            "SELECT last_at FROM sources WHERE device_id = %s AND source_id = %s",
            (device_id, source_id),
        ).fetchone()
        return Cursor(
            files=int(row["files"]) if row else 0,
            bytes=int(row["bytes"]) if row else 0,
            last_at=source["last_at"] if source else None,
        )

    # -- ingest ----------------------------------------------------------
    def apply(self, request: IngestRequest) -> IngestResult:
        now = datetime.now(UTC)
        with self.pool.connection() as conn, conn.transaction():
            conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"{request.device_id}:{request.batch_id}",),
            )
            previous = conn.execute(
                "SELECT received_at, result FROM batches WHERE device_id = %s AND batch_id = %s",
                (request.device_id, request.batch_id),
            ).fetchone()
            if previous is not None and now - previous["received_at"] < REPLAY_WINDOW:
                result = IngestResult.model_validate(previous["result"])
                return result.model_copy(update={"replayed": True})

            conn.execute(
                """
                INSERT INTO sources (device_id, source_id)
                VALUES (%s, %s)
                ON CONFLICT (device_id, source_id) DO NOTHING
                """,
                (request.device_id, request.source_id),
            )
            source = conn.execute(
                """
                SELECT source_rev FROM sources
                WHERE device_id = %s AND source_id = %s
                FOR UPDATE
                """,
                (request.device_id, request.source_id),
            ).fetchone()
            current_rev = int(source["source_rev"]) if source else 0
            reset_allowed = request.source_rev > current_rev

            accepted = 0
            duplicates = 0
            for batch_file in request.files:
                known = None
                if not reset_allowed:
                    known = conn.execute(
                        """
                        SELECT "offset" FROM file_cursors
                        WHERE device_id = %s AND source_id = %s AND path = %s
                        """,
                        (request.device_id, request.source_id, batch_file.path),
                    ).fetchone()
                expected = int(known["offset"]) if known is not None else 0
                if batch_file.from_offset < expected:
                    raise CursorConflict(batch_file.path, expected)

                marker = conn.execute(
                    """
                    INSERT INTO seen_shas (source_id, sha256) VALUES (%s, %s)
                    ON CONFLICT DO NOTHING
                    RETURNING 1
                    """,
                    (request.source_id, batch_file.sha256),
                ).fetchone()
                if marker is None:
                    duplicates += 1
                else:
                    accepted += 1

                conn.execute(
                    """
                    INSERT INTO file_cursors (device_id, source_id, path, "offset", size, mtime)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (device_id, source_id, path) DO UPDATE
                        SET "offset" = EXCLUDED."offset",
                            size = EXCLUDED.size,
                            mtime = EXCLUDED.mtime
                    """,
                    (
                        request.device_id,
                        request.source_id,
                        batch_file.path,
                        # rescan（更高的 source_rev）时以客户端为准重置游标；
                        # 常规追加时 expected 已保证 to_offset >= known offset。
                        batch_file.to_offset
                        if reset_allowed
                        else max(expected, batch_file.to_offset),
                        batch_file.to_offset,
                        batch_file.mtime,
                    ),
                )

            conn.execute(
                """
                UPDATE sources
                SET source_rev = GREATEST(source_rev, %s), last_at = %s
                WHERE device_id = %s AND source_id = %s
                """,
                (request.source_rev, now, request.device_id, request.source_id),
            )
            result = IngestResult(
                batch_id=request.batch_id,
                accepted=accepted,
                duplicates=duplicates,
                cursor=self._cursor_summary(conn, request.device_id, request.source_id),
            )
            conn.execute(
                """
                INSERT INTO batches (device_id, batch_id, result) VALUES (%s, %s, %s)
                ON CONFLICT (device_id, batch_id) DO UPDATE
                    SET received_at = now(), result = EXCLUDED.result
                """,
                (request.device_id, request.batch_id, Jsonb(result.model_dump(mode="json"))),
            )
            return result

    # -- maintenance -----------------------------------------------------
    def purge_expired(self, *, keep: timedelta = timedelta(hours=25)) -> int:
        """删掉重放窗口外的批次记录（窗口 24h，留 1h 余量给边界）。"""
        with self.pool.connection() as conn, conn.transaction():
            cursor = conn.execute(
                "DELETE FROM batches WHERE received_at < now() - %s",
                (keep,),
            )
            return cursor.rowcount


__all__ = ["PostgresStore"]
