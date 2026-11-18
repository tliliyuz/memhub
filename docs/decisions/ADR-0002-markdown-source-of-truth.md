# ADR-0002 markdown 为真源，图谱/向量为可重建投影

| 属性 | 值 |
|:---|:---|
| 状态 | accepted |
| 日期 | 2026-11-18 |

## 背景

旧系统的数据格式即实现：知识散在 DB、导出文件与 wiki 之间，无法 diff、无法回滚、无法人工审阅。semantica 的 `ContextGraph` 是内存对象 + JSON 持久化，适合查询但不适合作为长期真源。

## 决策

1. 每条知识 = 一个 markdown 文件，frontmatter 承载 `kind / tier / source / confidence`，git 版本化。
2. `kg.json`、向量索引、FTS 全部是**投影**，可随时删除并从 markdown 重建。
3. 写知识 = 写文件 + git commit；读知识优先走投影，投影缺失时回退文件扫描。

## 备选与否决理由

| 备选 | 否决理由 |
|:---|:---|
| 以 kg.json 为真源 | 合并冲突不可读，历史不可审阅，LLM 抽取结果无法人工局部修正 |
| 以 Postgres 为真源 | 需要迁移与备份体系，个人知识库规模用不上；导出仍是 markdown |
| 以向量库为真源 | 不可读、不可 diff；重建成本被低估 |

## 后果

- 治理 agent 的每次写入都产生 git commit，可回滚、可审计。
- 重建投影是常规操作（`rebuild.timer`），必须幂等。
- markdown 目录不能太大：单库 1e4 文件内由 FTS 覆盖；超出再考虑分库。
- 投影不一致是已知风险，用「重建后比对节点数」做健康检查。