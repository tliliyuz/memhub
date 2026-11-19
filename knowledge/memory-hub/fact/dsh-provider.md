---
created_at: '2026-11-18T07:26:22Z'
id: memory-hub/fact/dsh-provider
kind: fact
project: memory-hub
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: memory-hub/concepts/dsh-双-provider-体系与设置覆盖层.md
  type: wiki
supersedes: []
tags:
- dsh
- 配置
- provider
- 覆盖层
- 配置覆盖
- cordis
tier: canonical
title: DSH 双 Provider 体系与设置覆盖层
updated_at: '2026-11-18T07:26:22Z'
---

> DSH 界面展示与模型清单由 llm-deepseek 决定，llm-pi-ai 是另一套多 provider 容器；~/.dsh/settings.yaml 优先级高于 cordis.patch.yml 并可能在重启时被重写。

# DSH 双 Provider 体系与设置覆盖层

## 定义

[[DSH Desktop]] 内部同时存在**两套 provider 体系**，外加一层**设置覆盖层**，三者共同决定「界面上能看到什么模型」：

| 插件 | 用途 | 界面是否展示 |
|---|---|---|
| `llm-deepseek` | 单 provider，`baseURL` 直指 8096，自带 `models` 列表 | ✅ 这是「DeepSeek / deepseek-official」 |
| `llm-pi-ai` | 多 provider 容器（tokenhub / memory-proxy / magpie…） | 取决于 `settings.yaml` |

换言之：

- **`llm-deepseek`** —— 决定界面展示与模型清单
- **`llm-pi-ai`** —— 另一套多 provider 容器

两套体系的 schema 不同，不能混抄：

```yaml
# llm-deepseek 用列表字段
inputModalities: [text, image]
# llm-pi-ai 用标量字段 —— schema 不同，不能混抄
input: ...
```

## 设置覆盖层

`~/.dsh/settings.yaml` 是**设置覆盖层**，优先级高于 `~/.dsh/profiles/desktop/cordis.patch.yml`，且 DSH 重启时可能按界面当前状态**重写**它。

- `settings.yaml.imported` 存在 → 说明做过一次性导入迁移。
- 重启后配置丢失时，先看 `settings.yaml` 的时间戳是否晚于你的改动。

## 显著性（改配置的正确姿势）

1. **改「界面读的那一层」**：要动 `llm-deepseek`。改完 `llm-pi-ai` 的 providers，界面纹丝不动——这是最常见的「白改」。
2. **避开会被覆盖的层**：优先用 `llm-deepseek` 这条，因为它不在 `settings.yaml` 里，不会被重写；改完需确认 `settings.yaml` 中**不含** `llm-deepseek` 段。

## 意义

这解释了「改了 `cordis.patch.yml` 却不生效」的一大类现象——修改可能被更高优先级的覆盖层冲掉，而重启前一切看起来都正常，属于 [[静默失效与健康检查盲区]] 的配置侧样本。

## 与 MCP 接入的交集（2026-11-10 新增）

[[DSH Cordis 插件式 MCP 接入]] 同样把配置写进 `~/.dsh/profiles/desktop/cordis.patch.yml` 的顶层 entry 列表，与 provider 覆盖配置是**同一文件的写入方**。

因此产生一个**待确认问题**：

> MCP 的插件 entry（`@deepseek-ai/dsh-mcp-client`）是否也会被 `settings.yaml` 覆盖或在重启时被重写冲掉？

目前已知：重启 DSH 后 19 个 `mcp__team_brain__*` 工具确实出现过，但尚未验证「改过 settings.yaml 后是否仍保留」。

## 相关实体

- [[DSH Desktop]]
- [[Memory Proxy]]（`baseURL` 指向的 8096 入口）
- [[Magpie]]（模型清单来源）

## 相关概念

- [[DSH Cordis 插件式 MCP 接入]] —— 同一文件的另一类 entry
- [[静默失效与健康检查盲区]] —— 覆盖层导致的静默不生效
- [[模型-id-解析与路由组|模型 ID 解析与路由组]] —— provider 层的模型选择

## 常见话题

- 权限/凭据模型：见 [[凭据分层模型]]
- 模型 id 写法：见 [[模型-id-解析与路由组|模型 ID 解析与路由组]]

## Citations

- `memhub-magpie-级联配置手册.md` §3.5、§4.4、§4.5
- `team-brain-mcp-接入指南.md` 第 8.3、8.5 节
