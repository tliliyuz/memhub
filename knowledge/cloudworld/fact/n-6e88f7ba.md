---
created_at: '2026-11-18T07:26:22Z'
id: cloudworld/fact/n-6e88f7ba
kind: fact
project: cloudworld
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: cloudworld/concepts/看门狗单实例互斥.md
  type: wiki
supersedes: []
tags:
- 方案
- watchdog
- SSH隧道
- 进程互斥
- 运维
tier: canonical
title: 看门狗单实例互斥
updated_at: '2026-11-18T07:26:22Z'
---

> memhub-tunnel-watchdog.ps1 必须全机唯一实例运行；两条实例会互拆对方的 SSH 隧道，且改脚本后旧进程不热加载，是「隧道莫名重建、502 时有时无」的隐蔽成因。

# 定义

[[SSH 隧道过渡方案]] 的存活由 `scripts/memhub-tunnel-watchdog.ps1` 常驻维持（三条 SSH 隧道 + [[本地 relay]]）。该脚本必须**全程只有一个实例运行**：一旦出现两个以上实例，它们会把对方启动的隧道当野进程杀掉，形成互拆。

# 为什么必须互斥（2026-11-16 实测）

## 杀隧道是按命令行匹配，不认归属

```powershell
$needle = "127.0.0.1:${localPort}:"
# 杀掉所有命令行含该转发的 ssh —— 包括对方实例刚启动的那条
```

所以两条看门狗同时跑 → 互相拆对方刚建好的隧道 → 隧道每几分钟重建一次。

## 更隐蔽的一层：改脚本不生效

实测现场：

- `pid 38932` 启动于 `11-13 17:15:25`
- 脚本最后一次修改 `11-13 17:17:03`

进程启动 **2 分钟后**脚本才被改。PowerShell 在启动时把脚本读进内存，**不热加载**，该进程继续跑加"忙碌保护"之前的旧逻辑。

两条判据（缺一不可）：

1. `watchdog.log` 当天 `skip rebuild` 计数为 **0** —— 保护从未触发过
2. 日志文案与脚本不符：现脚本打印 `rebuilding (no active connections)`，实际日志只有 `rebuilding`

后果：`15:55:25` 直接 `stopped tunnel 'gateway' ssh (pid 3196)`，把正在传输的 200~400KB 请求掐断，relay 报 `502 client error (SendRequest)`（详见 [[隧道分层与 502 归因]]）。当天 relay 200/502 = 34/26，失败率 43%；同日 `DOWN -> restarting` 30 次。

# 修复：命名互斥量

```powershell
$mutexName     = 'Global\CloudWorld-MemHub-Watchdog'
$mutexCreated  = $false
$watchdogMutex = [System.Threading.Mutex]::new($true, $mutexName, [ref]$mutexCreated)
if (-not $mutexCreated) { exit 0 }
```

要点：

- 必须放在脚本最前（`$ErrorActionPreference` 之后），早于任何日志写入，否则拿不到锁的实例也会污染日志
- 进程退出时操作系统自动释放锁，不会因上次崩溃而永久卡死
- 计划任务用「每分钟触发一次」做保活：拿到锁的实例长驻，其余实例秒退；主实例真死掉后下一次触发自然接手（最长 60 秒空窗）

验证方式：

- 手动再起一个实例，第二个应静默退出、不写日志
- `[System.Threading.Mutex]::new($false, $name, [ref]$c)` 返回 `createdNew=False` 表示锁已被持有
- 进程列表里 watchdog 实例数恒为 1

# 计划任务自身的坑

`MultipleInstances=IgnoreNew` **不能**保证不重复拉起。实测任务状态 `Running`、`LastResult=0x800710E0 (ERROR_REQUEST_ABORTED)`，同时存在两条 pwsh 实例。

# 一个自己会踩的坑

按命令行筛选进程时，**当前进程也会命中**（因为命令行文本里就含着那个脚本路径），结果是命令把自己杀掉、返回 `exit 4294967295 (-1)`：

```powershell
# 错：自杀
Get-CimInstance Win32_Process -Filter "Name='pwsh.exe'" |
  Where-Object { $_.CommandLine -like '*memhub-tunnel-watchdog*' }

# 对：排除自身
Where-Object { $_.ProcessId -ne $PID -and $_.CommandLine -like '*memhub-tunnel-watchdog*' }
```

# 相关实体

- [[watchdog 计划任务]] —— 承载该脚本的计划任务实体
- [[relay 后台进程]] —— 同一脚本维持的另一半
- [[SSH 隧道过渡方案]] —— 互斥保护的对象
- [[隧道分层与 502 归因]] —— 互拆造成的可见故障
- [[cloud-world.exe]] —— 被该进程长期占用的二进制
