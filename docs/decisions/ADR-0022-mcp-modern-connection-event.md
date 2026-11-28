# ADR-0022 MCP 现代协议的连接事件并入漏斗

| 属性 | 值 |
|:---|:---|
| 状态 | accepted |
| 日期 | 2026-11-27（负责人裁决：选择「修漏斗口径」，把现代协议的连接事件纳入计数） |

## 背景

[ADR-0018](ADR-0018-mcp-discovery-trace.md) 定义的漏斗口径是「连接数 = `initialize` 成功行数」，
当时假设客户端都走 2025 版本的 `initialize` 握手。官方 MCP Python SDK（部署锁定 `mcp==2.3.0`）
与 Claude Code 2.1.332 已协商出 2026-07-28 现代协议：客户端首包带 `Mcp-Protocol-Version:
2026-07-28` 请求 `server/discover`，随后直接发 `tools/list` 与 `tools/call`，**不存在
`initialize` 握手**；SDK 在 `StreamableHTTPSessionManager` 里按该请求头选择现代单次交换路径。

生产实测（2026-11-27，`kb_mcp_trace` 近 3 天）：`initialize` 0 行，`tools/list` 24 行
（`tool_count=7`，客户端 `claude-code/2.1.332`），`kb_search` 成功 1 行。管理台漏斗因此
显示「0 连接 → 24 次列工具」，把「连上了但不按旧协议握手」误读成「没人连上」，也无法回答
ADR-0018 要区分的「连上了但没列工具」。本地用同版本客户端对 mock 入口抓包复现：首包
`server/discover`（`id=server-discover-probe-1`），次包 `tools/list`，全程无 `initialize`。

`server/discover` 是现代协议里唯一的连接等价事件：客户端每个对端进程在建立连接时探测一次，
其结果同时携带 `supportedVersions` 与 `instructions`。现有 `observe_discovery` 只观察
`initialize` / `tools/list`，因此该事件既不进入漏斗，也不在明细里可见。

## 决策

1. **把 `server/discover` 纳入发现层记录点**：`observe_discovery` 同时观察该方法，记
   `event=discover`；`status` 为 `ok` / `error`，`tool`、`tool_count`、`result_bytes`、`args_digest`
   为空，其余元数据与 `initialize` 一致。
2. **漏斗连接数按协议代累加**：`connections = initialize 成功行数 + discover 成功行数`。
   不按凭据或客户端去重，延续 ADR-0018 对「去重会隐藏真实连接次数」的否决。
3. **列表接口事件取值扩展为 `call / list_tools / initialize / discover`**，默认仍为 `call`，
   既有页面、筛选与分页口径不变（ADR-0018 §4）。
4. **不新增表结构迁移**：`event` 是 text 列、取值由应用层枚举维护，`0004` 已建
   `(event, called_at)` 索引，`discover` 复用同一套可靠落库、spool 补投与 30 天保留。
5. `notifications/*` 与 `ping` 仍不记录；`server/discover` 是现代协议连接漏斗的第一步，
   不属于通知。

## 备选与否决理由

- **只用 `tools/list` 近似连接数**：否决。列工具次数会把「一次连接列了多次工具」与多次连接
  混在一起，漏斗第一段的分母消失。
- **按凭据或客户端去重成唯一连接**：否决。现代协议请求无会话标识，且重连、换进程都是真实
  连接事件；去重会把它们藏起来。
- **把 `server/discover` 记为 `list_tools`**：否决。它发生在列工具之前、不返回工具数，
  合并后漏斗两段不可区分。
- **为现代协议新建 `connection` 事件表或独立列**：否决。复用 `event` 即可满足查询与索引，
  新增表会复制写入、spool 与保留期逻辑，且跨表聚合没有收益。

## 后果

- 现代客户端的连接数恢复可观测，`instructions` 的送达通道与连接事件同源、可核对。
- 连接数可能大于列工具数（探测成功但未列工具），这正是 ADR-0018 要暴露的「连上了却没看到
  工具」信号；转化率分母为 0 时仍记 `0.0`。
- 无迁移；历史行不受影响。切换前窗口里的现代连接无法补记，只能从本版本上线后开始累计。
- `kb_mcp_trace` 每次客户端建立连接多一行 `discover`（量级与 `initialize` 相同），纳入 P99
  观察；`docs/plans/mcp-trace-spec.md`、`docs/contracts/kb-admin-api.md` 与
  `docs/contracts/mcp-tools.md` 同步更新。
