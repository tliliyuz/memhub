# ADR-0014 取消「候选需人工转正」门槛，写入即生效

| 属性 | 值 |
|:---|:---|
| 状态 | accepted |
| 日期 | 2026-11-25（2026-11-26 负责人裁决采纳方案 B） |
| 关联 | 修订 ADR-0006（`tier=candidate` 一律人工转正）、ADR-0011 与 ADR-0012（MCP 只碰候选）、ADR-0013 §7（转正流程推迟）；修订 `docs/contracts/node-schema.md` §5 |

## 背景

ADR-0006 规定自动写入一律 `tier=candidate`，人工确认后升 `canonical`。ADR-0013 §7 把转正推迟到后续里程碑。当前仅能逐条人工转正，不符合产品对自动入库的要求。本条比较模型复核与取消转正两种路线，不设计人工审核界面。

现状带来三个具体问题：

- worker 与 MCP 写入的节点永远停在 `candidate`，默认搜索只查 `canonical`（`kb/query.py:157`），所以新知识默认搜不到，需要显式传 `tier="all"`。
- `node-schema.md:95` 写「无命中时回退 `candidate` 并标注」，实现没有这样做，文档与实现不一致。
- `merge.py` 对已有 `canonical` 节点一律跳过（`skipped_canonical`）。若按「LLM 通过即转」自动转正，转正后的节点不再接收后续会话的补充。

## 决策

负责人裁决（2026-11-26）：采纳方案 B，**取消转正门槛，所有有效节点都是 canonical**；方案 A（LLM 自动复核）不做。

1. 新建节点（worker 抽取、MCP 写入、迁移保留的存量）一律以 `tier=canonical` 写入。存量 `candidate` 用一次性数据迁移转为 `canonical`，`kb_node_revisions` 记一条 `actor=system`、`reason=ADR-0014` 的修订。
2. 保留 `tier` 列和 `deprecated` 取值，不做删列迁移。`candidate` 取值保留在枚举中，但没有任何写入路径。
3. 搜索默认排除 `deprecated`，不再按 `candidate` 过滤；删除「无命中回退候选」规则与 `_empty_hint` 中的候选提示。
4. worker 对已有节点不再因 `canonical` 跳过，改为沿用现有的追加式合并（追加来源与正文段落，不覆盖标题）。
5. MCP 的 `kb_update_candidate` 与 `kb_deprecate` 失去「只碰 candidate」的边界。新边界：调用方只能修改 `kb_node_revisions` 中创建者 `actor` 与自己一致的节点。工具名不改，避免破坏契约，描述同步更新。

## 备选与否决理由

- **方案 A：LLM 自动复核，通过即转 canonical。** 负责人最终裁决不采用（「如果不行就别搞这个机制，所有文档都是 canonical」）。保留为以后需要质量闸门时的技术路线。否决理由：
  - 模型可以复核来源是否支持结论，但不能仅凭同一份材料验证结论真实；目前没有评测证明第二道模型判定比现有证据校验有足够收益。
  - 增加一次模型复核（可按批处理），还要定义拒绝、超时和重试耗尽后的去向，否则会重新产生默认搜不到的节点。
  - 转正后仍要解决 `skipped_canonical` 冻结问题，所以第 4 条改动两个方案都要做。
- **方案 C：管理台批量转正或轻量审批流。** 否决：负责人已明确不做人工审核。
- **维持现状。** 否决：默认搜不到新知识，且文档与实现已经不一致。

## 后果

- 默认搜索直接可见新知识，不再需要 `tier="all"`。
- 失去「自动写入先隔离」的缓冲。抽取质量问题会直接进入默认检索，只能靠 `kb_deprecate` 与管理台废弃事后处理。
- 数据迁移会改动存量行，需要在部署前核对 `candidate` 数量，并保留迁移前的修订快照以便回滚。
- 需要同步修改：`node-schema.md` §5、`mcp-tools.md`、`architecture.md:71`、`kb-admin-api.md`、管理台的 tier 下拉与徽标、`web` 中的 tier 筛选。
- ADR-0006 第 23 行、ADR-0011、ADR-0012 的相关句与 ADR-0013 §7 在本条接受后标注「被 ADR-0014 修订」。
