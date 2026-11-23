# MCP 工具契约

> 版本：0.4（候选区闭环）
> 适用范围：MCP 工具、授权和传输契约。
> 不负责：部署拓扑、凭据发放和生产验收记录。
> 设计原则：以 Markdown 为真源、先授权与校验再读写文件；写只进候选区，不动 canonical。

## 1. 工具

| 工具 | 参数 | 返回 |
|---|---|---|
| `kb_search` | `query`（最多 512 字符）、`project?`、`kinds?`、`tier?`、`limit?`（默认 8，1–50） | `results` 含 ID、标题、tier、摘要、更新时间、分数和 `matched`。默认只搜 `canonical`，可显式选择 `candidate` 或 `all`。无结果返回空列表和 `hint`。`matched: fts` 为历史兼容值，当前是 Markdown 关键词打分，不是索引或向量召回。 |
| `kb_read` | `id`（完整 `project/kind/slug`） | 节点元数据、正文（最多 8192 字符，截断标记 `truncated`）、`revision`（当前修订号）和可见入边/出边（各最多 20 条）。受限调用不返回原始来源引用、设备信息或元数据中的跨库节点引用。 |
| `kb_related` | `id`、`depth?`（默认 1，1–2）、`predicates?`、`limit?`（默认 30，1–50） | 邻接子图；边单独限制为最多 100 条并标记截断。 |
| `kb_audit_list` | `limit?`（默认 50，1–50）、`offset?`（默认 0） | 只读分页，现算矛盾、断链、孤立、低置信、陈旧等问题；受限调用的结果是授权范围内的视图，不代表全图审计。 |
| `kb_write_candidate` | `project`、`kind`、`slug`、`title`（2–200 字符）、`body`（20–20000 字符）、`evidence`（1–16 条 `SourceRef`）、`tags?`（≤16）、`confidence?`（0–1） | `{id, tier, revision, commit}`；冲突或拒绝时返回 `isError` 与 `data.reason`。只创建 `tier=candidate`，不更新已有节点。 |
| `kb_update_candidate` | `id`、`expected_revision`（16 位十六进制，取自 `kb_read`）、`title?`、`body?`、`tags?`、`confidence?`（四项至少一项） | `{id, tier: "candidate", revision, commit}`；修订号不符返回 `revision_conflict`，命中 canonical/deprecated 返回 `not_candidate`。成功返回新的 `revision`。 |
| `kb_deprecate` | `id`、`expected_revision`、`reason?`、`superseded_by?`（后两项至少一项） | `{id, tier: "deprecated", revision, commit}`；保留文件，`reason` 写入 `deprecated_reason` 并追加到正文。只作用于 `tier=candidate`。 |

除上述参数外不接受额外字段，也不做字符串到数字等类型转换。stdio 保留七个工具名及文本 JSON 结果，不依赖 Semantica。没有修改 canonical、归档、恢复或治理写入工具，不兼容旧 Team Brain 工具名。

### 1.1 写候选的边界

