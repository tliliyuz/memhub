# 跨端契约（v0.9）

本目录是 **memhub 新架构**唯一的事实来源之一：客户端（agent-console / collector）、服务端、MCP 消费方都以此为准。改契约先改这里，再改实现。

> 适用范围：跨端契约索引与变更流程。
> 不负责：各契约的具体字段（见下表各文档）。

| 文档 | 内容 | 主要读者 |
|---|---|---|
| [node-schema.md](node-schema.md) | 知识节点 kind/entity_kind/边枚举、`kb_nodes` 字段、tier 治理、投影 | 服务端、治理 agent、MCP |
| [source-registry.md](source-registry.md) | `sources.json` 本地源注册表、采集器行为、隐私边界 | 客户端、collector |
| [ingest-api.md](ingest-api.md) | 游标、推送、心跳、错误码、限流、幂等 | 客户端、服务端 |
| [mcp-tools.md](mcp-tools.md) | 检索组 + 治理组工具、错误码、不变式 | agent、治理 agent、服务端 |
| [kb-admin-api.md](kb-admin-api.md) | 本地管理台 kb-api：知识库目录与子图、节点 CRUD、边编辑、回收站、审计、投影重建、并发与错误码 | 服务端、管理台前端 |

## 待定（阻塞项）

1. ~~设备注册流程~~ — 已定（0.2）：桌面端用已有凭据调 `POST /devices/register` 换 `device_token`，存 OS 凭据库；采集器只持 `device_token`，作用域仅 `/ingest/*`。不复用 PKCE，也不复用面板 `user_key`（无设备作用域、每用户 20 把、最后一把不可吊销）。
2. ~~sessions 源的项目归属~~ — 已定（0.5）：必须由用户在客户端明确选择并保存显式目标；服务端不从路径、source_id 或会话内容推断，不允许 `auto`。
3. **portal 去留**：`memhub.work/portal` 目前是一个静态页；重写 vhost 时若占用 `/`，需确认 portal 保留为 `/portal/` 还是撤掉。→ 责任人：用户
4. ~~MCP 接入形态~~ — 已定（0.4）：本地 `memhub mcp` 保留 stdio；远端由 kb-api 在 `/mcp` 提供无状态 Streamable HTTP，使用独立凭据、库范围与读写作用域（[mcp-tools.md](mcp-tools.md) §4）。不保留本地轻代理。
5. ~~同 device_id 重复注册~~ — 已定（0.3）：未吊销时幂等返回同一有效 token、不旋转；吊销后重新注册签发新 token 并解除吊销；自动轮换只由 `/devices/refresh` 触发。

## 变更记录

- 0.9 — 真源改为 PostgreSQL `kb_*`（ADR-0013）：节点、边、知识库登记不再以 markdown 为真源，markdown 仅一次性迁移源；`matched` 为 `bm25`，`revision` 为每次写入重算的 16 位 hex；MCP 写工具返回的 `commit` 恒为 `null`；采集目标的「已登记且活动」改读 `kb_projects`（`ingest-api.md` 0.7）。
- 0.8 — 候选区闭环：新增 `kb_update_candidate` 与 `kb_deprecate`（[mcp-tools.md](mcp-tools.md) 0.4），都要求 `expected_revision` 且只作用于 `tier=candidate`；`kb_read` 返回 `revision`；`NodeFrontmatter` 新增 `deprecated_reason`，`tier=deprecated` 允许「有替代节点」或「只有原因」（[node-schema.md](node-schema.md)）。canonical 修改与治理组其余工具仍关闭。
- 0.7 — MCP 开放第一个写工具 `kb_write_candidate`（[mcp-tools.md](mcp-tools.md) 0.3）：新增 `mcp:write` 作用域（隐含读），`tools/list` 按作用域裁剪；只创建 `tier=candidate`，slug 冲突、归一化正文哈希去重、证据必填、内容门槛与每日上限；写成功自动 commit。canonical 修改与治理组其余工具仍关闭。
- 0.6 — 采集目标边界收敛为「显式 + 已登记 + 活动」：移除设备—知识库授权文件与 `POST /ingest/projects` 建库代理；`400/1003` 的 `data.reason` 细分为 `missing` / `reserved` / `invalid` / `unregistered` / `inactive` / `target_conflict`；存储层不再隐式建库。
- 0.5 — 采集目标必须显式、已登记且按设备授权；列表只返回可写目标并标记 `writable_only`；会话证据门禁与队列复核规则收紧。
- 0.4 — MCP 首版定为四个只读工具；新增远端 `/mcp` 传输、独立只读凭据与库范围（`mcp-tools.md` 0.2）。
- 0.3 — 注册段补充：生产必须带 `user_key` 鉴权、`device_id` 生产必填（400/1002）、同 device_id 重复注册幂等、吊销后重注册签发新 token；`source-registry` 明确 `base_url` 必须与签发 token 的服务器一致；示例中的 `device_id` 统一改为 UUID v4。
- 0.2 — 按客户端评审修订：device token 作用域与注册流程、游标加 `size/mtime/source_rev`、`code` 非 HTTP 状态、batch 幂等 24h + 200 重放、退避抖动与不丢数据、令牌不落盘、Windows reparse/offline 跳过。
- 0.1 — 初稿：节点 schema、源注册表、采集 API。
