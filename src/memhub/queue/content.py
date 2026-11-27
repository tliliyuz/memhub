"""原始增量正文存储（ADR-0020）。

生产实现是百度云 ClickHouse 的 `memhub_raw.raw_sessions`：ingest 收到批次后把正文直接
写过去，worker 按 `(project, sha256)` 取回。表用 ReplacingMergeTree 按
`(project, sha256)` 去重，180 天 TTL；账号只有 SELECT / INSERT，清理只能走 TTL
或运维本机账号。

链路约束（实测）：
- 只有 nginx 8443 TLS 入口，凭据经 `X-ClickHouse-User` / `X-ClickHouse-Key` 头传递；
- 腾讯云 → 百度云约 0.6–0.8 MB/s，回读约 0.15 MB/s 且并发不提升，
  因此写用 `Content-Encoding: gzip`，读用 `enable_http_compression=1`；
- 不要加 `decompress=1`（服务端会按未压缩解析压缩体，报 `UNKNOWN_CODEC 115`）。

`LocalContentStore` 是 dev / 测试实现：落在 `<DATA_DIR>/content_store/<project>/<sha[:2]>/<sha>.json`。
它只用于单机联调，不是生产真源；进程之间共享仍需要同一个 DATA_DIR。

容灾方向（CH → 腾讯云/COS 反向导出）尚未裁决，本次不实现；在反向导出落地前
ClickHouse 是原文的单点存储（ADR-0020 §7）。
"""

from __future__ import annotations

import gzip
import json
import os
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, cast

import httpx
from anyio import Path as AsyncPath

CH_DATABASE = "memhub_raw"
CH_TABLE = "raw_sessions"


class ContentUnavailable(RuntimeError):
    """正文存储不可用（网络/TLS/服务端错误）；调用方按「临时不可用」推迟，不算文件失败。"""


@dataclass(frozen=True)
class ContentEntry:
    """写入正文存储的一行；字段与 `raw_sessions` 列一一对应。"""

    project: str
    sha256: str
    device_id: str
    source_id: str
    source_type: str
    batch_id: str
    path: str
    from_offset: int
    to_offset: int
    mtime: datetime
    producer: str
    content: str


class RawContentStore(Protocol):
    """正文存储契约：写入、按目标查已存在、按库+sha 取正文。"""

    async def existing(self, device_id: str, source_id: str, shas: Sequence[str]) -> dict[str, str]:
        """返回 `sha -> 已存储的 project`；用于「同一内容不能换目标」校验。"""
        ...

    async def put(self, entries: Sequence[ContentEntry]) -> int:
        """幂等写入；返回实际新写的行数（已存在的 sha 跳过）。"""
        ...

    async def get(self, project: str, sha256: str) -> str | None:
        """取正文；不存在返回 None。"""
        ...

    async def close(self) -> None: ...


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _ch_time(value: datetime) -> str:
    """ClickHouse DateTime 在 JSONEachRow 里的稳妥写法。"""
    return _utc(value).strftime("%Y-%m-%d %H:%M:%S")


def _row(entry: ContentEntry, uploaded_at: datetime) -> dict[str, object]:
    return {
        "device_id": entry.device_id,
        "project": entry.project,
        "source_id": entry.source_id,
        "source_type": entry.source_type,
        "batch_id": entry.batch_id,
        "path": entry.path,
        "from_offset": entry.from_offset,
        "to_offset": entry.to_offset,
        "mtime": _ch_time(entry.mtime),
        "uploaded_at": _ch_time(uploaded_at),
        "sha256": entry.sha256,
        "producer": entry.producer,
        "content": entry.content,
    }


