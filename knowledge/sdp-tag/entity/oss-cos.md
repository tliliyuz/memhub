---
created_at: '2026-11-18T07:26:22Z'
entity_kind: other
id: sdp-tag/entity/oss-cos
kind: entity
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/entities/oss-cos-图片转存.md
  type: wiki
supersedes: []
tags:
- 外部系统
- 图片
- 性能
tier: canonical
title: OSS/COS 图片转存
updated_at: '2026-11-18T07:26:22Z'
---

> 图片转存通道，价值在稳定性与可用性，被证伪为「打标提速」的原因，也未解决 lab 的图片下载超时。

# 定义

kind: external_system

将商品图从源 CDN（如 Zara `origin_url`）转存到自有对象存储（COS `store_url`）的通道，同时承担 WebP 等格式问题的转换职责。

# 关键属性

| 测量项 | 结果 |
| --- | --- |
| 经代理：CDN vs COS | 27.6 ms vs **67.2 ms**（COS 更慢） |
| 直连：CDN vs COS | 68.0 ms vs 71.6 ms（基本持平） |
| 解码耗时 | 都约 13 ms，字节与转换后 JPEG 完全一致 |
| 结论 | **不要把打标提速归因于 OSS 转存**；其价值是稳定性和可用性 |

# 关系

- ↔ [[实验台（lab）]]：⚠️ lab 仍**优先 `origin_url`** 而非 `store_url`，所以转存**并没有解决** lab 的图片下载超时（B11）。
- ↔ [[打标评测方法论]]：图片相关的「假阳性」根因（WebP 内容协商）无法复现，需靠 `Content-Type` + magic bytes 判定（F8）。

# 已知问题

- ⚠️ WebP 是真问题：JDK 17 ImageIO 不认 WebP，转存时 2 张「`.jpg`/`.png` 名字下实际是 WebP」的图**永久失败**（F8）。

# Citations

- B11、F8；出处见 [[03-失败与被推翻]]。
