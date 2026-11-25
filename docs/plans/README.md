# 计划与规格

> 适用范围：跨模块的实施规格、迁移方案与里程碑拆解。
> 不负责：架构决策（见 [decisions](../decisions/README.md)）、对外字段契约（见 [contracts](../contracts/README.md)）、变更记录（见 [CHANGELOG](../CHANGELOG.md)）。

| 文档 | 状态 | 内容 |
|:---|:---|:---|
| [kb-pg-migration-spec.md](kb-pg-migration-spec.md) | specified | 知识真源迁到 PostgreSQL 的数据模型、边界、迁移与验收规格（承接 [ADR-0013](../decisions/ADR-0013-postgres-source-of-truth.md)） |
| [mcp-trace-spec.md](mcp-trace-spec.md) | draft | MCP 调用轨迹的数据模型、记录语义、可靠落库、保留期与管理台验收规格（承接 [ADR-0014](../decisions/ADR-0014-mcp-call-trace.md)） |

约定：规格在负责人评审通过前保持 `draft`；获批后改为 `specified`，实现以规格导出的验收测试为准（见 [DEVELOPMENT](../guides/DEVELOPMENT.md) §4）。
