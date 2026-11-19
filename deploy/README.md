# 部署规划

> 状态：draft（未上机）。机上执行由 `cloud-server-86` 会话负责，任何改变现状的操作需用户确认。

## 1. 主机

| 项 | 值 |
|:---|:---|
| 主机 | 腾讯云 Lighthouse `43.142.18.23` |
| 规格 | 4C / 3.6 GiB / 59 GiB，Ubuntu 24.04 |
| 域名 | `memhub.work`、`api.memhub.work`（证书至 2027-02-09，certbot.timer 在跑） |

## 2. 端口

| 服务 | 监听 | 对外 |
|:---|:---|:---|
| nginx | 80/443 | 全部 |
| ingest-api | `127.0.0.1:8700` | `/api/v1/ingest/*`、`/devices/*` |
| kb-api | `127.0.0.1:8701` | `/api/v1/kb/*` |
| mcp | `127.0.0.1:8702` | `/mcp` |
| explorer | `127.0.0.1:8703` | `/` |

段位约定：memhub 用 8700-8710，只监听 loopback。同机 AI 评测中台用 8200-8299，互不重叠。
`eval.memhub.work` 归评测中台，但需用户配 DNS 与证书；配好之前它只跑回环。

## 3. 资源预算

| 项 | 预算 |
|:---|:---|
| 内存峰值 | ≤1.4 GiB（compose 限额 ingest 512m + worker 900m；实测 ingest ≈60MB、worker 抽取一枚 60K 字符会话 ≈155MB） |
| 磁盘 | ≤12 GiB（knowledge 5G / raw_store 4G 硬上限 / 日志 2G / 余量） |
| raw_store 上限 | 4 GiB，超出时 ingest 返回 `1008`，采集端降级 |
| 告警水位 | 磁盘 ≥80% 已用；可用内存 <300 MiB |

同机评测中台：内存按 1.2 GiB 设计（1.5 GiB 为上限），磁盘 10 GiB；Postgres `shared_buffers`/`work_mem` 设上限，MinIO 计入内存与磁盘水位。

说明：上表是 **cgroup 限额（上限）**，不是常驻占用。常驻实际占用约 200-300 MB，两套合计仍远低于 2.2-2.5 GiB 的设计值；限额留足余量是为了突发（大文档抽取、explorer 渲染）不被 OOM 杀掉。

## 4. nginx

- 重写 `memhub.work` vhost（不新开子域）：
  - `/api/` → 127.0.0.1:8700/8701（按前缀分流）
  - `/mcp` → 127.0.0.1:8702
  - `/` → 127.0.0.1:8703
  - **保留** `/.well-known/acme-challenge/` 的 webroot，否则续期静默失败
- `api.memhub.work` 当前指向已死的 127.0.0.1:8096，需一并处理，不留死域名。
- `memhub.work/portal` 现为静态页；去留待用户决定（保留为 `/portal/` 或撤掉）。

## 5. 日志与容量（硬要求）

- `daemon.json`：`log-driver=json-file`，`max-size=20m`，`max-file=3`。
  **顺序**：先改 daemon.json 并 `systemctl reload docker`，再起容器——`log-opts` 只对之后新建的容器生效。
- `memhub-disk-guard.timer`：按「已用/总量」算 80% 阈值（不写死可用值），告警附带 top-5 目录。
- 应用日志：按大小滚动，保留 3 份；日志中不得出现 token、密钥、正文原文。

## 6. 运行形态（已定：容器）

| 组件 | 形态 |
|:---|:---|
| ingest-api | compose 常驻容器 `memhub/app:0.1.0`，`network_mode: host`，容器内绑 `127.0.0.1:8700`（**没有 `ports:`**，host 网络下端口映射无效） |
| worker | compose 常驻容器 `memhub/app-worker:0.1.0`，内部窗口门控 21:00-02:00；窗口外常驻 sleep 不退出，`restart: on-failure:5` |
| purge / rebuild | systemd timer 跑 `docker run --rm` 一次性子命令 |

镜像从 `wheelhouse` 离线构建（`docker build --network=none`），不在机上编译、不连 PyPI。
数据库为宿主机 native PostgreSQL 16（`memhub_prod`），容器走 host 网络访问 `127.0.0.1:5432`；
`MEMHUB_DB_URL` 等密钥只存在于 `/etc/memhub/env`（0600），经 `env_file` 注入。

一次性子命令（timer 用）：

| 命令 | 作用 | 退出码 |
|:---|:---|:---|
| `memhub purge-expired` | 删 25h 外的批次记录 | 0 正常 / 2 配置错 |
| `memhub worker --once` | 只跑一轮提炼 | 0 全部成功 / 1 有失败 / 2 配置错 |
| `memhub project --knowledge-dir ... --out ...` | 重建图谱投影 | 0 / 2 |

### timer 完整参数（照抄）

公共参数与 compose 逐项对齐；`--log-opt max-file` 必须是字符串。

purge（建议 `06:15`，oneshot）：

```bash
docker run --rm --name memhub-purge \
  --user 999:987 \
  --env-file /etc/memhub/env \
  --network host \
  --read-only \
  --tmpfs /tmp:size=64m,mode=1777 \
  -v /var/lib/memhub:/var/lib/memhub \
  --log-driver json-file --log-opt max-size=50m --log-opt max-file=3 \
  memhub/app:0.1.0 \
  memhub purge-expired --keep-hours 25
```

rebuild（建议 `06:30`，oneshot；用 worker 镜像，`project` 依赖 `engine` extra 的 semantica）：

```bash
docker run --rm --name memhub-rebuild \
  --user 999:987 \
  --env-file /etc/memhub/env \
  --network host \
  --read-only \
  --tmpfs /tmp:size=64m,mode=1777 \
  -v /var/lib/memhub:/var/lib/memhub \
  --log-driver json-file --log-opt max-size=50m --log-opt max-file=3 \
  memhub/app-worker:0.1.0 \
  memhub project --knowledge-dir /var/lib/memhub/knowledge --out /var/lib/memhub/kb/kg.json
```

注意：
- `--out` 必须落在 `/var/lib/memhub`（根文件系统只读），`kb/` 不存在时由命令自行创建。
- worker 窗口由常驻容器门控，**不需要** timer；`--once` 只在手动补跑时用。
- 退出码 1 表示部分失败，systemd 侧不要 `SuccessExitStatus=1` 掩盖它。

timer 建议：purge `06:15`；rebuild `06:30`；worker 窗口由容器内门控，不需要 timer。

## 7. 部署顺序

1. 改 daemon.json → reload docker
2. 写 nginx location（保留 acme webroot）→ `nginx -t` → reload
3. 起容器（compose up -d）
4. 装 systemd timer（purge / rebuild）
5. 冒烟：`/healthz`、`/api/v1/ingest/cursor`、`/mcp` 握手
6. 观察 24h 磁盘/内存曲线再开全量采集
