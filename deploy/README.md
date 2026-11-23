# 部署规划

> 状态：563fefe 发布版（2026-11-19，备案已过）。机上执行由 `cloud-server-86` 会话负责，任何改变现状的操作需用户确认。

## 0. 本版形态（563fefe）

- 云端（43.142.18.23）跑 4 个容器：ingest-api、worker、kb-api（管理台 + 静态前端）、oauth2-proxy；nginx `/` 与 `/api/v1/kb/` 走 GitHub 登录，`/api/v1/` 仍由设备 token 自鉴权。
- **kb-api 取代 explorer**：图谱页由前端自带 cytoscape 渲染，数据来自 `kb/kg.json`；旧 explorer 容器保留为 compose `legacy` profile，不再默认启动。
- `knowledge/`（markdown 真源）与 `data/`（raw_store）从本地同步到 `/var/lib/memhub/`，由 worker 继续提炼。
- collector 仍在客户端（e4 负责），本版发布后联调 session 采集。

### 采集目标授权：待发布分支的切换要求

此节是发布前检查清单，不表示该修复已部署。

1. 先只读盘点旧队列：按生产者、显式项目、登记能否确认汇总计数，不导出正文、不补填 `project`、不重跑。已归档库不恢复；需要保留的隔离记录应在现有清理周期内单独处理。
2. 核实 ingest、worker 和 kb-api 共享同一个 `/var/lib/memhub` 卷及相同真源目录，ingest 与 worker 指向同一个 PostgreSQL 设备登记库（不新增数据库迁移）。用管理台与 `.kbs.json` 核对已登记的目标；裸目录不等于登记。
3. 无需授权文件：写边界就是「显式 + 已登记 + 活动」，目标以管理台登记为准。部署前用管理台确认要写入的库已登记且未归档即可；如需新库，在管理台创建，不要手工建目录代登记。
4. 暂停旧版入口及 worker，再协调切换 ingest、worker、kb-api，避免混跑。先检查可写列表标记与 `400/1003` 的 `data.reason`，再以合成的已登记来源核对队列、游标和归属。不能在仍可能接收批次的情况下恢复会自动回退建库的旧 worker。
5. 回滚前先暂停采集入口和 worker。旧 ingest 可能无法解析新版本写入批次结果 JSONB 的内部 `_project`；不要假定可在线混滚。先在隔离环境验证回滚兼容性，或保持入口暂停直到新结果均退出 24 小时重放窗口；不开启旧的猜库链路，不删除状态或迁移旧记录作为快速回退。旧版 ingest 若仍配置授权文件，回滚期间需同步恢复该文件。

### 客户端回环联调（只用合成数据）

在同一台隔离 Windows VM／测试账户中运行客户端与服务端夹具。不要使用日常账户的计划任务、配置或凭据库，也不要把服务绑定到非回环地址。在修复分支根目录用已安装仓库开发依赖的虚拟环境运行（PowerShell）：

```powershell
$env:PYTHONPATH = 'src'
python tests/collector_loopback_fixture.py --device-id <测试客户端的UUIDv4> --port 8780
```

- 客户端 API 基址为 `http://127.0.0.1:8780/api/v1`。夹具使用临时目录、内存登记与 Fake worker；不使用继承的 `MEMHUB_*` 配置，不访问数据库或外部模型。使用同一测试设备 ID 完成本地注册，凭据只通过客户端正常流程进入隔离账户的凭据库，不复制到聊天、命令行或配置文件。
- 可写列表应只有 `fixture-left`、`fixture-right`，且 `total:2`、`writable_only:true`。在两个不同的测试目录中各放一份合成 `.jsonl` 文件，分别在界面保存两个库。每份文件包含下列一行、以换行结尾；为避免两份文件内容哈希完全相同，第二份另追加一条不同的合成对话。夹具只对下面这句固定测试文本产生候选。

