# 治理配置契约

| 适用范围 | 消费仓的 `governance.toml`、受管入口块、契约文档与初始化/同步流程 |
| 不负责 | 各仓业务规范与目录结构；检查器实现与 L0 规则文本见治理平台仓库 |

本文件由治理平台打包到消费仓，与平台版本逐字一致。仓内编辑会在 `verify` 时
被判为漂移；需要更新时运行 `governance sync`，不要手改。

## 1. 文件归属

| 文件 | 归属 | 维护方式 |
|---|---|---|
| `governance.toml` | 消费仓 | owner 手工维护，只写本仓差异 |
| `docs/contracts/governance-toml.md` | 平台 | `init` / `sync` 写入，勿手改 |
| `docs/guides/SDD.md`、`docs/guides/DOCUMENT_GOVERNANCE.md`、`docs/guides/DOCUMENT_FORMAT.md`、`docs/tech/TIME_CONVENTIONS.md` | 平台 | `init` / `sync` 逐字写入，勿手改 |
| `AGENTS.md`、`CLAUDE.md` 的主题受管块 | 平台 | `init` / `sync` 写入，块外内容归 owner |
| `docs/guides/DEVELOPMENT.md` 的 `verification`、`resources` 受管章节 | 平台 | `sync` 只替换章节块内，块外归 owner |
| `.claude/commands/review.md` 的 `review` 块 | 平台 | `init` / `sync` 写入，块外内容归 owner |
| `.claude/hooks/guard-git-write.py` | 平台 | `init` / `sync` 写入，勿手改 |
| 其余文档与代码 | 消费仓 | owner 手工维护 |

## 2. 配置分层与合并

治理规则分三层，消费仓只声明自己的差异：

| 层 | 载体 | 内容 |
|---|---|---|
| L0 基线 | 平台 `policy/` | 所有仓共同遵守的文本规则，不可按仓裁剪 |
| L1 技术包 | 平台 `packs/<pack>.toml` | 工具链命令与原子层默认值 |
| L2 仓库事实 | 消费仓 `governance.toml` | 排除前缀、文档清单、层覆盖、时区等差异 |

合并规则：同名键以 L2 覆盖 L1；`[atomic]` 与 `[time]` 按段合并；未声明的键回落到
默认值。顶层键必须写在任何 `[段]` 之前（TOML 规则）；误写进 `[checks]` 的顶层键
会被兼容读取，但不作为新配置的写法。

平台侧的 `policy/manifest.toml` 是分发内容的唯一清单（入口短文本、整份受管文档、
受管章节、宿主与一次性骨架）。清单不随 `init` 下发，消费仓只维护自己的
`governance.toml` 差异。

## 3. 键清单

| 键 | 类型 | 默认 | 含义 |
|---|---|---|---|
| `[repo] name` | 字符串 | 仓库目录名 | 仓库标识 |
| `[repo] pack` | 字符串 | `python-service` | 选择 L1 技术包 |
| `excluded_prefixes` | 字符串数组 | `[]` | 不参与文档结构检查的目录前缀 |
| `numbered_docs` | 字符串数组 | `[]` | H2 必须连续整数编号的文档 |
| `authority_docs` | 字符串数组 | `[]` | 需在正文前声明「适用范围」「不负责」的文档 |
| `history_docs` | 字符串数组 | `["docs/CHANGELOG.md"]` | 允许出现实施日期与提交证据的文档 |
| `deprecated_docs` | 字符串数组 | `[]` | 不允许新增内容的文档 |
| `decisions_dir` | 字符串 | `docs/decisions` | ADR 目录 |
| `env_example` | 字符串 | `.env.example` | 环境键清单文件 |
| `environment_doc` | 字符串 | `docs/tech/ENVIRONMENT.md` | 环境变量权威文档 |
| `[checks] <name>` | 布尔 | 启用 | 显式写 `false` 才关闭对应检查 |
| `[entrypoints] max_lines` | 整数 | `120` | 入口文件总行数上限（`entry_budget`） |
| `[entrypoints] max_owner_lines` | 整数 | `40` | 「## 本仓专属」行数上限 |
| `[atomic] max_implementation_layers` | 整数 | `1` | 单次提交允许的实现层数 |
| `[atomic] closing_layers` | 字符串数组 | `["tests", "docs"]` | 可与实现层同提交的收尾层 |
| `[[atomic.layer]]` | 表数组 | 技术包默认值 | 文件到实现层的映射（`name` + `patterns`） |
| `[toolchain]` | 字符串表 | 技术包默认值 | 工具链命令，供 CI 与文档引用 |
| `[time] business_timezone` | 字符串 | 空 | 本仓唯一业务时区；声明后启用 `time_conventions` |
| `[time] allow_paths` | 字符串数组 | `[]` | 时区检查的追加豁免 |
| `[[time.forbid]]` | 表数组 | `[]` | 追加的时区禁用规则（`pattern` / `globs` / `message`） |

