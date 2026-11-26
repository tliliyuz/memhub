# 架构决策记录（ADR）

命名：`ADR-NNNN-<topic>.md`，一旦接受不修改正文；结论变化时新增一条并互相引用。

> 适用范围：架构决策的编号、状态与索引。
> 不负责：决策正文（见各 ADR 文件）、实施记录（见 [CHANGELOG.md](../CHANGELOG.md)）。

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
| [ADR-0016](ADR-0016-long-term-memory.md) | 长期记忆独立成域，并反向注入会话抽取 | proposed |
| [ADR-0017](ADR-0017-mcp-discovery-trace.md) | MCP 发现层事件并入调用轨迹，形成连接漏斗 | accepted |

模板：

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
