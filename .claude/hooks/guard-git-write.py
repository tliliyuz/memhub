#!/usr/bin/env python3
"""Claude Code PreToolUse 钩子：Git 远端操作防呆。

由 `.claude/settings.json` 注册，经 stdin 读取 hook JSON（官方 schema：
`tool_input.command`）。把 DEVELOPMENT §6 的 Git 纪律机器化：

DEVELOPMENT §6 规定「Git 本地写操作默认授权，仅远端操作需要负责人针对当前
操作明确授权」，因此本钩子只拦截远端操作。`git status && git push` 这类复合
命令会按 `&&` `||` `;` `|` 切段分别判定，不会因为前半段放行就整条放行。

裁决分两档：
- 只读子命令与全部本地写操作（`add` / `commit` / `merge` / `rebase` /
  `switch` / `reset --hard` / `clean -f` / `worktree` / `branch` / `tag` 等）
  → 直接放行。本地不可逆操作的数据安全由 DEVELOPMENT §6 的文本约束负责，
  不再逐条弹窗。
- **远端操作**（`push` / `fetch` / `pull` / `clone` / `ls-remote` / `remote`
  改写 / `send-email` / `request-pull` / `lfs` 远端动作 / `archive --remote`
  等）→ 返回 `ask`，由权限层请负责人当场确认。

本仓 DEVELOPMENT §5 有意不禁止 `Co-Authored-By` 署名，因此钩子不做署名拦截。

实现注意：只把「段首（允许 `VAR=值` 前缀）就是 `git`」的段当作 git 命令，
否则 `grep "git push" docs/` 这类包含文本的命令会被误拦。

输出约定（官方 PreToolUse 语义）：打印 `permissionDecision: ask` 交由权限层
请负责人确认，并以 `permissionDecisionReason` 回传理由。无输出则放行。

用 Python 而不是 bash + jq：本仓开发环境是 Windows，不保证 jq 存在；
钩子失效会让门禁静默失效，比钩子本身慢一点更糟。
"""

from __future__ import annotations

import json
import re
import shlex
import sys

# 复合命令按 shell 分隔符切段后逐段判定。切分必须感知引号：否则
# `grep -rn "git push" docs/` 会在引号内的 `|`（或 `&&`）处被切断，
# 后一段段首正好是 `git`，造成误拦。
SEGMENT_OPERATORS = ("&&", "||", ";", "|", "\n")

# 无参数即为只读的子命令。
READ_ONLY_SUBCOMMANDS = frozenset(
    {
        "log",
        "status",
        "diff",
        "show",
        "blame",
        "annotate",
        "rev-parse",
        "rev-list",
        "describe",
        "shortlog",
        "cat-file",
        "ls-files",
        "ls-tree",
        "merge-base",
        "grep",
        "for-each-ref",
        "name-rev",
        "whatchanged",
        "count-objects",
        "check-ignore",
        "verify-commit",
        "verify-tag",
        "help",
        "version",
    }
)

# 需要看参数才能判定只读的子命令。只有「出现了列举/查询类参数、且没有出现写类参数」
# 才算只读；这与「参数白名单」不同：`git config --get user.name` 里的 `user.name`
# 是值不是选项，必须允许。
LIST_FLAGS = {
    "tag": (
        "-l",
        "--list",
        "-v",
        "--verify",
        "-n",
        "--sort",
        "--format",
        "--contains",
        "--points-at",
        "--merged",
        "--no-merged",
        "--column",
        "--no-column",
    ),
    "branch": (
        "-a",
        "--all",
        "-r",
        "--remotes",
        "-v",
        "--verbose",
        "--list",
        "--show-current",
        "--contains",
        "--merged",
        "--no-merged",
        "--format",
        "--sort",
        "--column",
        "--no-column",
    ),
    "remote": ("-v", "--verbose", "get-url"),
    "config": ("--get", "--get-all", "--get-regexp", "--list", "-l"),
    "stash": ("list", "show"),
    "reflog": ("show",),
    "submodule": ("status", "summary"),
}