`[time]` 段的键必须写在 `[[time.forbid]]` 之前（TOML 规则）。时区检查未声明
`business_timezone` 时整体跳过，便于未迁移仓库渐进接入；其余检查默认启用。

## 4. 初始化与同步

```text
python <平台路径>/governance.py init --repo <目标仓>
python <平台路径>/governance.py sync --repo <目标仓>
```

- `init`：按 `policy/manifest.toml` 生成 `governance.toml` 初稿（`[repo] name` 取
  目标目录名）、写入本契约文档与四份通用标准文档、搭建骨架文档集（含
  `docs/tech/OPERATION_TIME.md`）、填充 `DEVELOPMENT` 的受管章节、写入
  `.pre-commit-config.yaml`，并注入入口与审查命令的受管块。重复执行不产生改动。
- `sync`：按清单把受管内容更新到平台当前版本，不改 `governance.toml`、骨架文档
  与受管块之外的正文。未初始化时报错，先运行 `init`。
- `.pre-commit-config.yaml` 缺失时由 `init` 写入；已存在时不改写。安装 git 钩子
  需执行 `pre-commit install` 与
  `pre-commit install --hook-type commit-msg --hook-type pre-push`。

## 5. 漂移门禁

- `manifest_complete`：清单声明的入口条目、受管文档与受管章节的源文件必须存在且
  非空；每个宿主的主题集合、每个章节宿主的主题集合与清单完全一致，未登记块与
  缺失块都报错；骨架必须有对应模板。
- `contract_pack`：本文件、四份通用标准文档、guard 钩子副本与平台版本逐字一致；
  两个入口文件的主题块、`DEVELOPMENT` 的受管章节与平台模板一致；
  `.claude/commands/review.md` 存在时，其 `review` 块同样校验（文件缺失不报错）。
  不一致时提示运行 `governance sync`。
- `entrypoints`：`AGENTS.md` 与 `CLAUDE.md` 必须逐字节一致。
- `entry_budget`：入口总行数不超过 `[entrypoints] max_lines`；受管块外的二级标题
  只允许「## 本仓专属」，且该块不超过 `max_owner_lines`。通用标准放 `docs/`，入口
  只保留硬约束与索引。
- 主题块由 `<!-- governance:<主题> begin -->` 与 `end` 界定；入口承载 `intro`、
  `core`、`hard-constraints`、`doc-matrix` 四个主题，审查命令另承载 `review` 块；
  受管章节使用 `<!-- governance:section:<主题> begin -->`。

## 6. 升级流程

1. 平台更新规则、检查或本契约文本。
2. 各消费仓运行 `governance sync`，刷新受管内容。
3. 按 `verify` 的失败清单修本仓代码；修复动作归 owner。
4. 全量 `verify` 通过后提交。

## 7. 手改边界

通用规范只在平台定义，消费仓不复制、不本地改写。入口短文本住在平台的
`policy/entry/`，受管章节住在 `policy/sections/`，新增或修改时必须同时更新
`policy/manifest.toml`，再由各仓 `sync`。本仓确实需要的差异写成配置键（如
`[time] allow_paths`、`excluded_prefixes`）或块外正文；需要新的通用规则时，先在
平台登记条目并增加检查，再由各仓同步，避免各仓各自定义造成不一致。