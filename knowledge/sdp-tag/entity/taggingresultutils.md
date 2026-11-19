---
created_at: '2026-11-18T07:26:22Z'
entity_kind: other
id: sdp-tag/entity/taggingresultutils
kind: entity
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/entities/taggingresultutils.md
  type: wiki
supersedes: []
tags:
- 模块
- 阈值
- 比较符
tier: canonical
title: TaggingResultUtils
updated_at: '2026-11-18T07:26:22Z'
---

> 阈值解析与比较工具类：维度值覆盖全局（:124），gt-v1 下为严格大于（:112）。

# TaggingResultUtils

## 定义

打标结果筛选的阈值解析与比较工具类。

## 关键属性（代码可验证）

```java
// TaggingResultUtils.java:124
public static double thresholdOf(String dimensionId, double threshold, Map<String, Double> dimensionThresholds) {
    Double override = dimensionId == null || dimensionThresholds == null ? null : dimensionThresholds.get(dimensionId);
    return override == null ? threshold : override;
}
```

- **替换语义**：维度有值就用维度值，全局只是兜底——不是「两者都要满足」，见 [[阈值体系]]。
- `gt-v1` 下比较为**严格大于** `score > threshold`（`:112`）；评测工具 coverage 曾用 `>=`。

## 关系

- 四层覆盖链（租户 → 全局 → 图谱 `dimension.label_threshold` → 内置）最终落在此处。
- 与 [[门控]] 的 `gateFloor` 取值相互独立但都为「取更严/取最小」的口径。

## 易误解

- 两套比较符在同一份数据上会持续制造「数据对不上」的假 bug。

## Citations

- `01-术语实义.md` §9 `[D][Z]`。
