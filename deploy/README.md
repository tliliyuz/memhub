# 部署规划

> 状态：563fefe 发布版（2026-11-19，备案已过）。机上执行由 `cloud-server-86` 会话负责，任何改变现状的操作需用户确认。

## 0. 本版形态（563fefe）

- 云端（43.142.18.23）跑 4 个容器：ingest-api、worker、kb-api（管理台 + 静态前端）、oauth2-proxy；nginx `/` 与 `/api/v1/kb/` 走 GitHub 登录，`/api/v1/` 仍由设备 token 自鉴权。
- **kb-api 取代 explorer**：图谱页由前端自带 cytoscape 渲染，数据来自 `kb/kg.json`；旧 explorer 容器保留为 compose `legacy` profile，不再默认启动。
- `knowledge/`（markdown 真源）与 `data/`（raw_store）从本地同步到 `/var/lib/memhub/`，由 worker 继续提炼。
- collector 仍在客户端（e4 负责），本版发布后联调 session 采集。

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
| kb-api | `127.0.0.1:8701` | `/` 与 `/api/v1/kb/*`（GitHub 登录后） |
| mcp | 无 | `memhub mcp` 是 stdio 服务，由 agent 客户端拉起，不占端口 |
| explorer（旧） | `127.0.0.1:8703` | 563fefe 起不再部署，`legacy` profile 备查 |
| oauth2-proxy | `127.0.0.1:4180` | 不直接对外；nginx `/oauth2/*` 与 `auth_request` 判决 |

段位约定：memhub 用 8700-8710，只监听 loopback。同机 AI 评测中台用 8200-8299，互不重叠。
`eval.memhub.work` 归评测中台，但需用户配 DNS 与证书；配好之前它只跑回环。

## 3. 资源预算

| 项 | 预算 |
|:---|:---|
| 内存峰值 | ≤1.5 GiB（compose 限额 ingest 384m + worker 640m + kb 384m + oauth2-proxy 128m = 1536m；实测 ingest ≈60MB、worker 抽一枚 60K 字符会话 ≈155MB、kb 重建 437 节点投影 ≈143MB、explorer 旧版 ≈151MB） |
| 磁盘 | ≤12 GiB（knowledge 5G / raw_store 4G 硬上限 / 日志 2G / 余量） |
| raw_store 上限 | `MEMHUB_QUEUE_MAX_BYTES`（`.env.example` 为 1 GiB；磁盘预算硬顶 4 GiB，别超过），超出时 ingest 返回 `1008`，采集端降级 |
| 隔离区清理 | `pending_review/` 中超过 30 天的文件由 purge timer 删除（`--pending-review-days`） |
| 处理副本上限 | `processed_raw/`（raw_store 的完整副本）按 7 天或 `MEMHUB_PROCESSED_MAX_BYTES`（默认 2 GiB）先到先裁 |
| 告警水位 | 磁盘 ≥80% 已用；可用内存 <300 MiB |

同机评测中台：内存按 1.2 GiB 设计（1.5 GiB 为上限），磁盘 10 GiB；Postgres `shared_buffers`/`work_mem` 设上限，MinIO 计入内存与磁盘水位。

说明：上表是 **cgroup 限额（上限）**，不是常驻占用。常驻实际占用约 200-300 MB，两套合计仍远低于 2.2-2.5 GiB 的设计值；限额留足余量是为了突发（大文档抽取、explorer 渲染）不被 OOM 杀掉。

## 4. nginx

- 重写 `memhub.work` vhost（不新开子域）：
  - `/api/` → 127.0.0.1:8700/8701（按前缀分流）
  - `/mcp` → 127.0.0.1:8702
  - `/` → 127.0.0.1:8703（explorer，只读页面；片段见 §6）
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
| kb-api | compose 常驻容器 `memhub/app-kb:0.1.0`，复用 worker wheelhouse + 烘进镜像的 `web/dist`；绑 `127.0.0.1:8701`，由 nginx 挂到 `/` |
| explorer（旧） | 不再部署；需要时 `docker compose --profile legacy up -d explorer`，并把 nginx `/` 改回 8703 |
| purge / rebuild | systemd timer 跑 `docker run --rm` 一次性子命令 |

