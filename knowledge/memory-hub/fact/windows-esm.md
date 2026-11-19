---
created_at: '2026-11-18T07:26:22Z'
id: memory-hub/fact/windows-esm
kind: fact
project: memory-hub
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: memory-hub/concepts/windows-esm-入口判断失效.md
  type: wiki
supersedes: []
tags:
- nodejs
- node
- esm
- windows
- 静默失效
- 启动失败
- 静默退出
- 踩坑
tier: canonical
title: Windows ESM 入口判断失效
updated_at: '2026-11-18T07:26:22Z'
---

> Node ESM 用 import.meta.url === `file://${process.argv[1]}` 判断「是否直接运行」在 Windows 反斜杠路径下永不相等，进程启动即静默退出，客户端只见 Connection closed；修复为 pathToFileURL(process.argv[1]).href。

# Windows ESM 入口判断失效

## Definition / 定义

Node 的 ESM 脚本常用下面这行判断「当前模块是否被直接运行」（等价于 CJS 的 `require.main === module`）：

```js
if (import.meta.url === `file://${process.argv[1]}`) {
  main();
}
```

在 **Windows** 上，`process.argv[1]` 是反斜杠路径（例如 `D:\...\server.js`、`D:\workplace\...\server.js`），拼出来的 `file://D:\...` 与 `import.meta.url`（`file:///D:/.../server.js`、`file:///D:/workplace/.../server.js`）形式的 URL **永不相等**，于是 `main()` / 入口分支从不执行，进程启动后立即静默退出。

## Significance / 意义

- 对 [[Team Brain MCP]] 而言，后果是 **stdio MCP server 启动后静默退出**：进程一度存在、没有任何错误输出、没有异常抛出、没有日志，客户端只看到 `Connection closed`。
- 这是一个典型的 [[静默失效与健康检查盲区]] 案例：没有异常日志、没有非零退出码，端口/进程层面的健康检查完全无法发现；也容易被误判为「配置写错」或「网络问题」。
- **任意 Windows 机器上均可复现**，与具体客户端无关，不是环境偶发问题。

## 修复

改用 `pathToFileURL` 把路径正规化为 URL 再比较：

```js
import { pathToFileURL } from 'node:url';

if (import.meta.url === pathToFileURL(process.argv[1]).href) {
  main();
}
```

`pathToFileURL()` 会做正确的盘符与分隔符归一化，产出与 `import.meta.url` 同构的 URL。

该问题在 [[Team Brain MCP]] 中已修复。

## Examples / 示例

[[Team Brain MCP]] 的 `dist/mcp/server.js` 曾使用错误写法，导致：

- DSH / Codex 等客户端接入后，server 子进程秒退。
- 客户端侧唯一线索是 `Connection closed`。
- 修复后 `node dist/mcp/server.js` 能打印 `MCP server connected via stdio`。

其它可能被同一坑点波及的入口见 [[stdio MCP 分发与启动约束]]。

## Related

[[Team Brain MCP]] · [[静默失效与健康检查盲区]] · [[本地部署拓扑与回环绑定]]（Windows 宿主机前置条件） · [[stdio MCP 分发与启动约束]]

## Citations

- `team-brain-mcp-接入指南.md` §6.1（第 6.1 节）
