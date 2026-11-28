# 架构决策记录（ADR）

本目录保存长期架构取舍：ADR 回答「为什么选这个方案」，不承担当前规范正文；字段、行为与口径以 [权威文档矩阵](../../CLAUDE.md#3-权威文档矩阵) 指定的来源为准。

命名：`ADR-NNNN-<topic>.md`，一旦接受不修改正文；结论变化时新增一条并互相引用。

> 适用范围：架构决策的编号、触发判定、状态与索引。
> 不负责：决策正文（见各 ADR 文件）、实施记录（见 [CHANGELOG.md](../CHANGELOG.md)）。

## ADR 触发清单

以下任一项成立时，必须先完成 ADR 检查，再继续规格、测试或实现：

1. 引入或移除跨组件边界（新的服务、执行面或存储边界）。
2. 更换存储、编排或消息机制，或改变任务领取、幂等/去重语义。
3. 改变对外契约（采集 API、MCP 工具、节点 schema、管理台 API）的主版本、必填字段或错误/退出码语义。
4. 改变知识层级、检索口径或门禁判定顺序。
5. 引入新的第三方运行时依赖，或替换承担抽取、检索、合并的核心库。
6. 改变部署拓扑、运行环境假设或离线可用性。
7. 改变数据保留、审计、访问控制或密钥边界。
8. 改变成本模型、预算执行方式或模型/抽取调用策略。

清单外的重构、命名调整、局部性能优化和文档修订不触发 ADR。判断不确定时按命中处理。

## 检查与裁决输出

每次检查在规格或变更说明中输出：

```text
ADR 检查
- 命中项：<清单编号与事实>；未命中写「无」
- 结论：创建 ADR / 豁免 ADR：<理由> / 未命中 ADR：<理由>
- 关联文档：<受影响的规范与计划>
```

- 「创建 ADR」：先写 `proposed` 记录，负责人裁决后改为 `accepted`；未 accepted 前不得据此实现。
- 「豁免 ADR」：必须有负责人明确理由，并说明该取舍的影响范围与复核时点。
- 「未命中 ADR」：说明为何属于清单外改动；命中却写未命中视为治理违规。
- 记录至少包含命中项、裁决人、理由与日期；写入当次规格或 [CHANGELOG.md](../CHANGELOG.md)，同一裁决只在一个位置定义，其他文档引用。

## 修订、替代与澄清

| 动作 | 适用 | 写法 |
|:---|:---|:---|
| 澄清 | 决策不变，仅补充边界或术语 | 不重写 ADR 正文；在 CHANGELOG 或规范记录并引用原 ADR |
| 修订 | 同一决策族内的参数或范围调整 | 新建 ADR，在「背景」声明补充范围；原 ADR 保持 `accepted`，索引新增一行 |
| 替代 | 决策方向改变 | 新建 ADR，旧 ADR 状态改为 `superseded by ADR-XXXX`，两者双向链接 |

- 已接受的 ADR 不得删除；被替代的保留全文，只改状态与链接。
- 同一事实只在当前有效 ADR 的「决策」中定义一次；历史讨论归入「备选与否决理由」。

## 索引

| 编号 | 标题 | 状态 |
|:---|:---|:---|
| [ADR-0001](ADR-0001-no-proxy-in-request-path.md) | 记忆能力不进入模型请求路径 | accepted |
| [ADR-0002](ADR-0002-markdown-source-of-truth.md) | markdown 为真源，图谱/向量为可重建投影 | superseded by ADR-0013 |
| [ADR-0003](ADR-0003-device-token-scope.md) | 采集器使用独立 device token，不复用面板 user_key | accepted |
| [ADR-0004](ADR-0004-runtime-state-in-postgres.md) | 运行态放云上共享 PostgreSQL 实例 | accepted |
| [ADR-0005](ADR-0005-async-orm-data-access.md) | 数据访问层改为异步 I/O + SQLAlchemy ORM | accepted |
| [ADR-0006](ADR-0006-upload-reuse-extraction-pipeline.md) | 管理台上传文档复用现有抽取管线 | accepted |
| [ADR-0013](ADR-0013-postgres-source-of-truth.md) | PostgreSQL 作为知识唯一真源 | accepted |
| [ADR-0014](ADR-0014-drop-candidate-tier-gate.md) | 取消「候选需人工转正」门槛，写入即生效 | accepted |
| [ADR-0009](ADR-0009-collector-project-write-grants.md) | 采集器按设备授权写入已登记目标 | superseded by ADR-0010 |
| [ADR-0010](ADR-0010-collector-target-without-grant-file.md) | 采集写的目标边界改为「显式 + 已登记 + 活动」 | accepted |
| [ADR-0011](ADR-0011-mcp-write-candidate.md) | MCP 第一阶段只开放写候选 | accepted |
| [ADR-0012](ADR-0012-candidate-update-and-deprecate.md) | 候选区闭环：允许更新与废弃自己的候选 | accepted |
| [ADR-0015](ADR-0015-mcp-call-trace.md) | MCP 调用轨迹落库，治理台可见 | accepted |
| [ADR-0016](ADR-0016-long-term-memory.md) | 长期记忆独立成域，并反向注入会话抽取 | accepted |
| [ADR-0017](ADR-0017-session-message-uuid-dedupe.md) | 会话去重单位改为消息 uuid，fork 不再重复抽取 | accepted |
| [ADR-0018](ADR-0018-mcp-discovery-trace.md) | MCP 发现层事件并入调用轨迹，形成连接漏斗 | accepted |
| [ADR-0019](ADR-0019-mcp-memory-tools.md) | MCP 只读长期记忆工具，凭据显式开启 | accepted |
| [ADR-0020](ADR-0020-clickhouse-raw-store.md) | 原始增量存百度云 ClickHouse，提炼队列放 PG | accepted |
| [ADR-0021](ADR-0021-kb-runtime-role-split.md) | kb-api 与 ingest/worker 拆分运行态角色与连接预算 | accepted |
| [ADR-0022](ADR-0022-mcp-modern-connection-event.md) | MCP 现代协议的连接事件并入漏斗 | accepted |
| [ADR-0023](ADR-0023-kb-read-cache.md) | kb 读接口用本机 Redis 热读缓存，失效靠数据版本 epoch | accepted |
| [ADR-0024](ADR-0024-read-cache-ttl.md) | 读缓存 TTL 由 60s 提到 600s（ADR-0023 参数修订） | accepted |

## 模板

```markdown
# ADR-NNNN 标题

| 属性 | 值 |
|:---|:---|
| 状态 | proposed / accepted / superseded by ADR-XXXX |
| 日期 | YYYY-MM-DD |

## 背景
## 决策
## 备选与否决理由
## 后果
```