# 写类参数：出现即判定为非只读，优先于列举参数。
WRITE_FLAGS = {
    "tag": (
        "-d",
        "--delete",
        "-a",
        "--annotate",
        "-f",
        "--force",
        "-m",
        "--message",
        "-F",
        "--file",
        "-s",
        "--sign",
        "-u",
        "--local-user",
        "-e",
        "--edit",
    ),
    "branch": (
        "-d",
        "-D",
        "--delete",
        "-m",
        "-M",
        "--move",
        "-c",
        "-C",
        "--copy",
        "-f",
        "--force",
        "-u",
        "--set-upstream-to",
        "--unset-upstream",
        "--edit-description",
        "--create-reflog",
        "--track",
        "--no-track",
    ),
    "remote": ("add", "remove", "rm", "rename", "set-url", "set-head", "prune", "update"),
    "config": (
        "--unset",
        "--unset-all",
        "--add",
        "--replace-all",
        "--rename-section",
        "--remove-section",
        "--edit",
        "-e",
    ),
    "stash": ("save", "push", "pop", "apply", "drop", "clear", "create", "store", "branch"),
    "reflog": ("expire", "delete", "drop"),
    "submodule": ("add", "init", "update", "deinit", "foreach", "sync", "absorbgitdirs"),
}

# 无参数即为只读（列目录、看历史）；`stash` 不在此列 —— 裸 `git stash` 是保存改动。
EMPTY_IS_READ_ONLY = frozenset({"tag", "branch", "remote", "config", "reflog", "submodule"})

# 影响远端：一律交回权限层，与本地操作分开授权。
REMOTE_SUBCOMMANDS = frozenset(
    {
        "push",
        "fetch",
        "pull",
        "clone",
        "ls-remote",
        "remote",
        "submodule",
        "svn",
        "send-email",
        "request-pull",
    }
)

# `git lfs` 子命令中会访问远端的动作；其余（install / track / status 等）本地放行。
LFS_REMOTE_ACTIONS = frozenset({"push", "fetch", "pull"})

# git 全局选项：带值需要跳两个 token。
GLOBAL_OPTS_WITH_ARG = frozenset(
    {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--config-env"}
)
GLOBAL_OPTS_NO_ARG = frozenset(
    {"--no-pager", "--bare", "--literal-pathspecs", "--no-optional-locks", "--no-replace-objects"}
)
ENV_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
SHELL_NAMES_RE = re.compile(r"^(?:bash|sh|zsh|dash|fish|pwsh|powershell|cmd)(?:\.exe)?$")


def emit_decision(decision: str, reason: str) -> None:
    """输出 PreToolUse 决策。

    `ask` 用于远端 git 操作：钩子读不到对话内容，也无法区分「负责人当次批准」与
    「Agent 自称已批准」，因此把判断交回 Claude Code 的权限层，由负责人对**这一条
    命令**当场确认。批准即构成 DEVELOPMENT §6 要求的「针对当前操作的明确授权」，
    不会扩散到后续远端命令。本地操作不再经过本钩子询问。
    """
    payload = json.dumps(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": decision,
                "permissionDecisionReason": reason,
                "continueOnBlock": True,
            }
        },
        ensure_ascii=False,
    )
    # Windows 下 sys.stdout 默认是 cp936，中文理由会变成乱码送到 Claude Code。
    # 显式写 UTF-8 字节，保证钩子输出在所有平台可读。
    sys.stdout.buffer.write(payload.encode("utf-8"))
    sys.stdout.buffer.flush()


def split_segments(command: str) -> list[str]:
    """按引号外的 shell 分隔符切段。"""
    segments: list[str] = []
    buffer: list[str] = []
    index = 0
    quote = ""
    while index < len(command):
        char = command[index]
        if quote:
            buffer.append(char)
            if char == quote and (index == 0 or command[index - 1] != "\\"):
                quote = ""
            index += 1
            continue
        if char in ("'", '"'):
            quote = char
            buffer.append(char)
            index += 1
            continue
        matched = next((op for op in SEGMENT_OPERATORS if command.startswith(op, index)), None)
        if matched:
            segments.append("".join(buffer))
            buffer = []
            index += len(matched)
            continue
        buffer.append(char)
        index += 1
    segments.append("".join(buffer))
    return [segment for segment in segments if segment.strip()]


