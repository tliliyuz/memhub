---
created_at: '2026-11-18T07:26:22Z'
entity_kind: other
id: memory-hub/entity/start-proxy
kind: entity
project: memory-hub
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: memory-hub/entities/start-proxy-启动脚本.md
  type: wiki
supersedes: []
tags:
- 启动脚本
- 配置生成
- 挂载
tier: canonical
title: start-proxy 启动脚本
updated_at: '2026-11-18T07:26:22Z'
---

> TencentDB-Agent-Memory-local/start-proxy.sh，从 .env 生成 .proxy-config/config.yaml 再挂载进容器，是 Proxy 配置生效的唯一通道。

# 定义

`TencentDB-Agent-Memory-local/start-proxy.sh` 是 [[Memory Proxy]] 的启动脚本。它的核心行为是：**从 `.env` 生成 `.proxy-config/config.yaml`，再把该文件挂载进容器**（容器内路径 `/data/config.yaml`，Proxy 启动参数 `--config /data/config.yaml`）。

因为 Proxy **没有任何环境变量覆盖通道**，这个脚本是配置生效的**唯一途径**——改完 `.env` 必须重跑脚本，否则改动不生效。

# 关键属性

| 属性 | 值 |
|---|---|
| 路径 | `TencentDB-Agent-Memory-local/start-proxy.sh` |
| 输入 | `.env` |
| 产物 | `.proxy-config/config.yaml`（挂载为 `/data/config.yaml`） |
| 启动命令 | `MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*' ./start-proxy.sh`（Git Bash 下必须带这两个变量） |
| 健康输出 | `[ok] tdai-proxy healthy` —— 只探端口，不校验上游 |

# 生成配置的开关语义

`.env` 中缺少 `PROXY_ENABLE_*` 时，脚本会生成一份**全关闭**的配置，记忆注入直接失效。因此必须显式写入：

```env
PROXY_FULL_STACK=1
PROXY_ENABLE_AUTH=1
PROXY_ENABLE_TDAI=1
PROXY_ENABLE_SESSION_INIT=1
```

生成结果须满足 `config.yaml` 中 `tdai.enabled / auth.enabled / sessionInit.enabled / knowledge.enabled` 全为 `true`。详见 [[能力开关显式固化]]。

# 典型故障

1. **Git Bash MSYS 路径转换**：`-v D:\path\config.yaml:/data/config.yaml` 的 `D:` 被误认为路径分隔符，挂载源被拼成 `...config.yaml;C:\Program Files\Git\data\config.yaml`，容器内 `/data/config.yaml` 不存在 → 日志 `config not found — falling back to DEFAULT_CONFIG` → 上游变成占位地址 → **全部 502，但容器仍 `healthy`**。
2. **忘记重跑脚本**：只改 `.env` 不重跑，配置不变。

# 自检

- `docker exec tdai-proxy head -5 /data/config.yaml` —— 能读到内容才对。
- `docker inspect tdai-proxy` 的 `Mounts.Source` 应是 `/d/workplace/...` 形式（而非含 `;C:\Program Files\Git` 的拼接串）。
- 更完整的排障分支见 [[静默失效与健康检查盲区]] 与 [[Proxy 转发故障分段定位]]。

# 回滚

备份 `.env.bak.20261110`、`.proxy-config/config.yaml.bak.20261110`；回滚后重跑脚本（带 MSYS 变量）并重启 [[DSH Desktop]]。

# 关系

- 服务于 [[Memory Proxy]]。
- 与 [[能力开关显式固化]]、[[本地部署拓扑与回环绑定]] 直接相关。

# Citations

- `memhub-magpie-级联配置手册.md` §3.3、§3.4、§4.1、§4.2、§8
