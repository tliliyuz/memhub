---
created_at: '2026-11-18T07:26:22Z'
id: cloud-server/fact/memory-core
kind: fact
project: cloud-server
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: cloud-server/concepts/memory-core-配置生效陷阱.md
  type: wiki
supersedes: []
tags:
- 配置
- memory-core
- 陷阱
- Docker
- 运维
tier: canonical
title: memory-core 配置生效陷阱
updated_at: '2026-11-18T07:26:22Z'
---

> 改 memory-core 参数时有四个反复踩的坑——.env 覆盖 ${VAR:-default}、0 被判非法回落到 60、docker run --name 需先删容器、远端 sed 里 $ 被吃掉；附端口归属表与备份回滚约定。

# 定义

[[tdai-memory-core]] 由 `/opt/memhub/start-memory-core.sh` 生成配置并 `docker run` 拉起。修改其参数时有三个反复踩到的坑：**变量优先级**、**容器重建语义**、**远端 sed 转义**。任一处判断错，都会得到「改了但没生效」的假象。

# 坑一：`${VAR:-default}` 会被 `.env` 抢先覆盖

启动脚本里写的是：

```bash
-e TDAI_SKILL_WORKER_CONCURRENCY="${TDAI_SKILL_WORKER_CONCURRENCY:-1}"
```

看起来默认值就是 1。但脚本会 source `/opt/memhub/.env`，而该文件第 172 行导出：

```
TDAI_SKILL_WORKER_CONCURRENCY=4
```

`${VAR:-default}` 只在变量**未设置或为空**时取默认值，变量已存在时直接用它。所以**改脚本默认值无效，必须改 `.env`**。

实测证据：改完脚本、重建容器后 `docker inspect` 仍显示 `=4`；改 `.env` 并再次重建才变成 `=1`。

排障顺序：`docker inspect <container> --format "{{range .Config.Env}}{{println .}}{{end}}"` 看**实际生效值**，不要看脚本。

# 坑二：`0` 不是「关闭」，而是「回落到 60」

`skill-config.ts` 的校验逻辑：

```js
const DEFAULT_WORKER_CONCURRENCY = 60;
const parsed = Number.parseInt(envConcurrencyRaw, 10);
if (Number.isInteger(parsed) && parsed > 0 && String(parsed) === envConcurrencyRaw.trim()) {
  workerConcurrency = parsed;
} else {
  logger.warn(`TDAI_SKILL_WORKER_CONCURRENCY=${envConcurrencyRaw} invalid (must be positive integer); ignored`);
}
```

**必须是正整数**。设成 `0` 会被判非法并忽略，然后落到默认 **60** —— 比原来的 4 还糟 15 倍。想关闭功能必须另找开关（当前版本没有 disable 标志），只能靠调小并发数。

`WORKER_CONCURRENCY` 与 `TDAI_SKILL_WORKER_CONCURRENCY` 是两个独立变量，前者控制通用 worker。调这个变量的动机见 [[skill worker 空转与认证超时级联]]。

# 坑三：脚本用 `docker run --name`，必须先删容器

脚本只有 `docker run -d --name "$CONTAINER"`，**没有前置 `docker rm`**，直接重跑会因容器名冲突失败。正确顺序：

```bash
docker rm -f tdai-memory-core
bash /opt/memhub/start-memory-core.sh
```

脚本自身会做健康等待（最长 90s）与 admin key 校验，输出 `[ok] tdai-memory-core healthy` / `auth/verify 200` 才算成功。这与 [[容器化部署与重建语义]] 是同一件事的具体操作面。

# 坑四：远端 sed 里的 `$` 会被吃掉

想替换 `${TDAI_SKILL_WORKER_CONCURRENCY:-4}` 这类含 `$` 的模式时，经过 `ssh` 这一层转义后模式常匹配不到、且 `sed` 静默成功。改用**行号定位**最稳：

```bash
sed -i "260s/:-\x34/:-\x31/" /opt/memhub/start-memory-core.sh
sed -n "260p" /opt/memhub/start-memory-core.sh   # 必须回读确认
```

改任何配置后都要回读确认，不要假设 sed 成功。

# 端口归属（B 机 VM-0-10-ubuntu）

| 端口 | 归属 | 说明 |
|---|---|---|
| 8420 | tdai-memory-core | gateway + 认证服务（`/v3/meta/auth/verify`） |
| 8424 | tdai-memory-hub | 知识 API（wiki / code-graph） |
| 8125 | tdai-memory-hub | 面板 |
| 8096 | tdai-proxy | 记忆注入 / 上游转发 |
| 3425 | magpie | 模型网关 |
| 3430 | magpie | 网关 Web UI（`MAGPIE_WEB_KEY`） |

全部只绑 `127.0.0.1`，远程访问必须走 SSH 隧道（见 [[回环绑定与 SSH 隧道访问]]）。注意 `magpie` 绑的是 `172.17.0.1:3425`（docker 网桥），因此**从宿主机 `curl 127.0.0.1:3425` 得到 `000` 属正常**，容器内用 `host.docker.internal:3425` 才通。

# 变更前必备份

```bash
cp -a /opt/memhub/.env /opt/memhub/.env.bak-<用途>-$(date +%Y%m%d%H%M%S)
cp -a /opt/memhub/start-memory-core.sh /opt/memhub/start-memory-core.sh.bak-<用途>-$(date +%Y%m%d%H%M%S)
```

回滚：恢复备份 → `docker rm -f tdai-memory-core` → 重跑启动脚本。

# 相关实体

- [[tdai-memory-core]] —— 被配置的组件
- [[tdai-memory-hub]] —— 持有 8424/8125 两个端口的相邻组件
- [[容器化部署与重建语义]] —— 「重建才生效」的上位语义
- [[回环绑定与 SSH 隧道访问]] —— 端口只绑回环后的访问方式
- [[记忆栈服务拓扑]] —— 端口在拓扑中的角色
- [[skill worker 空转与认证超时级联]] —— 调参要解决的故障
- [[运维操作手册]] —— 标准操作序列
