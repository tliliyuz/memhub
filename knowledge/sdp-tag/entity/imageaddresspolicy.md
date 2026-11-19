---
created_at: '2026-11-18T07:26:22Z'
entity_kind: other
id: sdp-tag/entity/imageaddresspolicy
kind: entity
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/entities/imageaddresspolicy.md
  type: wiki
supersedes: []
tags:
- 主图
- 模块
- 白名单
tier: canonical
title: ImageAddressPolicy
updated_at: '2026-11-18T07:26:22Z'
---

> 主图地址放行/阻断判定模块，isBlocked 含链路本地判定；allowed-networks 与 allowed-hosts 语义完全不同。

# Definition

主图抓取前的地址判定模块：判断一个主图 URL 是否允许下载（`isBlocked`），由 [[sdp-tag-api]] 的 precheck 调用。

# Key attributes

- `isBlocked` **包含链路本地判定** → `169.254.x.x` 一律被拦（腾讯云 COS 就近接入 VIP 就是这么被拦的）。
- 两个配置项**语义完全不同**：

| 配置项 | 语义 | 正确用法 |
| --- | --- | --- |
| `allowed-networks` | 放开网段 | **只本机**（Clash fake-IP `198.18.0.0/15`），不要上生产 |
| `allowed-hosts` | 按主机名放行 | 生产首选（如 COS 域名） |

- **环境变量命名陷阱**：`allowed-hosts` → `TAG_IMAGEFETCH_ALLOWEDHOSTS_0`（点换下划线、连字符去掉）；写成 `TAG_IMAGE_FETCH_ALLOWEDHOSTS_0` 会**静默失效**（真实发生过）。
- JDK 17 ImageIO 不认 WebP：OSS 转存时 2 张图永久失败（`download_status=3`）；但「CDN 返回 WebP」的根因**无法复现**，再次出现先抓 `Content-Type` + magic bytes。

# Relationships

| 关联 | 关系 |
| --- | --- |
| [[主图抓取放行模型]] | 该模块所属的概念模型 |
| [[tencent-cos]] | 被拦的典型来源 |
| [[静默失败]] | precheck 失败不记日志 |

# Citations

- 04 排障信号手册 §3.1、§4.5