镜像从 `wheelhouse` 离线构建（`docker build --network=none`），不在机上编译、不连 PyPI：

```bash
docker build --network=none -f deploy/Dockerfile.ingest -t memhub/app:0.1.0 .
docker build --network=none -f deploy/Dockerfile.worker -t memhub/app-worker:0.1.0 .
docker build --network=none -f deploy/Dockerfile.kb     -t memhub/app-kb:0.1.0 .
```

数据库为宿主机 native PostgreSQL 16（`memhub_prod`），容器走 host 网络访问 `127.0.0.1:5432`；
`MEMHUB_DB_URL` 等密钥只存在于 `/etc/memhub/env`（0600），经 `env_file` 注入。
schema 由 `memhub api`（ingest 容器）启动时调 `ensure_schema` 幂等应用，没有单独的 migrate 命令；
563fefe 未新增迁移（仍只有 `0001_state`），旧库启动即打印 `schema: already up to date`。

**顺序约束**：kb-api 启动时会读 `kb/kg.json`（不存在也能起，只是图谱空）；首次部署先同步
`knowledge/`，再起 kb，它在真源变化后自行重建投影。旧 explorer 才要求「先跑一次 rebuild 再起」。替换 nginx 配置时保持 `/api/v1/` 的尾斜杠与 `/api/v1/kb/` 的优先级（`^~`）。

nginx 段（explorer 旧版）保留在上线记录里；563fefe 的完整 vhost 见
`deploy/nginx/memhub.vhost.conf`（`/` 与 `/api/v1/kb/` → 8701，走 `auth_request /__memhub_auth`）。
认证网关为 **oauth2-proxy v7.6.0**（GitHub OAuth，`--github-user` 白名单）：
凭据只写 `/etc/memhub/env`（0600），cookie secret 32 字节随机
（`openssl rand -base64 32`）。**注意三处部署坑**：镜像 distroless 不能配
exec 型 healthcheck；compose 的 `environment: ${VAR}` 会把 env_file 值覆盖成空串，
只能靠 `env_file` 注入；**不要覆盖 `--scope`**——GitHub provider 默认 `user:email read:org`，
v7.6.0 的 EnrichSession 会无条件列组织，缺 `read:org` 时回调 500。回跳原页面还需
`--whitelist-domain=memhub.work`，否则 `rd` 被判非法、登录后只能回 `/`。

kb-api 只监听回环，公网唯一入口是 nginx 的登录墙；健康检查走 `127.0.0.1:8701/healthz`，
不经公网（与 `location = /api/v1/healthz → 404` 同义）。

一次性子命令（timer 用）：

| 命令 | 作用 | 退出码 |
|:---|:---|:---|
| `memhub purge-expired` | 删 25h 外批次记录 + 30 天外隔离文件 + 裁剪 processed_raw | 0 正常 / 2 配置错 |
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
2. 同步 `knowledge/` 与 `data/` 到 `/var/lib/memhub/`（先 knowledge 后 data）
3. 构建三镜像（`--network=none`）→ 备份 `memhub_prod` → `docker compose up -d ingest worker kb oauth2-proxy`
4. 写 nginx vhost（保留 acme webroot）→ `nginx -t` → reload
5. 装 systemd timer（purge / rebuild）
6. 冒烟：`ss -lntp` 只见 127.0.0.1 的 8700/8701/4180；容器内 `/healthz` 200；未登录 `curl -i /api/v1/kb/stats` 得 401 JSON；浏览器 `/` 跳 GitHub 登录后能看到全部知识库概览
7. 观察 24h 磁盘/内存曲线再开全量采集
