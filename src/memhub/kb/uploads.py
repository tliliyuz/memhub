"""知识库上传：把文件直接送进提炼队列（复用 raw_store，不经过采集协议）。

上传只是把「本地有 agent 采集」换成「人在管理台贴文件」：落盘布局、配额、
worker 读取都与 `/ingest/raw` 完全一致，区别只在入口——这里没有 device token、
游标与批次幂等，批次状态改为读盘推导。

状态推导与 worker 的搬运语义一一对应（相对路径均相对 `<DATA_DIR>/raw_store`）：

- `processed_raw/<rel>` 存在 → `processed`；
- `pending_review/<rel>` 存在 → `failed`（连续 `max_attempts` 次失败后被隔离）；
- `state/failures.json[rel]` 有计数 → `failed`（重试中，带 `attempts`）;
- 文件仍在 `raw_store/<rel>` → `queued`（worker 只在窗口期搬运，白天长时间
  queued 是正常排队，不是故障）。

批次清单写在 `<DATA_DIR>/uploads/<batch_id>.json`；`uploads/` 在 `raw_store/`
之外，worker 的 `iter_pending` 不会扫到它。
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from anyio import Path as AsyncPath
from starlette.datastructures import UploadFile

from memhub.contract import BatchFile, IngestRequest
from memhub.kb.catalog import KB_ID_RE
from memhub.queue.rawstore import (
    QuotaExceeded,
    RawStoreQuota,
    batch_dir,
    estimate_new_bytes,
    save_batch,
)

DEVICE_ID = "kb-console"
SOURCE_TYPE = "docs"
MAX_FILES = 20
MAX_CHARS = 60_000
ALLOWED_SUFFIXES = (".md", ".txt", ".jsonl")
UPLOADS_DIR = "uploads"
PROCESSED_DIR = "processed_raw"
PENDING_DIR = "pending_review"
FAILURES_PATH = Path("state") / "failures.json"
BATCH_ID_RE = re.compile(r"^[0-9a-f]{32}$")


class UploadInvalid(Exception):
    """整批请求不合法：字段缺失、项目 id 非法、没有可接受的文件。"""

    def __init__(self, message: str, data: dict[str, Any] | None = None, *, status: int = 400):
        super().__init__(message)
        self.message = message
        self.data = data or {}
        self.status = status


class UploadQueueFull(Exception):
    """raw_store 已到上限：让上传方稍后再试，不把队列撑爆。"""

    def __init__(self, used: int, limit: int, incoming: int) -> None:
        super().__init__(f"queue full: {used}+{incoming} > {limit}")
        self.used = used
        self.limit = limit
        self.incoming = incoming


class KbUploads:
    """一次上传的落盘、清单与状态推导。配额对象由调用方持有（进程内共享）。"""

    def __init__(self, data_dir: Path, quota: RawStoreQuota) -> None:
        self.data_dir = data_dir
        self.quota = quota

    @property
    def raw_root(self) -> Path:
        return self.data_dir / "raw_store"

    @property
    def uploads_root(self) -> Path:
        return self.data_dir / UPLOADS_DIR

    # ---- 上传 ----

    async def accept(
        self,
        project: str,
        files: Sequence[UploadFile],
        *,
        project_exists: Callable[[str], Awaitable[bool]],
    ) -> dict[str, Any]:
        if not KB_ID_RE.match(project):
            raise UploadInvalid(
                "知识库 id 只能用小写字母/数字/./_/-，且以字母或数字开头",
                {"project": project},
                status=422,
            )
        # 只收已存在的知识库：拼错的 project 会在提炼时凭空建出一个空库目录，
        # 管理台的库列表里就会多出一个没有节点、也说不清来源的幽灵库。
        if not await project_exists(project):
            raise UploadInvalid(f"知识库不存在: {project}", {"project": project}, status=404)
        if not files:
            raise UploadInvalid("至少上传一个文件", {"files": "empty"}, status=422)
        if len(files) > MAX_FILES:
            raise UploadInvalid(f"单批最多 {MAX_FILES} 个文件", {"files": len(files)}, status=422)

        accepted: list[BatchFile] = []
        rejected: list[dict[str, str]] = []
        for upload in files:
            name = Path(upload.filename or "").name
            suffix = Path(name).suffix.lower()
            if not name:
                rejected.append({"name": "", "reason": "invalid_name"})
                continue
            if suffix not in ALLOWED_SUFFIXES:
                rejected.append({"name": name, "reason": "unsupported_type"})
                continue
            raw = await upload.read()
            try:
                content = raw.decode("utf-8")
            except UnicodeDecodeError:
                rejected.append({"name": name, "reason": "not_utf8"})
                continue
            if not content.strip():
                rejected.append({"name": name, "reason": "empty"})
                continue
            if len(content) > MAX_CHARS:
                rejected.append({"name": name, "reason": "too_large"})
                continue
            encoded = content.encode("utf-8")
            accepted.append(
                BatchFile(
                    path=name,
                    from_offset=0,
                    to_offset=len(encoded),
                    mtime=datetime.now(UTC),
                    sha256=hashlib.sha256(encoded).hexdigest(),
                    content=content,
                )
            )

        if not accepted:
            raise UploadInvalid(
                "没有可接受的文本文件（仅支持 .md / .txt / .jsonl，UTF-8，单文件 ≤60000 字符）",
                {"rejected": rejected},
                status=422,
            )

        batch_id = uuid.uuid4().hex
        request = IngestRequest(
            batch_id=batch_id,
            device_id=DEVICE_ID,
            source_id=project,
            source_type=SOURCE_TYPE,
            project=project,
            files=accepted,
        )
        incoming = await estimate_new_bytes(self.data_dir, request)
        try:
            await self.quota.check(incoming)
        except QuotaExceeded as exc:
            raise UploadQueueFull(exc.used, exc.limit, exc.incoming) from exc
        try:
            await save_batch(self.data_dir, request)
        except OSError:
            # 可能只写了一半；让下次请求重扫，别让缓存低估真实占用。
            await self.quota.invalidate()
            raise
        await self.quota.record(incoming)

        base = batch_dir(self.data_dir, DEVICE_ID, project).relative_to(self.raw_root)
        manifest: dict[str, Any] = {
            "batch_id": batch_id,
            "project": project,
            "device_id": DEVICE_ID,
            "source_id": project,
            "source_type": SOURCE_TYPE,
            "created_at": datetime.now(UTC).isoformat(),
            "files": [
                {
                    "name": batch_file.path,
                    "sha256": batch_file.sha256,
                    "chars": len(batch_file.content),
                    "rel": str(base / batch_file.sha256[:2] / f"{batch_file.sha256}.json"),
                }
                for batch_file in accepted
            ],
        }
        # raw 已落盘而清单写失败时，这个批次就查不到了；重传同一内容会拿到新
        # batch_id，raw 按 sha 去重、不会重复提炼。宁可这样也不回滚已收到的数据。
        await self._write_manifest(manifest)
        return {
            "batch_id": batch_id,
            "project": project,
            "accepted": [
                {"name": item["name"], "sha256": item["sha256"], "chars": item["chars"]}
                for item in manifest["files"]
            ],
            "rejected": rejected,
            "queued": True,
        }

    # ---- 状态 ----

    async def status(self, batch_id: str) -> dict[str, Any]:
        if not BATCH_ID_RE.match(batch_id):
            raise UploadInvalid("批次 id 非法", {"batch_id": batch_id}, status=404)
        path = self.uploads_root / f"{batch_id}.json"
        try:
            text = await AsyncPath(path).read_text(encoding="utf-8")
            manifest = json.loads(text)
        except OSError as exc:
            raise UploadInvalid(
                f"批次不存在: {batch_id}", {"batch_id": batch_id}, status=404
            ) from exc
        except ValueError as exc:
            raise UploadInvalid(
                f"批次清单损坏: {batch_id}", {"batch_id": batch_id}, status=500
            ) from exc
        if not isinstance(manifest, dict):
            raise UploadInvalid(f"批次清单损坏: {batch_id}", status=500)

        failures = await self._load_failures()
        entries: list[dict[str, Any]] = []
        counts = {"queued": 0, "processed": 0, "failed": 0, "missing": 0}
        files = manifest.get("files")
        for item in files if isinstance(files, list) else []:
            if not isinstance(item, dict):
                continue
            rel = str(item.get("rel", ""))
            entry: dict[str, Any] = {"name": item.get("name", ""), "sha256": item.get("sha256", "")}
            state = await self._file_state(rel, failures)
            entry["status"] = state
            if state == "failed" and rel in failures:
                entry["attempts"] = failures[rel]
            counts[state] += 1
            entries.append(entry)
        return {
            "batch_id": manifest.get("batch_id", batch_id),
            "project": manifest.get("project", ""),
            "created_at": manifest.get("created_at", ""),
            "total": len(entries),
            "counts": counts,
            "files": entries,
        }

    async def _file_state(self, rel: str, failures: dict[str, int]) -> str:
        if not rel:
            return "missing"
        if await AsyncPath(self.data_dir / PROCESSED_DIR / rel).is_file():
            return "processed"
        if await AsyncPath(self.data_dir / PENDING_DIR / rel).is_file():
            return "failed"
        if failures.get(rel, 0) > 0:
            return "failed"
        if await AsyncPath(self.raw_root / rel).is_file():
            return "queued"
        return "missing"

    async def _load_failures(self) -> dict[str, int]:
        try:
            text = await AsyncPath(self.data_dir / FAILURES_PATH).read_text(encoding="utf-8")
            data = json.loads(text)
        except (OSError, ValueError):
            return {}
        if not isinstance(data, dict):
            return {}
        return {str(key): int(value) for key, value in data.items() if isinstance(value, int)}

    async def _write_manifest(self, manifest: dict[str, Any]) -> None:
        target = self.uploads_root / f"{manifest['batch_id']}.json"
        await AsyncPath(self.uploads_root).mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(f"{target.name}.{uuid.uuid4().hex}.tmp")
        text = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
        try:
            await AsyncPath(tmp).write_text(text, encoding="utf-8", newline="\n")
            await AsyncPath(tmp).replace(target)
        except BaseException:
            try:
                await AsyncPath(tmp).unlink()
            except OSError:
                pass
            raise


__all__ = [
    "ALLOWED_SUFFIXES",
    "BATCH_ID_RE",
    "MAX_CHARS",
    "MAX_FILES",
    "KbUploads",
    "UploadInvalid",
    "UploadQueueFull",
]
