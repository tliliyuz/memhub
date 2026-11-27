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
| `AGENTS.md`、`CLAUDE.md` 的受管块 | 平台 | `init` / `sync` 写入，块外内容归 owner |
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

- `init`：生成 `governance.toml`（缺失时）、写入本契约文档、向两个入口文件注入
  受管块。重复执行不产生改动。
- `sync`：把契约文档与受管块更新到平台当前版本，不改 `governance.toml`，也不改
  受管块之外的内容。未初始化时报错，先运行 `init`。
- 钩子不自动改写：`governance hooks` 输出三层配置，合并进
  `.pre-commit-config.yaml` 后执行 `pre-commit install`。

## 5. 漂移门禁

- `contract_pack`：本文件与平台版本逐字一致；两个入口文件的受管块存在且与平台模板
  一致。不一致时提示运行 `governance sync`。
- `entrypoints`：`AGENTS.md` 与 `CLAUDE.md` 必须逐字节一致。
- 受管块由 `<!-- governance:contract begin -->` 与
  `<!-- governance:contract end -->` 界定，块内只放平台生成的引用。

## 6. 升级流程

1. 平台更新规则、检查或本契约文本。
2. 各消费仓运行 `governance sync`，刷新受管内容。
3. 按 `verify` 的失败清单修本仓代码；修复动作归 owner。
4. 全量 `verify` 通过后提交。

## 7. 手改边界

通用规范只在平台定义，消费仓不复制、不本地改写。本仓确实需要的差异写成配置键
（如 `[time] allow_paths`、`excluded_prefixes`）或追加规则；需要新的通用规则时，
先在平台增加检查与规则文本，再由各仓同步，避免各仓各自定义造成不一致。