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

## 3. 资源预算

| 项 | 预算 |
|:---|:---|
| 内存峰值 | ≤1.0 GiB（ingest 150M / worker 400M / kb 250M / mcp 100M / explorer 100M + Docker 开销） |
| 磁盘 | ≤12 GiB（knowledge 5G / raw_store 4G 硬上限 / 日志 2G / 余量） |
| raw_store 上限 | 4 GiB，超出时 ingest 返回 `1008`，采集端降级 |
| 告警水位 | 磁盘 ≥80% 已用；可用内存 <300 MiB |

同机评测中台预算 1.2-1.5 GiB / 10 GiB。合计约 2.5 GiB / 22 GiB，留 ≥1 GiB 余量给 OS 与突发。

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

## 6. systemd

| unit | 作用 |
|:---|:---|
| `memhub-ingest.service` | uvicorn ingest-api |
| `memhub-worker.service` | 提炼 worker（串行） |
| `memhub-kb.service` | kb-api + MCP |
| `memhub-rebuild.timer` | 定期重建投影（kg/vector/fts） |
| `memhub-disk-guard.timer` | 水位检查与告警 |
| `memhub-git-gc.timer` | 真源仓库 gc |

## 7. 部署顺序

1. 改 daemon.json → reload docker
2. 写 nginx location（保留 acme webroot）→ `nginx -t` → reload
3. 起容器（compose up -d）
4. 装 systemd unit/timer
5. 冒烟：`/healthz`、`/api/v1/ingest/cursor`、`/mcp` 握手
6. 观察 24h 磁盘/内存曲线再开全量采集