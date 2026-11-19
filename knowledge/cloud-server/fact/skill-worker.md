---
created_at: '2026-11-18T07:26:22Z'
id: cloud-server/fact/skill-worker
kind: fact
project: cloud-server
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: cloud-server/concepts/skill-worker-空转与认证超时级联.md
  type: wiki
supersedes: []
tags:
- 故障
- memory-core
- 性能
- 认证
- '502'
tier: canonical
title: skill worker 空转与认证超时级联
updated_at: '2026-11-18T07:26:22Z'
---

> memory-core 的 skill 抽取 worker 在抢不到锁时以 20ms 代替 200ms 抑制期忙等，打满单核 CPU，使其作为认证服务无法在 5 秒内响应，向上表现为 401 与 502 交替出现。

# 定义

[[tdai-memory-core]] 内含一个 skill 对话抽取 worker pool。在「agent 已在队头但抢不到抽取锁」的状态下，该 pool 会进入忙等（hot-loop），把单核 CPU 打满；而 [[tdai-memory-core]] 同时还是 [[tdai-proxy]] 的**认证服务**，于是认证在 5 秒内拿不到结果，向上表现为客户端 401 / 502。

# 症状（2026-11-16 / 11-17 两次实测）

客户端侧看到的是「red 阻塞」「attempt N/10」，账号侧看到的是交替出现的两种错误：

```
401 Authentication failed: auth service timeout (5000ms)
502 upstream request failed: ... client error (SendRequest)
```

服务端指标：

| 指标 | 异常值 |
|---|---|
| `tdai-memory-core` CPU | 100.27%（宿主 4 核，单核打满） |
| `/health` | `http=000`，实测 6s / 10s 无响应 |
| Docker 健康检查 | `Health check exceeded timeout (5s)`，`FailingStreak=7` |
| `auth service timeout` | 2232 次 / 12 小时 |
| 容器内堆叠的探针进程 | 14 个 `curl -fsS http://127.0.0.1:8420/health` 全部卡住 |
| 日志量 | 24551 行 / 10 分钟，随后 **2 分钟 0 行** |

**关键判据**：端口仍在 LISTEN、进程仍在，但日志突然静默且 `/health` 完全无响应 → 事件循环被同步操作占死，不是进程崩溃。容器内健康检查 curl 堆积是同一事实的物理证据（正常情况下一毫秒就退出）。

# 为什么会空转

`src/core/skill/conversation-add/worker-pool.ts`：

```js
const suppressTtl = this.opts.suppressAgentTtlMs ?? 200;   // 抑制 200ms

if (isSuppressed(agent)) {
  obsLogger.info("skill.worker.suppressed_skip", { worker_id, instance_id, agent_id });
  await sleep(Math.min(20, suppressTtl));                  // 但只睡 20ms
  continue;                                                // 立刻再 peek 同一个 agent
}
```

**抑制期 200ms、实际只睡 20ms**，等于每 200ms 空转约 10 次，每次还打一条 INFO 日志。乘上 `TDAI_SKILL_WORKER_CONCURRENCY`（默认 4）与队列里的多个 agent，就是每秒数百次循环。

`peekAgent` 是 peek 语义（不删队列），所以抢不到锁的 agent 一直留在队头被反复取到。相关参数：

- `worker.extractLockTtlMs` 默认 **600000（10 分钟）** —— 一个僵死锁会统治队头 10 分钟
- `brpopBlockMs` 默认 5000

日志里出现的 `suppressed_skip` 计数与 `agent_id` 会随批次变化（如 `agt-n7mlp4f7` → `agt-cNsjxlsi` → `agt-nyupnf7d3q`），所以**这不是单个 agent 的毒丸，换一批 agent 仍会复现**。

# 级联到 401 / 502 的路径

```
客户端上传 200~400KB
  → tdai-proxy 先调 memory-core 做 auth 校验（auth.timeoutMs=5000）
  → memory-core CPU 100%，5 秒内无响应
  → auth.verify.error → tdai-proxy 中断 pipeline
  → 请求体已传完 → 401；请求体还在传 → 连接 RST → relay 502
```

调用方是 [[Claude Code 与 Agent 客户端]]，链路位置见 [[记忆栈服务拓扑]]。同时会看到 `stage=TDAI_L0 error="This operation was aborted"`（记忆检索同源失败）与 `FORWARD fetch failed`。

# 与隧道故障的区分

两条硬判据：

1. 压测期间 `ssh` 隧道进程 **PID 不变** → 隧道没断
2. 服务器 `sshd` 日志只有 `disconnected by user`（客户端主动），没有网络层超时

排除隧道后，直接查 `docker stats` 里 `tdai-memory-core` 的 CPU 与 `suppressed_skip` 计数。

# 处置与保留风险

止血：`docker restart tdai-memory-core`，CPU 立即回落（实测 100.27% → 0.12%，认证回到 1.6~2.0ms 无抖动，6/6 大请求恢复 200）。重启流程见 [[运维操作手册]]。

但重启只治标——根因是代码里的 20ms 退避。把 `TDAI_SKILL_WORKER_CONCURRENCY` 从 4 降到 1 只能把空转强度降到 1/4，**真实修法是把 `sleep(20)` 改成退避到抑制期满（200ms）**，或在 `peek` 到已抑制 agent 时先阻塞等待而非空转。该文件位于镜像内 `/app/src`，重建镜像会丢失，属于需要向上游反馈的缺陷。

未改动的另一个隐患：`lockTtlMs=600000` 若再次出现僵死锁，忙等会重现。降到 60000 可缩短窗口，代价是极端情况可能重复抽取。

相关的配置生效问题（改了却不生效）见 [[memory-core 配置生效陷阱]]。

# 相关实体

- [[tdai-memory-core]] —— 发生忙等的组件
- [[tdai-proxy]] —— 因认证超时中断 pipeline 的一方
- [[记忆栈服务拓扑]] —— 401/502 在拓扑中的位置
- [[Claude Code 与 Agent 客户端]] —— 观测到报错的调用方
- [[memory-core 配置生效陷阱]] —— 调参时的陷阱
- [[运维操作手册]] —— 标准重启流程
