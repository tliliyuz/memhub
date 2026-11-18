# 跨端契约（v0.1 草案）

本目录是 **memhub 新架构**唯一的事实来源之一：客户端（agent-console / collector）、服务端、MCP 消费方都以此为准。改契约先改这里，再改实现。

| 文档 | 内容 | 主要读者 |
|---|---|---|
| [node-schema.md](node-schema.md) | 知识节点 kind/entity_kind/边枚举、frontmatter、tier 治理、投影 | 服务端、治理 agent、MCP |
| [source-registry.md](source-registry.md) | `sources.json` 本地源注册表、采集器行为、隐私边界 | 客户端、collector |
| [ingest-api.md](ingest-api.md) | 游标、推送、心跳、错误码、限流、幂等 | 客户端、服务端 |
| [mcp-tools.md](mcp-tools.md) | 检索组 + 治理组工具、错误码、不变式 | agent、治理 agent、服务端 |

## 待定（阻塞项）

1. ~~设备注册流程~~ — 已定（0.2）：桌面端用已有凭据调 `POST /devices/register` 换 `device_token`，存 OS 凭据库；采集器只持 `device_token`，作用域仅 `/ingest/*`。不复用 PKCE，也不复用面板 `user_key`（无设备作用域、每用户 20 把、最后一把不可吊销）。
2. **sessions 源的项目归属**：Claude Code 的 `projects/<encoded-path>` 能否可靠映射到知识库 `project`。当前按 `auto` 留给云端推断。
3. **portal 去留**：`memhub.work/portal` 目前是一个静态页；重写 vhost 时若占用 `/`，需确认 portal 保留为 `/portal/` 还是撤掉。→ 责任人：用户
4. **MCP 接入形态**：远端 SSE/HTTP 还是本地 stdio + 服务端 API。倾向：远端 HTTP（`/mcp`），本地仅留一个轻代理用于无公网场景。
5. ~~同 device_id 重复注册~~ — 已定（0.3）：未吊销时幂等返回同一有效 token、不旋转；吊销后重新注册签发新 token 并解除吊销；自动轮换只由 `/devices/refresh` 触发。

## 变更记录

- 0.3 — 注册段补充：生产必须带 `user_key` 鉴权、`device_id` 生产必填（400/1002）、同 device_id 重复注册幂等、吊销后重注册签发新 token；`source-registry` 明确 `base_url` 必须与签发 token 的服务器一致；示例中的 `device_id` 统一改为 UUID v4。
- 0.2 — 按客户端评审修订：device token 作用域与注册流程、游标加 `size/mtime/source_rev`、`code` 非 HTTP 状态、batch 幂等 24h + 200 重放、退避抖动与不丢数据、令牌不落盘、Windows reparse/offline 跳过。
- 0.1 — 初稿：节点 schema、源注册表、采集 API。