```json
{"type":"user","message":{"content":"Use ceramic spacers to keep test boards separated during drying."}}
```

- 用隔离账户的实际计划任务触发 collector `--once`。对照界面保存值、该次请求的 `project` 和 `GET /api/v1/kb/stats` 的 `by_project`：应各落一条候选，不出现 `fixture-denied` 或按来源名新建的库。单独用目录存在但未登记的 `fixture-denied` 做控制：应得 `400/1003`、`data.reason=unregistered`，该源游标不动，另一个合法源仍可推送，且不产生新目录。只记录目标 ID、计数和错误码，不记录请求凭据或正文。
- `GET /api/v1/kb/nodes?project=fixture-right&tier=candidate` 只读核对归属，`GET /api/v1/kb/trash/projects` 只读核对整库归档清单（全新夹具预期为空，不须归档或恢复）。用 Ctrl+C 关闭服务，临时目录随进程正常退出清理。直接调用 API 或手动跑 `--once`，均不能代替实际计划任务触发验收。

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
| mcp | 随 kb-api（`127.0.0.1:8701`） | `memhub mcp` 是 stdio 服务，由 agent 客户端拉起、不占端口；HTTP 入口 `= /mcp` 与 kb-api 同进程 |
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
  - `/mcp` → 127.0.0.1:8701，**精确匹配**；与 kb-api 同进程，**不**挂 oauth2-proxy 的 `auth_request`，改用独立 Bearer 凭据（鉴权与作用域裁剪在应用内完成）
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

构建上下文根目录还必须含仓库根的 `prompts/`（worker 镜像会 `COPY prompts /usr/local/lib/python3.12/prompts`；
wheel 不含提示词，漏了这层 `worker --once` 会 `FileNotFoundError`）。

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

### 整库归档版本升级与回滚

- `kb`、`worker` 和一次性 `memhub project` 重建任务须使用同一发布提交的 wheel。先禁用重建 timer 并等正在运行的任务结束，再停旧 `kb` 和 `worker`，然后同时切到新版本。不要混用两代写锁；ingest 不需要重建或停机。同步 nginx 配置和 oauth2-proxy 启动参数，先执行 `nginx -t`；保留旧镜像 ID、服务配置和真源备份。
- 若存在 `knowledge/_kb_archives/pending.json`，不要手动删标记或锁文件。在新 worker 镜像中，以同一卷、同一用户运行 `memhub recover-kb-archive --knowledge-dir /var/lib/memhub/knowledge`。若报告冲突，保持写入暂停、备份现场并核对变更，不覆盖人工修改。成功后重建投影。
- 旧版本不识别整库回收站及其写入阻止标记。回滚前先解决未完成的操作，恢复仍须受到阻止的已归档库，或停用旧写者直到另行处理对应队列。保留 `_kb_archives/`；镜像回滚不等于真源回滚，不用旧备份覆盖上线后的正常写入。
- 用临时样本验收整库归档/恢复，勿归档线上库做冒烟；用实际 GitHub 会话核验用户名、头像、退出后需要重新认证，以及 `/portal`、`api.memhub.work`、回调与白名单等既有入口。

## 7. 部署顺序

1. 改 daemon.json → reload docker
2. 同步 `knowledge/` 与 `data/` 到 `/var/lib/memhub/`（先 knowledge 后 data）
3. 构建三镜像（`--network=none`）→ 备份 `memhub_prod` → `docker compose up -d ingest worker kb oauth2-proxy`
4. 写 nginx vhost（保留 acme webroot）→ `nginx -t` → reload
5. 装 systemd timer（purge / rebuild）
6. 冒烟：`ss -lntp` 只见 127.0.0.1 的 8700/8701/4180；容器内 `/healthz` 200；未登录 `curl -i /api/v1/kb/stats` 得 401 JSON；浏览器 `/` 跳 GitHub 登录后能看到全部知识库概览
7. 观察 24h 磁盘/内存曲线再开全量采集
