"""kb 读缓存（ADR-0023）的验收条件。

缓存是纯加速层：命中不重算、数据版本变化即失效、任何 Redis 故障都降级到 PG，
key 与 value 都不携带正文、口令或连接串。这里用替身 Redis 与可变的 epoch 源验收，
不依赖真实 Redis（生产连通性由部署验收覆盖）。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest

from memhub.kb.read_cache import (
    SCHEMA_VERSION,
    NullReadCache,
    RedisReadCache,
    build_read_cache,
)


class FakeRedis:
    """最小 async Redis 替身：记下 key/value、命中数，并可按需注入故障。"""

    def __init__(self) -> None:
        self.data: dict[str, bytes] = {}
        self.gets = 0
        self.sets = 0
        self.ttls: list[int] = []
        self.fail_get = False
        self.fail_set = False
        self.closed = False
        self.get_result: bytes | None = None

    async def get(self, key: str) -> bytes | None:
        self.gets += 1
        if self.fail_get:
            raise ConnectionError("redis down")
        if self.get_result is not None:
            return self.get_result
        return self.data.get(key)

    async def set(self, key: str, value: bytes, *, ex: int | None = None) -> None:
        self.sets += 1
        if self.fail_set:
            raise ConnectionError("redis down")
        assert ex is not None
        self.ttls.append(ex)
        self.data[key] = value

    async def aclose(self) -> None:
        self.closed = True


class EpochSource:
    def __init__(self, value: str = "n0:0:e0:0") -> None:
        self.value = value
        self.calls = 0
        self.fail = False

    async def __call__(self) -> str:
        self.calls += 1
        if self.fail:
            raise RuntimeError("pg down")
        return self.value


class Counter:
    def __init__(self, payload: dict[str, Any] | None = None) -> None:
        self.calls = 0
        self.payload = payload or {"value": 1}

    async def __call__(self) -> dict[str, Any]:
        self.calls += 1
        return dict(self.payload)


async def test_null_cache_never_touches_epoch_or_redis() -> None:
    cache = NullReadCache()
    compute = Counter()
    epoch = EpochSource()
    assert await cache.get_or_compute("stats", {}, compute=compute, epoch_fn=epoch) == {"value": 1}
    assert compute.calls == 1
    assert epoch.calls == 0
    await cache.aclose()


async def test_hit_reuses_value_without_recomputing() -> None:
    client = FakeRedis()
    cache = RedisReadCache(client, ttl=30)
    compute = Counter()
    epoch = EpochSource()

    first = await cache.get_or_compute("stats", {}, compute=compute, epoch_fn=epoch)
    second = await cache.get_or_compute("stats", {}, compute=compute, epoch_fn=epoch)

    assert first == second == {"value": 1}
    assert compute.calls == 1
    assert client.sets == 1
    assert client.gets == 2
    assert client.ttls == [30]


async def test_epoch_change_invalidates_previous_key() -> None:
    client = FakeRedis()
    cache = RedisReadCache(client)
    compute = Counter()
    epoch = EpochSource("n1:2026-11-28T00:00:00+00:00:e0:0")

    await cache.get_or_compute("nodes", {"limit": 50}, compute=compute, epoch_fn=epoch)
    epoch.value = "n1:2026-11-28T00:01:00+00:00:e0:0"
    await cache.get_or_compute("nodes", {"limit": 50}, compute=compute, epoch_fn=epoch)

    assert compute.calls == 2
    assert len(client.data) == 2


async def test_params_participate_in_key() -> None:
    client = FakeRedis()
    cache = RedisReadCache(client)
    compute = Counter()
    epoch = EpochSource()

    await cache.get_or_compute("nodes", {"limit": 50}, compute=compute, epoch_fn=epoch)
    await cache.get_or_compute("nodes", {"limit": 500}, compute=compute, epoch_fn=epoch)

    assert compute.calls == 2
    assert len(client.data) == 2


async def test_get_failure_degrades_to_pg() -> None:
    client = FakeRedis()
    client.fail_get = True
    cache = RedisReadCache(client)
    compute = Counter()

    assert await cache.get_or_compute("stats", {}, compute=compute, epoch_fn=EpochSource()) == {
        "value": 1
    }
    assert compute.calls == 1
    # 读失败就当缓存不可用：本次不再尝试写，结果照常返回
    assert client.sets == 0


async def test_set_failure_still_returns_fresh_value() -> None:
    client = FakeRedis()
    client.fail_set = True
    cache = RedisReadCache(client)
    compute = Counter({"value": 2})

    assert await cache.get_or_compute("stats", {}, compute=compute, epoch_fn=EpochSource()) == {
        "value": 2
    }
    assert compute.calls == 1


async def test_epoch_failure_degrades_to_pg() -> None:
    client = FakeRedis()
    cache = RedisReadCache(client)
    compute = Counter()
    epoch = EpochSource()
    epoch.fail = True

    assert await cache.get_or_compute("stats", {}, compute=compute, epoch_fn=epoch) == {"value": 1}
    assert compute.calls == 1
    assert client.gets == 0


async def test_schema_version_mismatch_recomputes() -> None:
    client = FakeRedis()
    client.get_result = b'{"v": 999, "data": {"value": 9}}'
    cache = RedisReadCache(client)
    compute = Counter()

    assert await cache.get_or_compute("stats", {}, compute=compute, epoch_fn=EpochSource()) == {
        "value": 1
    }
    assert compute.calls == 1


async def test_corrupt_value_recomputes() -> None:
    client = FakeRedis()
    client.get_result = b"not-json"
    cache = RedisReadCache(client)
    compute = Counter()

    assert await cache.get_or_compute("stats", {}, compute=compute, epoch_fn=EpochSource()) == {
        "value": 1
    }
    assert compute.calls == 1


async def test_key_carries_no_payload_or_secret() -> None:
    client = FakeRedis()
    cache = RedisReadCache(client)
    params = {"q": "机密正文片段", "password": "s3cr3t", "limit": 50}

    await cache.get_or_compute("nodes", params, compute=Counter(), epoch_fn=EpochSource())

    (key,) = client.data
    assert key.startswith(f"kb:r{SCHEMA_VERSION}:nodes:")
    epoch_digest, params_digest = key.split(":")[3:]
    assert len(epoch_digest) == 12 and len(params_digest) == 16
    assert "机密正文片段" not in key
    assert "s3cr3t" not in key
    # 值是带 schema 版本的 JSON，且只含计算结果
    raw = client.data[key]
    assert f'"v": {SCHEMA_VERSION}'.encode() in raw


async def test_no_epoch_source_disables_cache() -> None:
    client = FakeRedis()
    cache = RedisReadCache(client)
    compute = Counter()

    assert await cache.get_or_compute("stats", {}, compute=compute, epoch_fn=None) == {"value": 1}
    assert client.gets == 0
    assert client.sets == 0


async def test_close_failure_is_swallowed() -> None:
    class Broken(FakeRedis):
        async def aclose(self) -> None:
            raise ConnectionError("redis down")

    await RedisReadCache(Broken()).aclose()


def test_build_cache_disabled_without_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MEMHUB_REDIS_URL", raising=False)
    assert isinstance(build_read_cache(), NullReadCache)
    monkeypatch.setenv("MEMHUB_REDIS_URL", "   ")
    assert isinstance(build_read_cache(), NullReadCache)


async def test_build_cache_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEMHUB_REDIS_URL", "redis://127.0.0.1:6379/0")
    monkeypatch.setenv("MEMHUB_REDIS_PASSWORD", "not-in-logs")
    cache = build_read_cache()
    assert isinstance(cache, RedisReadCache)
    await cache.aclose()


class _FakeKbStore:
    """只覆盖 stats 路径需要的读面；epoch 由测试手动推进。"""

    resolve_short_aliases = False

    def __init__(self) -> None:
        self.epoch = "n1:2026-11-28T08:00:00+00:00:e0:0"
        self.list_calls = 0

    async def cache_epoch(self) -> str:
        return self.epoch

    async def list_ids(self, project: str | None = None) -> list[str]:
        self.list_calls += 1
        return ["memhub/fact/alpha"]

    async def read_many(self, node_ids: list[str], *, include_body: bool = True):
        from memhub.contract import Kind, NodeFrontmatter, Tier
        from memhub.kb.query import NodeRecord

        node = NodeFrontmatter(
            id="memhub/fact/alpha",
            project="memhub",
            kind=Kind.FACT,
            title="缓存验收",
            tier=Tier.CANONICAL,
            created_at=datetime(2026, 11, 28, 8, 0, tzinfo=UTC),
            updated_at=datetime(2026, 11, 28, 8, 0, tzinfo=UTC),
        )
        return [NodeRecord("memhub/fact/alpha", node, "", "0123456789abcdef", 2)]

    async def edge_lines(self) -> AsyncIterator[str]:
        for line in ():
            yield line


def test_stats_route_uses_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """接线验收：/stats 两次请求命中缓存；数据版本变化后重新计算。"""
    from typing import cast

    from fastapi.testclient import TestClient

    from memhub.kb.api import create_app
    from memhub.kb.pgstore import PgKnowledgeStore

    store = _FakeKbStore()
    client = FakeRedis()
    app = create_app(
        store=cast(PgKnowledgeStore, store),
        cache=RedisReadCache(client),
    )
    with TestClient(app) as api:
        first = api.get("/api/v1/kb/stats")
        second = api.get("/api/v1/kb/stats")
        assert first.status_code == second.status_code == 200
        assert first.json() == second.json()
        assert store.list_calls == 1
        assert client.sets == 1

        store.epoch = "n1:2026-11-28T09:00:00+00:00:e0:0"
        third = api.get("/api/v1/kb/stats")
        assert third.status_code == 200
        assert store.list_calls == 2
        assert client.sets == 2


async def test_default_ttl_is_ten_minutes() -> None:
    """低频访问下 60s 等于每次冷启动；ADR-0024 把默认 TTL 提到 600s。"""
    client = FakeRedis()
    cache = RedisReadCache(client)
    await cache.get_or_compute("stats", {}, compute=Counter(), epoch_fn=EpochSource())
    assert client.ttls == [600]
