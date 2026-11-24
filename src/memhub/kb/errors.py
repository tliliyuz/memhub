"""存储层与写锁共用的错误类型；`manage` 对外再导出一份同名的别名。

单独成模块是为了打破循环：`store` / `pgstore` 需要 `WriteDeferred`、`RevisionConflict`，
而 `manage` 既是这些错误的使用者，又依赖存储层。错误语义与 HTTP/业务码的映射
仍由 `manage` 负责（`status` / `code` 挂在基类上，契约码来自 `memhub.contract`）。
"""

from __future__ import annotations

from typing import Any

from memhub.contract import ErrorCode


class ManageError(Exception):
    """管理端错误；`status` 映射 HTTP，`code` 是契约业务码。"""

    status = 400
    code = ErrorCode.KB_INVALID

    def __init__(self, message: str, data: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.data = data or {}


class NotFoundError(ManageError):
    status = 404
    code = ErrorCode.KB_NOT_FOUND


class ConflictError(ManageError):
    status = 409
    code = ErrorCode.KB_CONFLICT


class WriteDeferred(ConflictError):
    """写入需要等待；不是输入失败，不应消耗 worker 的重试次数。"""

    def __init__(
        self, message: str, data: dict[str, Any] | None = None, *, reason: str | None = None
    ) -> None:
        super().__init__(message, data)
        self.reason = reason


class InvalidError(ManageError):
    status = 422
    code = ErrorCode.KB_INVALID


class TargetUnavailable(Exception):
    """无法确认目标的登记状态（登记不可读、归档事务未完成）。

    调用方按可重试的服务端错误处理，不得沿用旧权限猜一个默认值。
    """


class ProjectMissing(FileNotFoundError):
    """目标知识库不存在（文件版看目录，PG 版看 `kb_projects`）。

    存储层不隐式建库：只有 `catalog.create_kb` 这样的显式建库路径可以登记新库。
    写节点或边时发现库不存在，一律失败而不是兜底创建。
    """


class ProjectInvalid(ValueError):
    """知识库 id 不合法（管理端映射 422）。"""


class NodeMissing(LookupError):
    """节点不存在或已软删（与 `query.NotFound` 区分：这是存储层事实）。"""


class RevisionConflict(RuntimeError):
    """乐观锁失配：调用方提供的 `expected_revision` 已过期。"""

    def __init__(self, node_id: str, *, expected: str, current: str | None) -> None:
        super().__init__(f"节点已被修改：{node_id}（expected={expected} current={current}）")
        self.node_id = node_id
        self.expected = expected
        self.current = current
