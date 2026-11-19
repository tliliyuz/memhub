---
created_at: '2026-11-18T07:26:22Z'
entity_kind: other
id: cloudworld/entity/nsis
kind: entity
project: cloudworld
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: cloudworld/entities/nsis-安装包.md
  type: wiki
supersedes: []
tags:
- 安装包
- 发布物
- nsis
tier: canonical
title: NSIS 安装包
updated_at: '2026-11-18T07:26:22Z'
---

> 只把 exe 包一层的外壳发布物；exe 变了安装包就得重出，发版必须同步升 tauri.conf.json 的 version。

# 定义

NSIS 安装包是 [[打包分层模型]] 的第二层：它本身不含业务逻辑，只是把 [[cloud-world.exe]] 包装成一个可安装的外壳（`tauri.conf.json` 中的 nsis 打包目标）。

# 关键属性

| 属性 | 说明 |
| --- | --- |
| 内容 | 仅包裹 exe，不包含配置与凭据 |
| 更新触发 | exe 变了安装包就得重出 |
| 已装机器升级 | 重跑安装包，或直接覆盖 exe |
| 版本管理 | 必须同步升 `tauri.conf.json` 的 `version`，否则新旧版本号相同，升级与卸载记录会混 |

# 版本管理规则（易错点）

发安装包时忘记升 `version`，会导致新旧安装包版本号一致，系统升级路径与卸载记录混淆。这条规则是发版检查项，不单独立概念页。

# 关系

- 包裹 [[cloud-world.exe]]。
- 属于 [[打包分层模型]] 中的「重出安装包」层，与「重编 exe」「改配置重启」区分。
- 配置与凭据不放安装包内，见 [[运行期配置与凭据分离]]。

# Citations

- `crates/desktop/src-tauri/tauri.conf.json`（nsis 目标、`version`）