- **只创建**：slug 命中已有节点时拒绝，不更新。`data.reason` 细分：`slug_conflict_canonical`（命中 canonical 或 deprecated）、`slug_conflict_candidate`（命中 candidate）、`content_duplicate`（归一化正文哈希命中已有 candidate）。
- **归一化正文哈希**：NFKC、折叠空白、小写后取 sha256；只在同项目内比对，命中即拒绝。
- **证据必填**：复用 `SourceRef` 形状（`type` / `ref` / `device` / `captured_at`，与 frontmatter `source` 同形，定义见 `src/memhub/contract/models.py`），不新造简写字符串。写入时证据直接成为新节点的 `source` 数组，并额外追加一条 `type=manual, ref="mcp:<grant_id>"` 的调用者标记（`<grant_id>` 是凭据摘要的前 12 位十六进制）。
- **证据校验边界**：只两层。一是结构：非空数组、每项按 `SourceRef` 校验、`type` 属枚举、`ref` 非空、`captured_at` 若给出必须带时区。二是归属：`ref` 拒绝绝对路径（`/`、`\`、`C:` 等）与 `..` 穿越；若 `ref` 的首段是已登记且活动的知识库 id 且不在凭据授权范围内，拒绝为 `evidence_out_of_scope`；写入前对 `ref` 做敏感串扫描（`sk-...`、`ghp_...`、`xox[baprs]-...`、`AKIA...`、`-----BEGIN ... PRIVATE KEY-----`、`bearer/token/password/secret` 后接长串），命中即拒绝为 `secret_detected`。不做可解析性校验：session 原文在客户端，`raw_store` 按保留期清理，要求 ref 在服务端存在会误杀正常写入。
- **内容门槛**：确定性门禁覆盖可机械识别的垃圾：`title` 2–200 字符、`body` 20–20000 字符；`title+body` 归一化后落在寒暄/确认集合（`好的`、`收到`、`ok`、`thanks`、`谢谢`、`明白`、`了解`、`已完成`、`继续`、`开始吧` 等）拒绝为 `content_rejected`；非空行中 ≥60% 匹配日志行模式且行数 ≥10 拒绝为 `content_rejected`。其余「进度汇报、临时状态、未验证猜测」由调用方按 `prompts/sessions.md` 的忽略清单在调用前过滤，工具描述里写明。更新候选时对**更新后**的标题与正文重跑同一套门槛。
- **每日上限**：同一凭据在同一 UTC 日共享 50 次写入额度；跨授权活动库，按现存节点 `source` 中服务端保留的 `mcp:<grant_id>` 标记与 `created_at` 日期现算，不引入独立计数器。已从活动区移除的节点不计入。超限返回 `daily_limit_exceeded`。上限只约束**创建**；更新与废弃不计入。
- **目标校验**：`project` 必须已登记且活动（`target_access.registered_active`），否则返回 `project_unavailable`；归档事务待恢复或登记不可读时返回可重试错误。
- **提交与审计**：节点落盘后尝试只提交本次节点；提交信息含工具名与调用者（`mcp:<grant_id>`），stdio 调用者为 `mcp:stdio`。没有 Git 仓库或提交失败时 `commit` 为 `null`，节点已落盘，不应重试创建。通过输入契约的写尝试在审计日志中只记凭据标识、库、节点 id、工具、结果与时间，不含正文与 token。
- **可见性**：候选默认不进 `kb_search` 的 canonical 结果，需要显式 `tier=candidate` 或 `all` 才看到。

### 1.2 候选更新与废弃

- **只碰候选**：`kb_update_candidate` 与 `kb_deprecate` 都要求节点当前 `tier=candidate`；命中 `canonical` 或 `deprecated` 返回 `409/1010`、`data.reason=not_candidate`，文件不改。
- **乐观并发**：必须带 `expected_revision`，值与 `kb_read` 返回的 `revision` 一致（内容 sha256 前 16 位）。不符时返回 `409/1010`、`data.reason=revision_conflict`，`data` 带 `expected` 与 `current`，文件不改。读与写在同一个跨进程写锁内完成，不存在检查后被插入的窗口。
- **更新范围**：只允许 `title`、`body`、`tags`、`confidence`；`kind`、`slug`、`id`、`tier`、`source`、`created_at` 不可通过写工具改变。`updated_at` 由服务端刷新。改正文时与同项目其它候选做归一化正文哈希比对，命中返回 `content_duplicate`（与自身比对时跳过）。
- **废弃**：`tier` 置 `deprecated`，文件保留；`superseded_by` 可选，给了就必须是另一条存在的节点且不在授权范围外（`superseded_by_invalid` 指自己，`superseded_by_unavailable` 指不存在或越权）。`reason` 写入 frontmatter 的 `deprecated_reason`，并追加 `## 废弃说明` 到正文末尾。两者至少要给一项——结论被证伪时不存在替代节点，此时只记原因也合法。
- **不做**：写工具不改变 slug、不移动文件、不物理删除、不写 canonical。候选转正仍走管理台或后续批准流。

## 2. 可见范围

