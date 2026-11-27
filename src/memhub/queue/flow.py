"""采集/上传共用的入队流程：校验目标 → 写正文 → 入队 → 推进游标。

顺序是有意的：正文必须先于队列行落库，worker 才不会领到一条取不到正文的任务。
反过来（先入队后写正文）会在正文写入失败时留下空任务。重复写入由内容寻址的
`(project, sha256)` 吸收，失败重试不会放大存储。
"""

from __future__ import annotations

from memhub.contract import IngestRequest, IngestResult
from memhub.ingest.store import Dedupe, MemoryStore, StateStore
from memhub.queue.content import RawContentStore
from memhub.queue.identity import BatchTargetConflict
from memhub.queue.tasks import MemoryQueue, PostgresQueue, Producer, QueueStore


def build_queue(state: StateStore) -> QueueStore:
    """PG 状态存储共用同一个连接池；其余实现退回进程内队列（dev / 测试）。"""
    if isinstance(state, MemoryStore):
        return MemoryQueue()
    from memhub.ingest.postgres import PostgresStore

    if isinstance(state, PostgresStore):
        return PostgresQueue(state.sessions)
    return MemoryQueue()


async def enqueue_batch(
    state: StateStore,
    queue: QueueStore,
    content: RawContentStore,
    request: IngestRequest,
    *,
    producer: Producer,
    limit: int,
) -> IngestResult:
    """一批增量的完整入队路径。调用方负责重放检查与鉴权。"""
    plan = await queue.check(request, producer=producer, limit=limit)

    # 队列行可能已被按天裁剪，正文却还在 TTL 内；再问一次正文存储，
    # 保证「同一内容不能换目标」在裁剪后仍然成立。
    if plan.entries:
        stored = await content.existing(
            request.device_id,
            request.source_id,
            [entry.sha256 for entry in plan.entries],
        )
        if any(project != plan.project for project in stored.values()):
            raise BatchTargetConflict()

    if plan.entries:
        await content.put(plan.entries)

    outcome = await queue.enqueue(request, producer=producer, limit=limit)
    return await state.apply(
        request,
        dedupe=Dedupe(accepted=outcome.accepted, duplicates=outcome.duplicates),
    )


__all__ = ["build_queue", "enqueue_batch"]
