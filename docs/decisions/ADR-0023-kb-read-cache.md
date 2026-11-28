# ADR-0023 kb 读接口使用本机 Redis 热读缓存

| 属性 | 值 |
|:---|:---|
| 状态 | accepted |
| 日期 | 2026-11-28 |

## 背景

kb 读接口在 PG 真源上完成批量读改造（`read_many` 单条 SELECT + 元数据投影）后，
`nodes?limit=500`、`stats`、`audit` 仍分别约 0.4–0.55s：剩余成本是读库、摘要组装与
JSON 编码，不随 `limit` 线性增长，但每次管理台切换页面都重复付一遍。这些结果都可由
`kb_*` 表重建，属于典型热读。

腾讯本机已部署 Redis 7.0.15（只监听 loopback，明文，纯缓存配置：`maxmemory`
512MB、`allkeys-lru`、save/AOF 关闭），本机往返约 0.18ms；容器走 host 网络可达。

## 决策

为 `nodes` / `stats` / `audit` 三个读接口加一层**可选的**本机 Redis 缓存：

- **能力开关**：`MEMHUB_REDIS_URL` 缺失、redis 客户端未安装、连接或读写失败，一律按
  「缓存关闭」处理并降级到 PG，不阻断启动、不向调用方抛错；口令只读
  `MEMHUB_REDIS_PASSWORD`，不写日志、不进 key。
- **一致性靠数据版本，不靠 TTL**：`PgKnowledgeStore.cache_epoch()` 用两条廉价聚合拼出
  版本串——`(active 节点 count, max(updated_at))` 与 `(边 count, max(created_at))`；
  epoch 摘要进缓存 key。节点/边的增、改、删、恢复都会改变 epoch，旧 key 立即失联。
  TTL（60s）只做内存背压，不承担正确性。
- **值带 schema 版本**：缓存值是 `{"v": <SCHEMA_VERSION>, "data": ...}` 的 JSON；版本
  不匹配或解析失败按未命中处理并重算，滚动升级期间新旧进程不会互喂脏值。
- **key 不含内容**：key 只由命名空间、参数摘要与 epoch 摘要拼成；正文、口令、查询词
  都只参与摘要，不落 key。
- 只是加速层：Redis 重启即丢，不做持久化配置，也不缓存 `search` / `graph`
  （`search` 口径仍在演进，`graph` 已足够快）。

## 备选与否决理由

- **进程内 LRU**：无新依赖，但每个 kb-api 进程各一份，重启即丢且不可观测；后续若扩
  多进程/多实例，失效口径不一致。Redis 已有现成部署，跨进程一致。
- **PG 物化视图/汇总表**：写路径要同步维护，等于把缓存失效成本前移到写侧；读多写少
  的短 TTL 缓存更简单，且失效口径由 epoch 统一承担。
- **直接调大 TTL 不拼 epoch**：实现最省，但数据更新后最长 60s 才可见，管理台改完节点
  刷新列表可能仍看到旧值，不可接受。
- **缓存 `search`**：检索排序与分词口径还可能调整，先不把未定型结果固化进缓存层。

## 后果

- 新增第三方运行时依赖 `redis`（纯 Python，无 hiredis），以 `memhub[cache]` 额外项
  安装；`Dockerfile.kb` 与 `deploy/lock-kb.txt` 的离线构建闭包必须同步（发版前需把
  redis wheel 放进 wheelhouse）。
- 命中时 `audit` 的 `created_at` 是上次检出时间而非本次；该字段本就是「检出时间」语义，
  缓存命中时沿用同一口径，不另做事件时间。
- 全局 epoch 在夜间批量写入时变化频繁，命中率会下降；先按全局口径上线，用命中率数据
  再决定是否按 project 拆分 epoch。