class LocalContentStore:
    """dev / 测试实现：本地目录存正文，语义与 ClickHouse 实现一致。"""

    def __init__(self, root: Path) -> None:
        self.root = root

    def _path(self, project: str, sha256: str) -> Path:
        return self.root / project / sha256[:2] / f"{sha256}.json"

    async def existing(self, device_id: str, source_id: str, shas: Sequence[str]) -> dict[str, str]:
        found: dict[str, str] = {}
        if not shas:
            return found
        for sha in set(shas):
            for path in self.root.glob(f"*/{sha[:2]}/{sha}.json"):
                try:
                    payload = json.loads(await AsyncPath(path).read_text(encoding="utf-8"))
                except (OSError, ValueError) as exc:
                    raise ContentUnavailable(f"local content unreadable: {sha}") from exc
                if not isinstance(payload, dict) or payload.get("sha256") != sha:
                    raise ContentUnavailable(f"local content corrupt: {sha}")
                if (payload.get("device_id"), payload.get("source_id")) != (
                    device_id,
                    source_id,
                ):
                    continue
                project = payload.get("project")
                if isinstance(project, str):
                    found[sha] = project
                break
        return found

    async def put(self, entries: Sequence[ContentEntry]) -> int:
        written = 0
        uploaded_at = datetime.now(UTC)
        for entry in entries:
            target = self._path(entry.project, entry.sha256)
            if await AsyncPath(target).exists():
                continue
            payload = _row(entry, uploaded_at)
            payload["mtime"] = _utc(entry.mtime).isoformat()
            payload["uploaded_at"] = uploaded_at.isoformat()
            await AsyncPath(target.parent).mkdir(parents=True, exist_ok=True)
            await self._atomic_write(target, payload)
            written += 1
        return written

    async def get(self, project: str, sha256: str) -> str | None:
        target = self._path(project, sha256)
        try:
            payload = json.loads(await AsyncPath(target).read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as exc:
            raise ContentUnavailable(f"local content unreadable: {sha256}") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("content"), str):
            raise ContentUnavailable(f"local content corrupt: {sha256}")
        if payload.get("project") != project or payload.get("sha256") != sha256:
            raise ContentUnavailable(f"local content identity mismatch: {sha256}")
        return cast(str, payload["content"])

    async def close(self) -> None:
        return None

    @staticmethod
    async def _atomic_write(target: Path, payload: dict[str, object]) -> None:
        tmp = target.with_name(f"{target.name}.{uuid.uuid4().hex}.tmp")
        text = json.dumps(payload, ensure_ascii=False) + "\n"
        try:
            await AsyncPath(tmp).write_text(text, encoding="utf-8", newline="\n")
            await AsyncPath(tmp).replace(target)
        except BaseException:
            try:
                await AsyncPath(tmp).unlink()
            except OSError:
                pass
            raise