def parse_git_segment(segment: str) -> tuple[str, list[str]] | None:
    """段首（允许 `VAR=值` 前缀）为 `git` 时返回 (子命令, 参数)，否则 None。"""
    try:
        tokens = shlex.split(segment, posix=True)
    except ValueError:
        tokens = segment.split()
    index = 0
    while index < len(tokens) and ENV_ASSIGN_RE.match(tokens[index]):
        index += 1
    if index >= len(tokens):
        return None
    # `bash -c 'git push'` / `powershell -Command "git push"` 旁路：解包内层命令。
    if SHELL_NAMES_RE.match(tokens[index]):
        for position, token in enumerate(tokens[index + 1 :], start=index + 1):
            if token in ("-c", "-Command", "--command", "/c", "/C"):
                inner = " ".join(tokens[position + 1 :])
                nested = parse_git_segment(inner)
                if nested is not None:
                    return nested
                break
    if tokens[index] != "git":
        return None
    index += 1
    while index < len(tokens):
        token = tokens[index]
        if token in GLOBAL_OPTS_NO_ARG:
            index += 1
            continue
        if token in GLOBAL_OPTS_WITH_ARG:
            index += 2
            continue
        if token.startswith(("--git-dir=", "--work-tree=", "--namespace=", "--config-env=")):
            index += 1
            continue
        if len(token) > 2 and token[:2] in ("-C", "-c"):
            index += 1
            continue
        break
    if index >= len(tokens):
        return ("", [])
    return (tokens[index], tokens[index + 1 :])


def is_read_only(subcommand: str, args: list[str]) -> bool:
    if subcommand in READ_ONLY_SUBCOMMANDS:
        return True
    list_flags = LIST_FLAGS.get(subcommand)
    if list_flags is None:
        # `commit` / `push` / `merge` 等不在两表中的子命令一律视为写操作。
        return False
    if not args:
        return subcommand in EMPTY_IS_READ_ONLY
    write_flags = WRITE_FLAGS.get(subcommand, ())
    for arg in args:
        if any(arg == flag or arg.startswith(flag) for flag in write_flags):
            return False
    # 有列举参数即可判定只读；剩余 token 是值或引用（`user.name`、`origin`）而非动作。
    return any(arg == flag or arg.startswith(flag) for arg in args for flag in list_flags)


def is_remote_operation(subcommand: str, args: list[str]) -> bool:
    """判定是否会访问或改写远端。"""
    if subcommand in REMOTE_SUBCOMMANDS:
        return True
    if subcommand == "lfs":
        return any(action in LFS_REMOTE_ACTIONS for action in args)
    if subcommand == "archive":
        return any(arg == "--remote" or arg.startswith("--remote=") for arg in args)
    return False


def classify(command: str) -> tuple[str, str] | None:
    """返回 (决策, 理由)；整条命令都在放行范围时返回 None。

    放行：只读子命令与全部本地写操作（`add` / `commit` / `merge` / `rebase` /
    `reset --hard` / `clean -f` / `worktree` / `branch` 等）。
    `ask`：访问或改写远端的子命令（`push` / `fetch` / `pull` / `remote` 等）。
    """
    for segment in split_segments(command):
        parsed = parse_git_segment(segment)
        if parsed is None:
            continue
        subcommand, args = parsed
        if is_read_only(subcommand, args):
            continue
        shown = subcommand or "（缺少子命令）"
        if is_remote_operation(subcommand, args):
            return (
                "ask",
                f"该命令会访问或改写远端（`git {shown}`）。DEVELOPMENT §6 要求：远端操作"
                "需负责人针对当前操作单独授权，本地操作与工作区闭环的授权不覆盖远端。",
            )
    return None


def read_stdin_text() -> str:
    """按 UTF-8 读 stdin；Windows 默认解码是 cp936，直接 sys.stdin.read() 会炸。"""
    raw = sys.stdin.buffer.read()
    for encoding in ("utf-8", "utf-8-sig", "gbk"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def main() -> int:
    raw = read_stdin_text()
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        return 0
    command = (payload.get("tool_input") or {}).get("command") or ""
    if "git" not in command:
        return 0

    result = classify(command)
    if result:
        emit_decision(*result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
