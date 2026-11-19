---
created_at: '2026-11-18T07:26:22Z'
entity_kind: other
id: cloudworld/entity/cloud-world-de4a13
kind: entity
project: cloudworld
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: cloudworld/entities/cloud-world.md
  type: wiki
supersedes: []
tags:
- 命名
- 平台
tier: canonical
title: cloud-world
updated_at: '2026-11-18T07:26:22Z'
---

> 被选定的产品工程名，覆盖 memhub、magpie 及后续接入服务，要求仓库/crate/二进制/配置目录/凭据条目五层标识同构派生。

# 定义

`cloud-world` 是产品的工程名（platform 级标识），其语义覆盖 [[memhub]]、[[magpie]] 以及后续接入的服务。命名决策见 [[07-命名决策]]，判据见 [[产品命名判据]]。

它不只是"一个名字"，而是一整套标识的根：仓库、crate、二进制、配置目录、凭据条目都由它同构派生（见 [[标识同构派生]]）。

# 关键属性

- **描述性**：看到名字即可知道产品做什么（可检索性维度）。
- **可推导性**：所有工程标识均可由它机械派生，无需另起名字。
- **偏通用**：在 GitHub 等公共命名空间中重名概率不低，需靠组织前缀消歧。

# 派生标识清单

| 层 | 标识 |
| --- | --- |
| 仓库 | `cloud-world`（对外使用 `<org>/cloud-world`） |
| crate | `cloud-world-core` / `-api` / `-relay` / `-service` / `-cli` / `-desktop` |
| 二进制 | `cloud-world`（CLI）、`cloud-world-desktop` |
| 配置目录 | `%APPDATA%\cloud-world` |
| 凭据条目 | `cloud-world / <profile>:panel-user-key` |

约定：二进制派生形式为 `产品名` 或 `产品名-端类型`；crate 派生形式为 `产品名-职责`。

# 关系

- 覆盖（平台 ← 服务）：[[memhub]]、[[magpie]]，以及后续接入的服务。
- 判据来源：[[产品命名判据]] → 得出本命名。
- 标识规范：[[标识同构派生]] → 本页的派生标识清单即其落地实例。
- 风险与后果：[[命名漂移与迁移成本]] → 派生不一致的代价。
- 命名空间治理：仓库名加组织前缀（`<org>/cloud-world`）以规避通用名重名。
- 被否决候选：`Nature-reawakens`，仅保留作版本代号 / 界面主题名，见 [[工程名与代号分离]]。

# 待补充

- 六个 crate 的职责边界（本文仅给出标识派生，未描述模块划分）。
- `<profile>` 的语义（预期属于未来的权限 / 凭据模型）。
- 部署模型，以及配置目录 / 凭据条目在其中的位置。

# 发布前验证

`crates.io` 上搜索不到同名 crate 不等于未被占用，正式发布前必须执行 `cargo publish --dry-run` 验证。

# Citations

- 源文档：`07-命名决策.md`
