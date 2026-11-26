# ADR-0017 MCP 发现层事件并入调用轨迹，形成连接漏斗

| 属性 | 值 |
|:---|:---|
| 状态 | accepted |
| 日期 | 2026-11-26 |

## 背景

[ADR-0015](ADR-0015-mcp-call-trace.md) 让每次 `tools/call` 与鉴权/路由拒绝可查，但明确把 `initialize` 与 `tools/list` 排除在外，发现层指标留给后续设计。结果是只能回答「调用了多少次」，不能回答三个治理问题：

- 客户端连上了 MCP，但根本没列工具（配置或握手问题）；
- 列出了工具，但一次都没调用（工具描述、instructions 或渐进式披露问题）；
- 调用失败集中在哪些连接之后。

客户端会延迟下发工具 schema（progressive disclosure），「连上 → 列工具 → 调用」本身就是最关键的漏斗。只在调用端计数，会把「没人用」和「看到了却不用」混在一起，无法验收工具描述与 instructions 的任何改动。

## 决策

1. **复用 `kb_mcp_trace`，不新建表**：新增 `event`（`call` / `list_tools` / `initialize`）与 `tool_count`（`tools/list` 成功返回的工具数）；迁移 `0004_mcp_trace_funnel` 给历史行回填 `event=call`。发现层事件与调用共用同一套可靠落库、spool 补投与 30 天保留。
2. **记录点**：`tools/call` 仍由 `invoke` 记录；`initialize` 与 `tools/list` 由 SDK 的 context 中间件观察（SDK 只允许经中间件观察 `initialize`）。只记元数据：请求 id、JSON-RPC id、凭据 id/名称快照、`User-Agent`、工具数、耗时、状态；不记参数、正文、token。
3. **漏斗口径**：同一时间窗内，连接数 = `initialize` 成功行数，列工具数 = `tools/list` 成功行数，实际调用数 = `call` 的 `ok + error` 行数（拒绝不计入调用）；两段转化率的分母为 0 时记 `0.0`。
4. **列表语义不扩张**：`GET /api/v1/kb/mcp-traces` 默认 `event=call`，既有页面、筛选与分页保持原口径；发现层行通过显式 `event` 参数查询，汇总接口新增 `funnel` 区块。
5. `notifications/*` 与 `ping` 仍不记录；它们不属于漏斗中的任何一步。

## 备选与否决理由

- **新建 `kb_mcp_trace_event` 表**：会复制独立事务、重试、spool、保留期清理与查询代码，且漏斗要跨表聚合；两张表的一致性没有收益。
- **只在日志里打 `initialize` / `tools/list`**：能 grep 不能聚合，也无法与凭据、工具和调用串联，否决。
- **客户端 sidecar 上报发现行为**：覆盖不到 Codex 等其它客户端，也看不到服务端握手失败，否决。
- **把拒绝也算作调用**：漏斗会把「没通过鉴权」显示成「用了工具」，失真，否决。
- **把 `initialize` 按凭据去重成唯一客户端**：重连、换进程都会产生新连接，去重会隐藏真实连接次数；保持事件计数，客户端维度留待后续聚合。

## 后果

- `kb_mcp_trace` 每次连接与每次列工具各多一行小事务写入；量级远低于 `tools/call`，但仍纳入 P99 观察。
- `tool_count` 随凭据作用域变化（`mcp:read` 4 个、`mcp:write` 7 个），`avg_tools` 是混合值，不能当作「工具总数」。
- 30 天保留不变；需要更长周期仍应先做日聚合表，而不是延长明细。
- ADR-0015 正文不修改；本 ADR 只扩展其记录范围，数据模型与查询契约的细节以 [mcp-trace-spec](../plans/mcp-trace-spec.md) 为准。
