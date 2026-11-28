"""kb 读接口的本地热读缓存（ADR-0023）。

只为 `nodes` / `stats` / `audit` 这类仍偏慢、且结果可重建的读开缓存：Redis 只做
纯缓存（重启即丢），任何时候连不上、未安装或读失败都必须降级到 PG，绝不影响主路径。

一致性靠「数据版本 epoch 拼进 key」而不是靠 TTL：
- epoch 由 `store.cache_epoch()` 给出（active 节点 count/max(updated_at) + 边
  count/max(created_at) 的廉价聚合）。任何增/改/删节点或边都会改 epoch，
  旧 key 随即失联，近似强一致；
- TTL 只是内存背压上限，不承担正确性。

键与值都不含正文、口令或任何密钥：key 只由命名空间、参数摘要与 epoch 摘要拼成，
value 是带 schema 版本号的 JSON。Redis 口令只从环境变量读取，不落日志。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from collections.abc import Awaitable, Callable, Mapping
from importlib import import_module
from typing import Any, Protocol

logger = logging.getLogger(__name__)

# 缓存值格式版本；值结构变化时 +1，旧值读到时按未命中处理并重算。
SCHEMA_VERSION = 1
DEFAULT_TTL_SECONDS = 60.0
_KEY_PREFIX = f"kb:r{SCHEMA_VERSION}"


class ReadCache(Protocol):
    async def get_or_compute(
        self,
        ns: str,
        params: Mapping[str, Any],
        *,
        compute: Callable[[], Awaitable[dict[str, Any]]],
        epoch_fn: Callable[[], Awaitable[str]] | None,
    ) -> dict[str, Any]: ...

    async def aclose(self) -> None: ...


class NullReadCache:
    """未启用缓存：永远直接计算，不触碰 epoch、不产生额外开销。"""

    async def get_or_compute(
        self,
        ns: str,
        params: Mapping[str, Any],
        *,
        compute: Callable[[], Awaitable[dict[str, Any]]],
        epoch_fn: Callable[[], Awaitable[str]] | None,
    ) -> dict[str, Any]:
        return await compute()

    async def aclose(self) -> None:
        return None


class RedisReadCache:
    """Redis 读缓存实现；任何异常只降级，不向上抛。"""

    def __init__(self, client: Any, *, ttl: float = DEFAULT_TTL_SECONDS) -> None:
        self._client = client
        self._ttl = ttl
        self._warned: set[str] = set()

    def _warn_once(self, op: str, exc: Exception) -> None:
        # 只提示一次，避免缓存故障刷屏；不打印连接串或口令。
        if op in self._warned:
            return
        self._warned.add(op)
        logger.warning("kb 读缓存 %s 失败，降级到 PG：%s", op, type(exc).__name__)

    @staticmethod
    def _key(ns: str, params: Mapping[str, Any], epoch: str) -> str:
        material = json.dumps([ns, sorted(params.items())], ensure_ascii=False, default=str)
        digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]
        epoch_digest = hashlib.sha256(epoch.encode("utf-8")).hexdigest()[:12]
        return f"{_KEY_PREFIX}:{ns}:{epoch_digest}:{digest}"

    @staticmethod
    def _encode(value: dict[str, Any]) -> bytes:
        return json.dumps(
            {"v": SCHEMA_VERSION, "data": value}, ensure_ascii=False, default=str
        ).encode("utf-8")

    @staticmethod
    def _decode(raw: bytes) -> dict[str, Any] | None:
        try:
            payload = json.loads(raw)
        except (ValueError, TypeError):
            return None
        if not isinstance(payload, dict) or payload.get("v") != SCHEMA_VERSION:
            return None
        data = payload.get("data")
        return data if isinstance(data, dict) else None

    async def get_or_compute(
        self,
        ns: str,
        params: Mapping[str, Any],
        *,
        compute: Callable[[], Awaitable[dict[str, Any]]],
        epoch_fn: Callable[[], Awaitable[str]] | None,
    ) -> dict[str, Any]:
        if epoch_fn is None:
            return await compute()
        try:
            epoch = await epoch_fn()
        except Exception as exc:  # noqa: BLE001 - epoch 失败等价于缓存不可用
            self._warn_once("epoch", exc)
            return await compute()
        key = self._key(ns, params, epoch)
        try:
            raw = await self._client.get(key)
        except Exception as exc:  # noqa: BLE001 - 读失败降级
            self._warn_once("get", exc)
            return await compute()
        if raw is not None:
            cached = self._decode(raw)
            if cached is not None:
                return cached
        value = await compute()
        try:
            await self._client.set(key, self._encode(value), ex=int(self._ttl))
        except Exception as exc:  # noqa: BLE001 - 写失败不影响本次返回
            self._warn_once("set", exc)
        return value

    async def aclose(self) -> None:
        try:
            await self._client.aclose()
        except Exception as exc:  # noqa: BLE001 - 关闭失败不阻断退出
            self._warn_once("close", exc)


def build_read_cache(*, url: str | None = None, password: str | None = None) -> ReadCache:
    """按环境变量构造读缓存；未配置或未安装 redis 时返回空实现（缓存关闭）。

    `MEMHUB_REDIS_URL` 缺失 = 能力关闭，不是错误。口令只读 `MEMHUB_REDIS_PASSWORD`，
    不写日志、不进 key。
    """
    url = (url if url is not None else os.environ.get("MEMHUB_REDIS_URL", "")).strip()
    if not url:
        return NullReadCache()
    password = password if password is not None else os.environ.get("MEMHUB_REDIS_PASSWORD", "")
    try:
        client = _redis_client(url, password or None)
    except ImportError:
        logger.warning("已配置 MEMHUB_REDIS_URL 但未安装 redis 客户端，读缓存关闭")
        return NullReadCache()
    return RedisReadCache(client)


def _redis_client(url: str, password: str | None) -> Any:
    """延迟导入 redis 客户端：可选依赖不进模块导入期，也不依赖其类型存根。"""
    redis = import_module("redis.asyncio")
    return redis.Redis.from_url(
        url,
        password=password,
        socket_timeout=0.5,
        socket_connect_timeout=0.5,
        decode_responses=False,
    )