class ClickHouseContentStore:
    """百度云 ClickHouse HTTP 实现（TLS + gzip + X-ClickHouse-User）。"""

    def __init__(
        self,
        url: str,
        *,
        user: str,
        password: str,
        ca: str | None = None,
        database: str = CH_DATABASE,
        table: str = CH_TABLE,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 120.0,
    ) -> None:
        self.database = database
        self.table = table
        headers = {"X-ClickHouse-User": user}
        if password:
            headers["X-ClickHouse-Key"] = password
        self.client = httpx.AsyncClient(
            base_url=url.rstrip("/"),
            headers=headers,
            verify=ca or True,
            timeout=httpx.Timeout(timeout, connect=10.0),
            transport=transport,
            trust_env=False,
        )

    @property
    def qualified(self) -> str:
        return f"`{self.database}`.`{self.table}`"

    async def existing(self, device_id: str, source_id: str, shas: Sequence[str]) -> dict[str, str]:
        if not shas:
            return {}
        query = (
            f"SELECT sha256, project FROM {self.qualified} FINAL "
            "WHERE device_id = {device:String} AND source_id = {source:String} "
            "AND sha256 IN {shas:Array(String)} FORMAT JSONEachRow"
        )
        rows = await self._request(
            query,
            params={
                "param_device": device_id,
                "param_source": source_id,
                "param_shas": json.dumps(sorted(set(shas))),
            },
            compress_response=True,
        )
        found: dict[str, str] = {}
        for line in rows.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except ValueError as exc:
                raise ContentUnavailable("clickhouse returned invalid JSON") from exc
            sha, project = item.get("sha256"), item.get("project")
            if isinstance(sha, str) and isinstance(project, str):
                found[sha] = project
        return found

    async def put(self, entries: Sequence[ContentEntry]) -> int:
        if not entries:
            return 0
        uploaded_at = datetime.now(UTC)
        body = "\n".join(
            json.dumps(_row(entry, uploaded_at), ensure_ascii=False) for entry in entries
        )
        query = f"INSERT INTO {self.qualified} FORMAT JSONEachRow"
        await self._request(
            query,
            method="POST",
            body=gzip.compress(body.encode("utf-8")),
            compress_body=True,
        )
        return len(entries)

    async def get(self, project: str, sha256: str) -> str | None:
        query = (
            f"SELECT content FROM {self.qualified} FINAL "
            "WHERE project = {project:String} AND sha256 = {sha:String} LIMIT 1 "
            "FORMAT JSONEachRow"
        )
        rows = await self._request(
            query,
            params={"param_project": project, "param_sha": sha256},
            compress_response=True,
        )
        for line in rows.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except ValueError as exc:
                raise ContentUnavailable("clickhouse returned invalid JSON") from exc
            content = item.get("content")
            return content if isinstance(content, str) else None
        return None

    async def close(self) -> None:
        await self.client.aclose()

    async def _request(
        self,
        query: str,
        *,
        method: str = "GET",
        params: dict[str, str] | None = None,
        body: bytes | None = None,
        compress_body: bool = False,
        compress_response: bool = False,
    ) -> str:
        query_params = {"database": self.database, "query": query}
        query_params.update(params or {})
        headers: dict[str, str] = {}
        if compress_body:
            headers["Content-Encoding"] = "gzip"
        if compress_response:
            query_params["enable_http_compression"] = "1"
            headers["Accept-Encoding"] = "gzip"
        try:
            response = await self.client.request(
                method,
                "/",
                params=query_params,
                content=body,
                headers=headers,
            )
        except httpx.HTTPError as exc:
            raise ContentUnavailable(f"clickhouse request failed: {type(exc).__name__}") from exc
        if response.status_code >= 400:
            # 不回显请求体（正文）或凭据；只带状态码与短摘要。
            raise ContentUnavailable(
                f"clickhouse http {response.status_code}: {response.text[:200]}"
            )
        return response.text


class NullContentStore:
    """未配置正文存储时的 dev 兜底：只推进游标与队列，不保存正文。

    生产不会走到这里：`create_app` 在 `MEMHUB_ENV=prod` 时强制要求 `MEMHUB_CH_URL`。
    """

    async def existing(self, device_id: str, source_id: str, shas: Sequence[str]) -> dict[str, str]:
        return {}

    async def put(self, entries: Sequence[ContentEntry]) -> int:
        return len(entries)

    async def get(self, project: str, sha256: str) -> str | None:
        return None

    async def close(self) -> None:
        return None


def build_content_store(data_dir: Path | None = None) -> RawContentStore:
    """按环境构造正文存储：有 `MEMHUB_CH_URL` 用 ClickHouse，否则退到本地目录。

    生产必须显式配置 `MEMHUB_CH_URL`（`create_app` / worker 入口会再校验一次），
    这里不替调用方猜测启用哪套存储。
    """
    url = os.environ.get("MEMHUB_CH_URL", "").strip()
    if url:
        return ClickHouseContentStore(
            url,
            user=os.environ.get("MEMHUB_CH_USER", "").strip(),
            password=os.environ.get("MEMHUB_CH_PASSWORD", ""),
            ca=os.environ.get("MEMHUB_CH_CA", "").strip() or None,
        )
    if data_dir is None:
        raise RuntimeError("需要 MEMHUB_CH_URL 或 MEMHUB_DATA_DIR 才能构造正文存储")
    return LocalContentStore(data_dir / "content_store")


__all__ = [
    "CH_DATABASE",
    "CH_TABLE",
    "ClickHouseContentStore",
    "ContentEntry",
    "ContentUnavailable",
    "LocalContentStore",
    "NullContentStore",
    "RawContentStore",
    "build_content_store",
]
