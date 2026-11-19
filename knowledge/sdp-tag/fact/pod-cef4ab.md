---
created_at: '2026-11-18T07:26:22Z'
id: sdp-tag/fact/pod-cef4ab
kind: fact
project: sdp-tag
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: sdp-tag/concepts/镜像经-pod-中转.md
  type: wiki
supersedes: []
tags:
- 镜像
- 发布
- 网络
tier: canonical
title: 镜像经 pod 中转
updated_at: '2026-11-18T07:26:22Z'
---

> 宿主直推不可用（代理掐断 + ACR 实例带宽配额约 0.2 MB/s），必须 kubectl cp + crane push 整镜像。

# 定义

镜像发布不能从宿主机直推，必须：`kubectl cp` 传到 pod → 在 pod 内 `crane push` 整镜像。

# 根因（两个来源，两个事实）

| 来源 | 观察 | 结论 |
| --- | --- | --- |
| `[D]` | 宿主 `docker push` 被 Docker Desktop 代理掐断（`192.168.65.1:3128 … broken pipe`）；宿主 `crane` 直连只有 **48 KB/s**；宿主→集群很快（`kubectl cp` 163 MB 约 **6.9 秒**），pod→ACR 约 15~30 秒 | 代理会掐断大层 |
| `[Z]` | 切到无代理同样失败；`maven.aliyun.com` 能跑 12.5 MB/s，**只有 ACR 实例慢**（~0.2 MB/s，并行不叠加，0% 丢包 10ms） | ACR **实例侧带宽配额** |

**合并结论**：宿主直推不可用，原因叠加；**走 pod 中转是正确方案**。

# crane push 而非 crane append

`append` 每次叠 150MB+ jar，实测 **8 层 / 748 MB**；`push` 整镜像 **5 层 / 284.7 MB**。

# 其它固定要求

`docker build --provenance=false --sbom=false` 必须带。

# 关联

- 相关实体：[[部署环境]]
- 相关概念：[[容器内存按 JVM 参数推导]]

# Citations

- `02-方案选型与权衡.md` §23
