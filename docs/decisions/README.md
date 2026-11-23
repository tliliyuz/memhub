# 架构决策记录（ADR）

命名：`ADR-NNNN-<topic>.md`，一旦接受不修改正文；结论变化时新增一条并互相引用。

> 适用范围：架构决策的编号、状态与索引。
> 不负责：决策正文（见各 ADR 文件）、实施记录（见 [CHANGELOG.md](../CHANGELOG.md)）。

| 编号 | 标题 | 状态 |
|:---|:---|:---|
| [ADR-0001](ADR-0001-no-proxy-in-request-path.md) | 记忆能力不进入模型请求路径 | accepted |
| [ADR-0002](ADR-0002-markdown-source-of-truth.md) | markdown 为真源，图谱/向量为可重建投影 | accepted |
| [ADR-0003](ADR-0003-device-token-scope.md) | 采集器使用独立 device token，不复用面板 user_key | accepted |
| [ADR-0004](ADR-0004-runtime-state-in-postgres.md) | 运行态放云上共享 PostgreSQL 实例 | accepted |
| [ADR-0005](ADR-0005-async-orm-data-access.md) | 数据访问层改为异步 I/O + SQLAlchemy ORM | accepted |
| [ADR-0006](ADR-0006-upload-reuse-extraction-pipeline.md) | 管理台上传文档复用现有抽取管线 | accepted |
| [ADR-0009](ADR-0009-collector-project-write-grants.md) | 采集器按设备授权写入已登记目标 | proposed |

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