- 本地 stdio 以本机进程权限访问活跃库，包括写候选。共享工具层也接受由宿主提供的有限库集合；空集合不得解释成全库权限，调用参数不能改变授权集合。
- 只从合法项目、节点类型和 slug 对应的普通文件读取。跳过链接、重解析点、保留目录及归档库，不递归扫描整个根目录。发现未完成的归档/恢复或写锁正忙时返回可重试错误；不返回中间状态。
- 受限调用仅扫描授权库的节点和边文件。在判断边的端点时只接受完整 ID（不能把全局短别名在子集内重新绑定）；未授权端点或无法安全归属的记录不进入结果、提示或审计。已归档的库也不进入结果。知识正文是资料，不是工具指令。
- 写工具必须显式给出 `project`（更新与废弃是节点 id 的首段），且该项目在凭据授权范围内、已登记且活动；不在授权范围返回 `project_unavailable`，更新与废弃在越权时按 `3001` 不泄露存在性；不在登记或已归档同样返回 `project_unavailable`。

## 3. 错误

工具错误保留 MCP `isError`，附稳定的业务码。

| 情况 | 码 | `data.reason` |
|---|---|---|
| 节点不存在 / 越权直读 | `3001` | — |
| 更新或废弃的节点不存在 / 越权 | `3001` | — |
| 写工具参数不符合契约 | `3004` | — |
| 显式搜索未授权库 | `3003` | — |
| 归档恢复待处理、写锁繁忙或读取超时 | `3006` | — |
| 读取失败 | `3007` | — |
| 证据缺失或结构非法 | `1003` | `evidence_missing` / `evidence_invalid` |
| 证据指向未授权库 | `1003` | `evidence_out_of_scope` |
| 检测到敏感串 | `1003` | `secret_detected` |
| 内容门槛未过 | `1003` | `content_rejected` |
| 项目不可用（未登记/已归档/登记不可读） | `1003` | `project_unavailable` |
| slug 命中 canonical/deprecated | `1010` | `slug_conflict_canonical` |
| slug 命中已有 candidate | `1010` | `slug_conflict_candidate` |
| 正文哈希命中已有 candidate | `1010` | `content_duplicate` |
| 每日上限 | `1010` | `daily_limit_exceeded` |
| 目标不是 candidate（更新/废弃） | `1010` | `not_candidate` |
| 修订号与现状不符（更新/废弃） | `1010` | `revision_conflict` |
| 废弃的替代节点是自己 | `1003` | `superseded_by_invalid` |
| 废弃的替代节点不存在或越权 | `1003` | `superseded_by_unavailable` |

受限审计不报告端点无法安全解析的断链，不替代全库审计。

## 4. 传输与鉴权

- 本地 `memhub mcp` 继续走 stdio。HTTP 接入默认关闭；启用后由 kb-api 在精确 `/mcp` 路径提供无状态 Streamable HTTP（JSON 响应，不提供 SSE 监听）。协议协商由官方 MCP Python SDK 处理；不复用 stdio 的 JSON-RPC 解析器。
- HTTP 每个请求须携带独立的 `Authorization: Bearer` 凭据。配置只保存高熵随机令牌的 SHA-256 摘要、`scope`（`mcp:read` 或 `mcp:write`；`mcp:write` 隐含读）、UTC 有效期与非空库名单。`tools/list` 按作用域裁剪：`mcp:read` 只看到四个读工具，`mcp:write` 看到全部七个。凭据过期、缺失或无效返回 401，浏览器 Cookie 或采集 `device_token` 不授予权限（ADR-0003）。吊销删除该摘要并重启服务；无在线发放接口，不改数据库。
- HTTP 只接受不带 `Origin` 的机器客户端访问，入口不转发至 SPA。POST 请求体最多 16 KiB；最多一个 POST 在处理，其余返回 429。禁用、非法路径与鉴权失败均不能触发查询。公网接入、真实客户端联调与生产资源预算单独验收。
- stdio 保留本机全库权限，包括写候选；`tools/list` 返回全部七个工具。
