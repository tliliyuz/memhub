# memhub Agent 指南

<!-- governance:intro begin -->
本文件是 Agent 入口：只保留核心规范、硬性约束与权威文档矩阵。通用规范由
governance-platform 维护：`AGENTS.md` 与 `CLAUDE.md` 必须逐字节一致，受管块由
`governance sync` 写入，块外「本仓专属」归本仓所有；入口行数与块外结构受门禁约束。
<!-- governance:intro end -->

<!-- governance:core begin -->
## 1. 核心规范

- 任何业务行为先有可审查的规范，再由测试转成可验收条件，最后才写实现；流程、RED/GREEN 规则与 ADR 检查见 [SDD 指南](docs/guides/SDD.md)。
- 修改任何 Markdown 前完整阅读 [DOCUMENT_FORMAT](docs/guides/DOCUMENT_FORMAT.md) 与 [DOCUMENT_GOVERNANCE](docs/guides/DOCUMENT_GOVERNANCE.md)，改后按 [DEVELOPMENT](docs/guides/DEVELOPMENT.md) 的验证矩阵执行检查。
- 任何问题先按第一性原理归因并消除产生机制；长期事实当次落盘；接消息先判断意图，诊断只给结论，明确要求变更才动手。
<!-- governance:core end -->

<!-- governance:hard-constraints begin -->
## 2. 硬性约束

以下约束依赖人工判断兜底，机械检查无法完全覆盖。

- 密钥、token、口令只经 `.env` 注入，禁止进入仓库、文档与提交信息；新增 `.env.example` 键时同次写入本机 `.env`，值未知留空，不猜测值。
- Git 本地写操作（提交、合并、变基、切换、worktree、分支与标签管理）一律直接执行，不征求负责人确认；仅远端操作需要针对当前操作明确授权。
- 单次提交至多一个实现层，tests 与 docs 收尾层可同提交；提交信息用中文描述实际改动，不加工具署名行。
- 权威文档在正文前声明适用范围与不负责，实施历史只进 ADR/CHANGELOG，弃用文档不得新增内容；密钥值不进 Markdown。
- 会话正文、用户内容与原始观测只进本仓真源，禁止硬编码进源码、测试或文档；真源位置在本仓专属声明。
- 存储与接口使用 UTC ISO 8601 绝对时刻与带时区时间列；业务时区在 `governance.toml` 声明，展示必须显式转换。细则见 `docs/tech/TIME_CONVENTIONS.md`。
- `main` 只接受负责人授权的合入，`dev` 是集成分支；修改从 `dev` 拉独立分支与 `git worktree`，验收后立即 `--no-ff` 合回 `dev` 并删除分支与 worktree。
- 只改当前任务与已确认规范覆盖的范围；背景与进入条件以权威文档状态为准；新增依赖先说明用途、维护状态、体积与替代方案。
- 未经批准不新增权威文档；临时规格与验收记录只放 Git 忽略目录；注释、文档与提交信息用中文，代码标识符用英文。
- 浏览器验收与资源占用按 DEVELOPMENT 的受管章节执行，单 space、单标签、用完关闭，不占用负责人正在使用的会话。
- 代码审查用 `/review` 按需触发，口径见 `.claude/commands/review.md`；它不是合并前置门禁。
<!-- governance:hard-constraints end -->

<!-- governance:doc-matrix begin -->
## 3. 权威文档矩阵

开始任务前按变更范围读取对应文档；目标文档尚未建立时先补规范，不得在无规范情况下推断设计。下表是平台保证存在的权威来源；本仓独有的真源在入口文件块外补充。

| 主题 | 唯一权威来源 |
|---|---|
| 系统拓扑、组件职责与关键机制 | `docs/tech/architecture.md` |
| 对外契约 | `docs/contracts/`（`README.md` 为索引） |
| 规范驱动开发：ADR 检查、规格、验收测试与最小实现 | `docs/guides/SDD.md` |
| 环境变量：键名、读取方与失败语义 | `docs/tech/ENVIRONMENT.md` |
| 开发环境、命令、验证矩阵、提交粒度、分支闭环 | `docs/guides/DEVELOPMENT.md` |
| 文档标题、编号、模板与冗余边界 | `docs/guides/DOCUMENT_FORMAT.md` |
| 文档归属、冲突裁决、事实状态与入口镜像 | `docs/guides/DOCUMENT_GOVERNANCE.md` |
| 时间与时区：存储、解析、展示与业务时区 | `docs/tech/TIME_CONVENTIONS.md` |
| 业务运行周期、幂等键与业务日边界 | `docs/tech/OPERATION_TIME.md` |
| 重要架构决策 | `docs/decisions/README.md`（治理规则与索引；具体决策 `ADR-NNNN-*.md`） |
| 行为变更记录（按日期追加） | `docs/CHANGELOG.md` |

文档冲突或实现领先于规范时，不自行选择方便实现的一方：先输出裁决候选并取得负责人有效裁决。
<!-- governance:doc-matrix end -->

## 本仓专属

> 本节由 `governance sync` 跳过，只写本仓差异。

- 真源：PostgreSQL `kb_*` 表（ADR-0013）；`raw_store/`、`knowledge/` 只是迁移源，运行时不读取。
- 拓扑与模块：`docs/tech/architecture.md`；目录归属见 DEVELOPMENT §2。
- worktree 只用单数 `.claude/worktree/<主题>`，由 `git worktree add` 创建；禁用 `EnterWorktree`（其托管根为复数路径）。
- 页面验收用 ego-lite：只用一个 space、同一标签内分步导航，结束关闭本次打开的全部标签页与自启进程。
- 生产服务器 43.142.18.23 的变更走负责人授权；仓库不保存部署凭据。
- MCP 工具契约见 `docs/contracts/mcp-tools.md`；知识正文只进 `kb_*` 真源。
