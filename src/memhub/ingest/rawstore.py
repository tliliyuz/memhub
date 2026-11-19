"""原始增量落盘：ingest 收到即写，worker 从这里读。

布局（内容寻址，重放与重复推送天然幂等）：

    <DATA_DIR>/raw_store/<device>/<source>/<sha[:2]>/<sha>.json

单个 JSON 文件包含该文件片段的元数据与正文；同一 sha 只会有一个文件，
所以在移动端重推同一批时只会覆盖成相同内容，不会膨胀。

为什么按 sha 而不是按设备路径：worker 按内容处理，同一份内容被两个设备/路径
推上来只该提炼一次；正文本身是 `content` 字段，路径只作溯源信息保留。

写入用「临时文件 + os.replace」：worker 只扫描到完整文件，不会读到半截 JSON。
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

from memhub.contract import IngestRequest

_SAFE = re.compile(r"[^A-Za-z0-9_.-]")


def _safe_id(value: str) -> str:
    """设备/来源 id 直接拼路径前做白名单化；不做路径拼接攻击面。"""
    cleaned = _SAFE.sub("_", value)
    return cleaned[:100] or "_"


def batch_dir(data_dir: Path, device_id: str, source_id: str) -> Path:
    return data_dir / "raw_store" / _safe_id(device_id) / _safe_id(source_id)


def save_batch(data_dir: Path, request: IngestRequest) -> int:
    """落一批原始增量；返回写入（或覆盖）的文件数。

    调用方保证本批已通过 `StateStore.apply()`——这里不判断游标与去重，
    只保证「已接受批次里的内容确实在盘上」。失败时抛 OSError，由调用方
    决定是否整批返回错误（当前策略：抛 500，客户端会重推）。
    """
    base = batch_dir(data_dir, request.device_id, request.source_id)
    written = 0
    for batch_file in request.files:
        target = base / batch_file.sha256[:2] / f"{batch_file.sha256}.json"
        if target.is_file():
            # 完全相同的内容已经落过盘；重放/跨设备重复推送走到这里。
            continue
        payload = {
            "device_id": request.device_id,
            "source_id": request.source_id,
            "source_type": request.source_type,
            "batch_id": request.batch_id,
            "path": batch_file.path,
            "from_offset": batch_file.from_offset,
            "to_offset": batch_file.to_offset,
            "mtime": batch_file.mtime.isoformat(),
            "sha256": batch_file.sha256,
            "content": batch_file.content,
        }
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=target.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(payload, handle, ensure_ascii=False)
            os.replace(tmp_name, target)
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise
        written += 1
    return written


__all__ = ["batch_dir", "save_batch"]
