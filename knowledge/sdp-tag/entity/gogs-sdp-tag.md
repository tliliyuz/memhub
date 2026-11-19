---
created_at: '2026-11-18T07:26:22Z'
entity_kind: external_system
id: sdp-tag/entity/gogs-sdp-tag
kind: entity
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/entities/gogs-sdp-tag.md
  type: wiki
supersedes: []
tags:
- Git
- Gogs
- 代码仓库
tier: canonical
title: gogs-sdp-tag
updated_at: '2026-11-18T07:26:22Z'
---

> Gogs 代码仓库 http://git.applesay.cn/hu.jingchao/sdp-tag.git（0.11.79，无 wiki），多会话/多人共享，凭据只在 Windows 凭据管理器。

# gogs-sdp-tag

## Definition

sdp-tag 的私有代码仓库（Gogs 自建）。

## Key Attributes

| 项 | 值 |
| --- | --- |
| 远端 | `http://git.applesay.cn/hu.jingchao/sdp-tag.git` |
| 版本 | Gogs 0.11.79（**无 wiki**） |
| 凭据存放 | Windows 凭据管理器 `LegacyGeneric:target=git:http://git.applesay.cn`，用户 `yu.zhen` |
| 大提交 | 远端 502 → `git -c http.postBuffer=524288000 push origin dev`（**只对单条命令生效**） |

## Relationships

- **托管内容**：[[sdp-tag-backend]] 源码、`deploy/k8s/*.yaml`、`script/sql/`
- **历史成因**：untracked 清单问题见 [[deployment-manifest-drift]]
- **凭据风险**：明文凭据已进 git 历史 → [[credential-leak-and-rotation]]

## 已知问题

- ⚠️ **沙箱下 GCM / `git-credential-wincred` 读不到该凭据**（「安全包中没有可用的凭证」），但端口连通、接口正常返回 401 → **纯凭据读取被环境限制**
- ⚠️ **仓库是共享的** `[Z]`：多会话/多人同时使用。合并前必须 `git status -sb` + `git log --oneline -1` 确认分支
- 账密**没有落进仓库**，只在凭据管理器（这一项 ✅）
- 🔴 但 RDS/ACR 口令、图谱导出 API Key、LLM key 默认值**已进 git 历史**

## Citations

- §8 Git
- §0 P0-1 / P0-2
