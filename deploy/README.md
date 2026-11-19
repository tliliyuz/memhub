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
| explorer | `127.0.0.1:8703` | `/`（oauth2-proxy 凭据到位后；此前 nginx 不挂） |
| oauth2-proxy | `127.0.0.1:4180` | 不直接对外；nginx `/oauth2/*` 与 `auth_request` 判决 |

段位约定：memhub 用 8700-8710，只监听 loopback。同机 AI 评测中台用 8200-8299，互不重叠。
`eval.memhub.work` 归评测中台，但需用户配 DNS 与证书；配好之前它只跑回环。

## 3. 资源预算

| 项 | 预算 |
|:---|:---|
| 内存峰值 | ≤1.4 GiB（compose 限额 ingest 384m + worker 640m + explorer 384m；实测 ingest ≈60MB、worker 抽一枚 60K 字符会话 ≈155MB、explorer 渲染 ≈151MB） |
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
| explorer | compose 常驻容器，复用 worker 镜像（需要 engine extra），绑 `127.0.0.1:8703`，由 nginx 挂到 `/`；`HOME`/`TMPDIR` 指到 tmpfs |
| purge / rebuild | systemd timer 跑 `docker run --rm` 一次性子命令 |

镜像从 `wheelhouse` 离线构建（`docker build --network=none`），不在机上编译、不连 PyPI。
数据库为宿主机 native PostgreSQL 16（`memhub_prod`），容器走 host 网络访问 `127.0.0.1:5432`；
`MEMHUB_DB_URL` 等密钥只存在于 `/etc/memhub/env`（0600），经 `env_file` 注入。

**顺序约束**：explorer 读的是 rebuild 产出的 `kg.json`，**先跑一次 rebuild、再起 explorer**。图谱不存在时 `memhub serve` 直接 exit 2，`on-failure:5` 会让它连续重启 5 次后停住——这是有意的，别改 `unless-stopped` 把错误藏进重启循环。

nginx 需要再加一段（explorer，只读可视化）：

```nginx
location / {
    auth_request /__explorer_auth;          # oauth2-proxy 凭据到位前不启用
    error_page 401 = @explorer_login;
    proxy_pass http://127.0.0.1:8703;
    proxy_http_version 1.1;
    proxy_set_header Connection "";
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 60s;
}
```

完整 vhost 草案（含 `/oauth2/*`、`/__explorer_auth` 判决段、ACME webroot 与
`/api/v1/` 的优先级说明）在 `deploy/nginx/memhub.vhost.conf`。
认证网关已定为 **oauth2-proxy**（用户拍板，不做 basic auth 过渡）：
凭据（GitHub OAuth App 的 client_id / client_secret / cookie secret）到位前
`location /` 保持现状，explorer 容器先跑但不挂 nginx。cookie secret 32 字节
随机（`openssl rand -base64 32`），只写 `/etc/memhub/env`（0600）。

注意 explorer 的 API 只允许回环访问（`SEMANTICA_ALLOW_ANONYMOUS=true` 下无鉴权），
nginx 把它挂到公网前请确认只暴露只读页面；需要登录墙时在 nginx 层加 basic auth。

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
2. 写 nginx location（保留 acme webroot）→ `nginx -t` → reload
3. 起容器（compose up -d）：先 ingest / worker；**先跑一次 rebuild 再起 explorer**
4. 装 systemd timer（purge / rebuild）
5. 冒烟：`/healthz`、`/api/v1/ingest/cursor`、`/`（explorer 页面）、`/mcp` 握手
6. 观察 24h 磁盘/内存曲线再开全量采集
