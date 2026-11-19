---
created_at: '2026-11-18T07:26:22Z'
id: sdp-tag/fact/n-c7dc1cf8
kind: fact
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/concepts/阈值体系.md
  type: wiki
supersedes: []
tags:
- 阈值
- noul
- 四层覆盖
- 比较符
- 配置
- 判分
- 打标
tier: canonical
title: 阈值体系
updated_at: '2026-11-18T07:26:22Z'
---

> 阈值是「替换」不是叠加；四层覆盖（图谱层常空、回落全局）、三套环境阈值并存、两套比较符与 0.8 写死 bug；env 不覆盖阈值；noul 概率语义；Ark 分布极端需 0.999。

# 阈值体系

## 定义（实义）

模型不筛，**服务端筛**；比较字段统一是 `TaggingDecisionDTO.score`（[[JEV 百炼决策模型]] 的 noul 也映射进 score）。

**最容易被理解错的一条**：

> 维度阈值不是「全局 0.9 和维度阈值都要满足」，而是**「维度有值就用维度值，全局只是兜底」**。

```java
// TaggingResultUtils.java:124
return override == null ? threshold : override;
```

一句话概括：sdp-tag 中控制「打标结果是否命中」的各类阈值配置，**三套并存**且位置分散，是最容易配错的一块。

## Schema

**四层覆盖**（从外到内）：

1. 租户 `tag_tenant_override`
2. 全局 `tag_workflow_default`
3. 图谱 `dimension.label_threshold`
4. 内置

第 3 层在 DB `graph_dimension.label_threshold` 中**常为空**，因此实际会**回落全局**——这与上面的「替换、非叠加」一致：空值等于没配，不是「更宽松」。

**比较符**：`gt-v1` 下是**严格大于** `score > threshold`（`TaggingResultUtils.java:112`），但 [[评测工具]] 的 coverage 曾用 `>=`。同数据两套口径，会持续制造「数据对不上」的假 bug，见 [[TaggingResultUtils]]。

## 三套阈值并存 `[D]`

| 场景 | 配置项 | 位置 | 阈值 |
| --- | --- | --- | --- |
| 实验台（[[打标实验台]]） | `tag.lab.scene-threshold` / `label-threshold` / dimension | yml | 0.8 / **0.7** / 0.8 |
| 正式链路（[[打标服务]]） | `tag.pipeline.scene-threshold` | yml | 0.8 |
| 正式链路（[[打标服务]]） | `tag.pipeline.label-threshold` | yml | **0.9** |
| 图谱维度 | `graph_dimension.label_threshold` | DB | 空（**回落全局**） |
| 门控 | `llm.chat.gate-threshold` | 启动参数 | **0.7** |
| 历史 doubao 方案 | — | — | **0.999** |

**实验台阈值 ≠ 线上阈值。把实验台结论直接搬到线上会错。** 而 `deploy/k8s/api.yaml` 的 env **没有覆盖阈值**——阈值根本不在那套 env 里映射，**改 yaml 不会改阈值**（原因见 [[env-var-relaxed-binding]]，映射缺失）。

**已知 bug**：`TagTaskSpecFactory:55` 曾把维度阈值**写死 0.8**。由于 `TagTaskSpecFactory` 构造 `TagTaskRunSpec` 决定 `configHash`，该写死值同时影响缓存复用，见 [[指纹与哈希复用]]。

> ⚠️ 注意区分：上表中的 `0.8` 是**正常配置值**（lab / pipeline 的 scene 阈值等）；`TagTaskSpecFactory:55` 的 `0.8` 是**写死的 bug 值**（劫持维度阈值并污染 configHash）。两者数值相同但性质不同，不要混为一谈。

## 与 Ark 的冲突 `[D]`

[[ark-volces]] 的分数分布极端：**2,308 个命中里 1,582 个 ≥ 0.999**，分数堆在 **0.99+**。

→ **0.7 阈值对 Ark 太松，要用 0.999。**

> ⚠️ 记录冲突：旧页把 `0.999` 记为「历史 doubao 方案」的阈值，新页把 `0.999` 记为「Ark 分布极端所以需要 0.999」。两者是否同源尚未确认，**保留两说**，不合并为单一事实。

## noul 是什么——不要 claim「校准概率」

`[Z]`：

- Noul 是 TypeSafe JEV / 百炼决策模型返回的「答案为是的概率」，**项目不做任何计算**，只校验 0~1。
- **官方文档没发布算法，也从没声称概率是校准的**；「校准概率」只出现在我们自己的代码注释和 Spec 里——**不要重复这个说法**。
- 中值（接近 0.5）文档说是「不清晰的情况」，不是「一半匹配」。
- `0.8/0.8/0.7` 这组阈值在仓库里没有推导依据。

## 与门控的关系

`gateFloor = min(配置闸门, 本阶段阈值, 该批涉及维度的生效阈值)`，三处取最小；配置闸门即启动参数 `llm.chat.gate-threshold`（0.7）。同一个 0.7 在门控口径下更严，见 [[门控]]。

## 连锁影响

- [[指纹与哈希复用]]：调一个维度阈值 → `configHash` 变 → 全量缓存失效。
- [[直标与补全]]：补全**绕过阈值**，甚至覆盖直判否定。
- [[分数带与准确率]]：临界带（[0.70,0.75) 79.0%）是质量风险，不只是稳定性问题。

## 验证方式

- 看 `TaggingResultUtils.thresholdOf` 的实际入参（是否带 `dimensionThresholds`）。
- 比对调用侧比较符（`gt-v1` vs `>=`）。
- 核对生效来源：yml / DB `graph_dimension` / 启动参数，而**不是** `deploy/k8s/api.yaml` 的 env。

## Related Entities

- [[TaggingResultUtils]] — 阈值解析与比较符实现
- [[JEV 百炼决策模型]] — score 来源
- [[打标实验台]] — lab 阈值（0.8/0.8/0.7）
- [[打标服务]] — pipeline 阈值（0.8/0.9）消费方
- [[评测工具]] / [[lab-accuracy-tool]] — 阈值口径与 lab 阈值
- [[ark-volces]] — 分数分布极端
- [[env-var-relaxed-binding]] — env 不覆盖阈值的原因（映射缺失）
- [[sdp-tag-api]] — 部署清单
- [[sdp-tag-backend]] — 阈值消费方
- [[门控]]、[[指纹与哈希复用]]、[[直标与补全]]、[[分数带与准确率]]

## Common Topics

- 配置体系
- 评测框架

## Citations

- `01-术语实义.md` §8、§9、§9.1、§9.2 `[D][Z]`。
- `05-配置与凭据地图.md` §3.4 阈值相关（三套并存，最容易配错）、§5.1 Ark 分数分布 `[D]`。
