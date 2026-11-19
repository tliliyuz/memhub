---
created_at: '2026-11-18T07:26:22Z'
id: memory-hub/fact/stdio-mcp
kind: fact
project: memory-hub
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: memory-hub/concepts/stdio-mcp-分发与启动约束.md
  type: wiki
supersedes: []
tags:
- mcp
- stdio
- 打包
- 分发
- 启动
tier: canonical
title: stdio MCP 分发与启动约束
updated_at: '2026-11-18T07:26:22Z'
---

> stdio MCP server 由客户端以子进程方式拉起，其可用性取决于分发产物是否自包含、command 是否绝对路径、以及宿主进程的 PATH 与 node_modules 解析规则。

# stdio MCP 分发与启动约束

## 定义

stdio 型 MCP server 不是常驻服务，而是**由客户端以子进程方式 spawn** 的可执行入口（通常是 `node <server.js>`）。因此它没有端口、没有健康检查端点，其「能不能用」完全取决于三件事：分发产物是否自包含、启动命令能否被解析、宿主进程的运行环境是否与开发者的 shell 一致。

## 意义

这类约束造成的失败**全部表现为启动即静默退出**，客户端只看得到 `Connection closed` 或干脆什么都不发生——与 [[Windows ESM 入口判断失效]] 属于同一类症状。不了解规律就会把打包问题误判成代码 bug。

## 三条核心约束

| 约束 | 反例 | 正确做法 |
|---|---|---|
| 分发产物必须**自包含** | `--packages=external` 打包，部署目录无 `node_modules` → `ERR_MODULE_NOT_FOUND` | 全量打包含 `@modelcontextprotocol/sdk`，单文件约 610KB |
| `command` 必须用**绝对路径** | GUI 启动的客户端进程 PATH 不含 shell 里的 `node`，写 `node` spawn 失败 | `command: "D:/develop/nodejs/node.exe"` |
| 插件/依赖解析可能走**宿主 app 目录** | 误以为 profile 缺 `node_modules` 就不能加载插件 | 先验证宿主已有同类插件能加载，再判断是否需要额外安装 |

## Examples

[[Team Brain MCP]] 的分发与启动：

```bash
cd team-brain-mcp
npm install --omit=dev      # 只装运行依赖
node dist/mcp/server.js     # 应打印 MCP server connected via stdio
```

从源码重建（`TencentDB-Agent-Memory/MemoryKnowledge`）：`pnpm install && pnpm build`（tsdown 产出 `dist/mcp/server.js`）。

在 [[DSH Desktop]] 中通过 [[DSH Cordis 插件式 MCP 接入]] 拉起时，`config.command` 必须写绝对路径，`args` 指向 `server.js` 绝对路径，并配 `toolCallTimeoutMs` / `failOnStartupError`。

## 相关概念

- [[MCP 双后端只读接入]] —— 分发之后真正决定可用性的是后端路由与鉴权
- [[本地部署拓扑与回环绑定]] —— stdio 子进程不监听端口，只回连 `127.0.0.1:8424` / `127.0.0.1:8125`
- [[静默失效与健康检查盲区]] —— 启动失败没有 `/health` 可探，只能靠客户端日志与实际工具调用
- [[Windows ESM 入口判断失效]] —— 同属「启动即静默退出」

## Citations

- `team-brain-mcp-接入指南.md` 第 4、8.4 节
