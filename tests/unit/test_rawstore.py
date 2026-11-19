"""raw_store 落盘：内容寻址、幂等、原子写。"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from memhub.contract import BatchFile, IngestRequest
from memhub.ingest.rawstore import batch_dir, save_batch

NOW = datetime(2026, 11, 19, 2, 0, tzinfo=UTC)


def _request(
    content: str, *, path: str = "sessions/a.jsonl", device: str = "dev-1"
) -> IngestRequest:
    return IngestRequest(
        batch_id="b-1",
        device_id=device,
        source_id="cc-sessions",
        source_type="sessions",
        files=[
            BatchFile(
                path=path,
                from_offset=0,
                to_offset=len(content),
                mtime=NOW,
                sha256=hashlib.sha256(content.encode()).hexdigest(),
                content=content,
            )
        ],
    )


def test_writes_content_addressed_file(tmp_path: Path) -> None:
    request = _request("hello")
    assert save_batch(tmp_path, request) == 1
    sha = request.files[0].sha256
    target = batch_dir(tmp_path, "dev-1", "cc-sessions") / sha[:2] / f"{sha}.json"
    assert target.is_file()
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["content"] == "hello"
    assert payload["path"] == "sessions/a.jsonl"
    assert payload["mtime"] == NOW.isoformat()


def test_second_push_of_same_content_is_noop(tmp_path: Path) -> None:
    assert save_batch(tmp_path, _request("hello")) == 1
    assert save_batch(tmp_path, _request("hello", path="sessions/copy.jsonl")) == 0


def test_unsafe_ids_cannot_escape_the_data_dir(tmp_path: Path) -> None:
    save_batch(tmp_path, _request("hello", device="../../etc"))
    root = (tmp_path / "raw_store").resolve()
    for path in root.rglob("*.json"):
        assert root in path.resolve().parents


def test_failed_write_leaves_no_tmp_files(tmp_path: Path) -> None:
    request = _request("hello")
    save_batch(tmp_path, request)
    leftovers = list(tmp_path.rglob("*.tmp"))
    assert leftovers == []
