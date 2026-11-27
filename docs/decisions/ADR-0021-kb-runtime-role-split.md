# ADR-0021 kb 运行态角色拆分与连接预算

| 属性 | 值 |
|:---|:---|
| 状态 | accepted |
| 日期 | 2026-11-27（负责人裁决：采用拆独立运行态角色） |

## 背景

ADR-0013 §6 为 kb-api 建立受限角色 `memhub_kb_app`（只对 schema `kb` 下的 `kb_*` 做 DML），
当时假设只有管理台使用它。ADR-0020 之后，ingest 用 `create_runtime_store()` 读 `kb_projects`
校验采集与上传目标，worker 与 CLI 用同一个工厂写 `kb_*`，三者都取 `MEMHUB_KB_DB_URL`；
连接池常量 `RUNTIME_POOL_SIZE=2 / RUNTIME_MAX_OVERFLOW=2` 按「单进程独占角色」设定，
角色 `CONNECTION LIMIT` 是 4。

线上实测（2026-11-27）：ingest、worker、kb 三个容器各持 2 条连接，合计 6 > 4；任何并发
（首页拉 graph 最明显）都会被 PG 拒绝，3 小时 `/api/v1/kb/graph` 等接口 500 82 次，
日志 `too many connections for role "memhub_kb_app"` 6 小时 240 次。单纯调大上限只是把
三个进程的池相加当上限，某进程突发仍会挤掉其它进程，且预算不可核算。

## 决策

1. **按进程组拆两个运行态角色**：
   - kb-api（管理台 / MCP）继续用 `memhub_kb_app` + `MEMHUB_KB_DB_URL`；
   - ingest、worker 与运行时 CLI 子命令（`memhub ingest` / `worker` / `memory-aggregate`）
     改用新角色 `memhub_rt_app` + 新键 `MEMHUB_KB_RT_DB_URL`。
   - 带外管理工具（`migrate-kb` 等）不是常驻进程，仍用 `--dsn` 或 `MEMHUB_KB_DB_URL`，
     不参与连接预算核算。
2. **权限相同、边界不缩**：两个角色都是 schema `kb` 的 `USAGE` + `kb_*` 的
   `SELECT/INSERT/UPDATE/DELETE`，均不对 `public` 授权。拆分的目的是连接预算与凭据轮换
   相互独立，不承担表级隔离；表级边界仍由 schema `kb` 与 ADR-0013 §6 的受限角色原则保证。
3. **失败语义显式**：缺 `MEMHUB_KB_RT_DB_URL` 时 ingest / worker / CLI 抛 `KbDsnMissing`
   并拒绝启动；kb-api 缺 `MEMHUB_KB_DB_URL` 同样失败。**不互相回退**：ingest/worker 不会
   因为没配新键就退回 `MEMHUB_KB_DB_URL`，否则会静默回到冲突状态。
4. **池参数按进程**：kb-api 与 ingest 用 `2+2`；worker 单并发处理批次，用 `1+1`。
5. **角色连接上限公式**：

   ```text
   角色上限 = Σ（使用该角色的容器数 × (pool_size + max_overflow)）+ 运维余量(2)
   ```

   据此：`memhub_rt_app` = (2+2) + (1+1) + 2 = **8**；`memhub_kb_app` = (2+2) + 2 = **6**。
   ALTER 前先用 `SELECT rolname, rolconnlimit FROM pg_roles WHERE rolcanlogin` 核算
   全实例总额，必须满足 `Σ rolconnlimit ≤ max_connections − 3`（超级用户预留）；超限时先
   下调其他角色或由负责人决定提高 `max_connections`，不得无视该约束上线。
6. **env 拆分**：ingest / worker 用的 `/etc/memhub/env` 新增 `MEMHUB_KB_RT_DB_URL`，
   kb-api 用的 `/etc/memhub/env.kb` 保留 `MEMHUB_KB_DB_URL`。容器全部切到新键后可把
   `MEMHUB_KB_DB_URL` 从 `/etc/memhub/env` 移除，减少暴露面；该移除是独立运维步骤。
7. **并发验收**：新增 `scripts/kb_concurrency_smoke.py`，同时并发请求 graph / stats / nodes，
   要求全部非 5xx 且服务端日志无 `too many connections`。脚本只读，不写库。

## 备选与否决理由

- **只调大 `CONNECTION LIMIT`**：否决。上限只是把三进程的最坏和写进一个数，任一进程突发仍
  会挤占其他进程，且「每个角色一个预算」无法分别核算。
- **共用角色 + 把池预算写死为常量**：否决。三进程 ×(2+2) 的最坏值是 12，与任何足够紧的
  上限都冲突；共用角色无法区分「kb 突发」与「worker 批量写入」。
- **再拆一个 ingest 专用只读角色**：暂不采用。ingest 只读 `kb_projects`，但把它单列为第三
  个角色会让凭据与部署步骤翻倍，收益有限；若后续 ingest 出现连接压力再按同一公式另立。

## 后果

- 多一把凭据与一条 env 键；部署、`docs/tech/ENVIRONMENT.md`、`deploy/README.md` 与
  `.env.example` 同步更新，`.env` 同次补空键。
- 生产需要带外执行建角色、GRANT、`ALTER ROLE ... CONNECTION LIMIT`，并把
  `MEMHUB_KB_RT_DB_URL` 写入两台容器的 env；由负责人授权后执行。
- kb-api 与 ingest/worker 的凭据可以各自轮换，单侧泄露不影响另一侧。
