# 部署规划

> 状态：563fefe 发布版（2026-11-19，备案已过）。机上执行由 `cloud-server-86` 会话负责，任何改变现状的操作需用户确认。

## 0. 本版形态（563fefe）

- 云端（43.142.18.23）跑 4 个容器：ingest-api、worker、kb-api（管理台 + 静态前端）、oauth2-proxy；nginx `/` 与 `/api/v1/kb/` 走 GitHub 登录，`/api/v1/` 仍由设备 token 自鉴权。
- **kb-api 取代 explorer**：图谱页由前端自带 cytoscape 渲染，数据来自 `GET /api/v1/kb/graph`（直读 PG `kb_*` 表）；不再部署 explorer，也不再有 `kg.json` 投影。
- `knowledge/`（markdown 真源）与 `data/`（raw_store）从本地同步到 `/var/lib/memhub/`，由 worker 继续提炼。
- collector 仍在客户端（e4 负责），本版发布后联调 session 采集。
- **下一版**把知识真源从 markdown 换成 PostgreSQL 的 `kb_*` 表（ADR-0013），`knowledge/` 只作一次性迁移源、迁移后删除；切换步骤见 §6「知识真源切换（markdown → PG，一次性）」。

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
| oauth2-proxy | `127.0.0.1:4180` | 不直接对外；nginx `/oauth2/*` 与 `auth_request` 判决 |

段位约定：memhub 用 8700-8710，只监听 loopback。同机 AI 评测中台用 8200-8299，互不重叠。
`eval.memhub.work` 归评测中台，但需用户配 DNS 与证书；配好之前它只跑回环。

## 3. 资源预算

| 项 | 预算 |
|:---|:---|
| 内存峰值 | ≤1.5 GiB（compose 限额 ingest 384m + worker 640m + kb 384m + oauth2-proxy 128m = 1536m；实测 ingest ≈60MB、worker 抽一枚 60K 字符会话 ≈155MB、kb 历史图谱重建（437 节点 / 2631 边）≈143MB） |
| 磁盘 | ≤12 GiB（knowledge 5G / raw_store 4G 硬上限 / 日志 2G / 余量） |
| raw_store 上限 | `MEMHUB_QUEUE_MAX_BYTES`（`.env.example` 为 1 GiB；磁盘预算硬顶 4 GiB，别超过），超出时 ingest 返回 `1008`，采集端降级 |
| 隔离区清理 | `pending_review/` 中超过 30 天的文件由 purge timer 删除（`--pending-review-days`） |
| 处理副本上限 | `processed_raw/`（raw_store 的完整副本）按 7 天或 `MEMHUB_PROCESSED_MAX_BYTES`（默认 2 GiB）先到先裁 |
| 告警水位 | 磁盘 ≥80% 已用；可用内存 <300 MiB |

同机评测中台：内存按 1.2 GiB 设计（1.5 GiB 为上限），磁盘 10 GiB；Postgres `shared_buffers`/`work_mem` 设上限，MinIO 计入内存与磁盘水位。

说明：上表是 **cgroup 限额（上限）**，不是常驻占用。常驻实际占用约 200-300 MB，两套合计仍远低于 2.2-2.5 GiB 的设计值；限额留足余量是为了突发（大文档抽取、图谱渲染）不被 OOM 杀掉。

## 4. nginx

- 重写 `memhub.work` vhost（不新开子域）：
  - `/api/` → 127.0.0.1:8700/8701（按前缀分流）
  - `/mcp` → 127.0.0.1:8701，**精确匹配**；与 kb-api 同进程，**不**挂 oauth2-proxy 的 `auth_request`，改用独立 Bearer 凭据（鉴权与作用域裁剪在应用内完成）
  - `/` → 127.0.0.1:8701（管理台 SPA，走 GitHub 登录）
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
| kb-api | compose 常驻容器 `memhub/app-kb:0.1.0`，复用 worker wheelhouse + 烘进镜像的 `web/dist`；绑 `127.0.0.1:8701`，由 nginx 挂到 `/`。**连 PG**：`MEMHUB_KB_DB_URL`（运行时 DML 角色，`search_path=kb`）经**独立** `env_file` `/etc/memhub/env.kb` 注入，缺该键启动即失败，不退回 markdown；该文件不含 `MEMHUB_DB_URL` / `PGPASSWORD` / LLM 与设备凭据 |
| purge | systemd timer 跑 `docker run --rm` 一次性子命令 |

镜像从 `wheelhouse` 离线构建（`docker build --network=none`），不在机上编译、不连 PyPI：

```bash
docker build --network=none -f deploy/Dockerfile.ingest -t memhub/app:0.1.0 .
docker build --network=none -f deploy/Dockerfile.worker -t memhub/app-worker:0.1.0 .
docker build --network=none -f deploy/Dockerfile.kb     -t memhub/app-kb:0.1.0 .
```

构建上下文根目录还必须含仓库根的 `prompts/`（worker 镜像会 `COPY prompts /usr/local/lib/python3.12/prompts`；
wheel 不含提示词，漏了这层 `worker --once` 会 `FileNotFoundError`）。

数据库为宿主机 native PostgreSQL 16（`memhub_prod`），容器走 host 网络访问 `127.0.0.1:5432`；
运行态密钥只存在于 `/etc/memhub/env`（0600），经 `env_file` 注入。kb-api 例外：它用独立文件
`/etc/memhub/env.kb`（同样 0600），只放 kb 进程实际读取的键（至少 `MEMHUB_KB_DB_URL`；`/mcp` 入口
用 `MEMHUB_MCP_GRANTS`，按需再拷 `MEMHUB_LOG_LEVEL` /
`MEMHUB_QUEUE_MAX_BYTES` / `MEMHUB_KB_HTTP_PORT`），避免受限容器拿到运行态全权 DSN 与 `PGPASSWORD`。
运行态 5 表由 `memhub api`（ingest 容器）启动时调 `ensure_schema` 幂等应用，没有单独的 migrate 命令；
563fefe 未新增迁移（仍只有 `0001_state`），旧库启动即打印 `schema: already up to date`。

**知识表（`kb_*`）是另一套迁移**（ADR-0013 §4）：建在专用 schema `kb`，版本表 `alembic_version`，
由迁移角色 `MEMHUB_KB_MIGRATE_DB_URL` **带外执行**，不在任何容器启动时跑。kb 镜像已烘入
`alembic.ini` 与 `alembic/`，服务器上没有宿主 venv，按「知识真源切换」小节用一次性容器执行。

**顺序约束**：真源切换到 PG 后，kb-api 只从 `MEMHUB_KB_DB_URL` 取知识，图谱与检索都直读 `kb_*` 表，
不再读写任何文件投影。首次部署**不再**需要先同步
`knowledge/`——它只在一次性迁移时用到；迁移前的旧版仍按原顺序（先 knowledge 后 kb）。替换 nginx
配置时保持 `/api/v1/` 的尾斜杠与 `/api/v1/kb/` 的优先级（`^~`）。

563fefe 的完整 vhost 见
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

rebuild timer 已随投影子系统下线移除：图谱与检索直读 `kb_*` 表，不存在需要定时重建的文件。

注意：
- worker 窗口由常驻容器门控，**不需要** timer；`--once` 只在手动补跑时用。
- 退出码 1 表示部分失败，systemd 侧不要 `SuccessExitStatus=1` 掩盖它。

timer 建议：purge `06:15`；worker 窗口由容器内门控，不需要 timer。

### 知识真源切换（markdown → PG，一次性）

本节覆盖 ADR-0013 的一次性上线：`knowledge/` 从真源降为迁移源，迁移校验通过后删除。
**第 1、3、5、6 步都是生产变更，全部需负责人授权**；本仓库只给出命令与判定标准，不在开发侧代跑。

1. **建对象与角色**（带外、只执行一次；判定见 ADR-0013 §6）
   - 在生产 `memhub_prod` 建 schema `kb`，以及两个角色：`memhub_kb_owner`（对 `kb_*` 有 DDL，Alembic 用）与
     `memhub_kb_app`（只对 `kb_*` 做 DML，kb-api 运行时用）。两者 `search_path` 固定 `kb`，**不授予 `public` 的
     `USAGE`**——运行态 5 表在 `public` 里，PG 15+ 默认对 `PUBLIC` 授 `USAGE`，只靠「另建角色」挡不住。
   - 连接配额建议：`memhub_kb_app` 限 4（连接池 2+2，ADR-0013 §6 的最小可行值），`memhub_kb_owner` 限 2
     （带外 `alembic` 与 `migrate-kb` 各占一条）。加上运行态现有 2+3（ingest）与 1+1（worker），都在
     `max_connections=60` 内。
   - `/etc/memhub/env`（0600）追加 `MEMHUB_KB_DB_URL`（指向 `memhub_kb_app`）与
     `MEMHUB_KB_MIGRATE_DB_URL`（指向 `memhub_kb_owner`）。值只经该文件注入；文档与提交信息只写键名。
   - 另建 `/etc/memhub/env.kb`（0600，归属同前）：kb 容器的独立 env_file，只放 kb 进程读取的键。
     至少 `MEMHUB_KB_DB_URL=` 同一值，且 **DSN 必须自带口令**（`postgresql://memhub_kb_app:<口令>@127.0.0.1:5432/memhub_prod`）：
     独立文件里没有 `PGPASSWORD`，仍按「DSN 不写口令 + PGPASSWORD」写法会直接认证失败。
     `/mcp` 入口需要时一并拷 `MEMHUB_MCP_GRANTS`，以及
     `MEMHUB_LOG_LEVEL` / `MEMHUB_KB_AUTO_REBUILD` / `MEMHUB_QUEUE_MAX_BYTES` / `MEMHUB_KB_HTTP_PORT`
     中实际设置过的项。**不要**把 `MEMHUB_DB_URL`、`PGPASSWORD`、LLM 凭据、设备 token 密钥拷进来：
     kb 用受限角色，只该看到知识表的 DML 权限。
2. **停写**：`docker compose stop kb worker`，等正在跑的 `worker --once` 结束。
   ingest 可以继续跑（只写 `raw_store/` 队列，不碰 `knowledge/`）。
3. **建表**（Alembic 带外执行，不在任何容器启动时跑）：
   ```bash
   docker run --rm --network=host --env-file /etc/memhub/env \
     memhub/app-kb:<tag> alembic -c /app/alembic.ini upgrade head
   ```
   迁移角色只认 `MEMHUB_KB_MIGRATE_DB_URL`，不读 `MEMHUB_DB_URL`。这一步只建 `kb_*` 六表与
   `alembic_version`；运行态 5 表仍由 ingest 启动时自管，两套版本表互不相干。
   **待负责人裁决**：上面用的是「烘进镜像的 alembic + 一次性容器」。备选是服务器上装宿主 venv 跑
   `alembic -c alembic.ini upgrade head`——但机上只有容器、没有宿主 Python，选它要额外维护一套 venv，
   且与镜像的 alembic 版本可能漂移。两种写法都可行，裁决前不要二选一固化到运维脚本。
4. **迁移与校验**（同一镜像，挂载只读的真源）：
   ```bash
   # 4.1 只读统计：不写库、不删文件
   docker run --rm --network=host --env-file /etc/memhub/env \
     -v /var/lib/memhub:/var/lib/memhub:ro --entrypoint memhub memhub/app-kb:<tag> \
     migrate-kb --knowledge-dir /var/lib/memhub/knowledge --schema kb --archives migrate --dry-run
   # 4.2 写库：单事务、按 id 与边三元组 upsert，可重复运行
   ... 同上，去掉 --dry-run
   # 4.3 逐节点、逐边比对内容哈希；不一致非 0 退出
   ... 同上，改用 --verify-only
   ```
   `--archives migrate` 必须与写入一致：`knowledge/` 删掉后，`kb_archives.snapshot` 是归档快照的唯一副本，
   默认的 `skip` 会让迁移后无处可取。`--dry-run` 下两种取值都只统计、不写。
5. **备份**（负责人授权后执行）：`pg_dump -Fc memhub_prod` + `tar` 打包 `/var/lib/memhub/knowledge`，
   存到数据卷之外。这是删除 markdown 与回滚的唯一依据；缺任何一份都不进入第 6 步。
6. **删除 markdown**（负责人授权后执行）：`--delete-source` 只与 `--verify-only` 同用，校验通过也只返回 3、
   不动文件——删除由负责人在服务器执行。删的是整个 `knowledge/`（含 `.kbs.json`、`_trash/`、`_kb_archives/`），
   不是逐文件清理。
7. **切换容器**：三个服务都强制 PG（缺 `MEMHUB_KB_DB_URL` 启动即失败，不退回 markdown），须一起换新镜像：
   ```bash
   docker compose up -d --force-recreate ingest worker kb
   ```
   `MEMHUB_KNOWLEDGE_DIR` 只剩一次性迁移与 `recover-kb-archive` 读取，可以从运行环境撤掉。
   **切换前**若存在 `_kb_archives/pending.json`，先用新 worker 镜像跑
   `memhub recover-kb-archive --knowledge-dir /var/lib/memhub/knowledge`；它没解决就不要开始迁移。
8. **回滚**：旧镜像只认 markdown。回滚 = 停新容器 → 从第 5 步的 `knowledge` 备份恢复 → 起旧镜像与旧 timer。
   切换后 worker / kb 的写入都在 PG 里，回滚会丢掉这部分写入；所以在验收完成（第 9 步）前不要恢复采集与全量写入，
   也别删 PG 表——两套真源短暂并存时，markdown 备份不代表新数据。
9. **验收**：`curl -s 127.0.0.1:8701/healthz` 返回 `ok`；管理台列表与 `GET /api/v1/kb/search` 能查到迁移后的库
   （`matched=bm25`）；`psql -c 'select count(*) from kb.kb_nodes'` 与第 4.3 步报告的节点数一致；图谱页能渲染。
   归档/恢复只用临时样本验收，不要归档线上库做冒烟。

### 整库归档版本升级与回滚

- `kb` 与 `worker` 须使用同一发布提交的 wheel：先停旧 `kb` 和 `worker`，再同时切到新版本。不要混用两代写锁；ingest 不需要停机。同步 nginx 配置和 oauth2-proxy 启动参数，先执行 `nginx -t`；保留旧镜像 ID、服务配置和真源备份。
- 若存在 `knowledge/_kb_archives/pending.json`，不要手动删标记或锁文件。在新 worker 镜像中，以同一卷、同一用户运行 `memhub recover-kb-archive --knowledge-dir /var/lib/memhub/knowledge`。若报告冲突，保持写入暂停、备份现场并核对变更，不覆盖人工修改。成功后无需额外重建投影——图谱与检索直读 `kb_*`。
- 旧版本不识别整库回收站及其写入阻止标记。回滚前先解决未完成的操作，恢复仍须受到阻止的已归档库，或停用旧写者直到另行处理对应队列。保留 `_kb_archives/`；镜像回滚不等于真源回滚，不用旧备份覆盖上线后的正常写入。
- 用临时样本验收整库归档/恢复，勿归档线上库做冒烟；用实际 GitHub 会话核验用户名、头像、退出后需要重新认证，以及 `/portal`、`api.memhub.work`、回调与白名单等既有入口。

## 7. 部署顺序

1. 改 daemon.json → reload docker
2. 同步 `knowledge/` 与 `data/` 到 `/var/lib/memhub/`（先 knowledge 后 data）
3. 确认 `/etc/memhub/env.kb` 已按第 1 步建好（compose 在解析阶段就校验所有服务的 env_file，文件缺失时连 `docker compose up -d ingest worker` 也会失败）→ 构建三镜像（`--network=none`）→ 备份 `memhub_prod` → `docker compose up -d ingest worker kb oauth2-proxy`
4. 写 nginx vhost（保留 acme webroot）→ `nginx -t` → reload
5. 装 systemd timer（purge）
6. 冒烟：`ss -lntp` 只见 127.0.0.1 的 8700/8701/4180；容器内 `/healthz` 200；未登录 `curl -i /api/v1/kb/stats` 得 401 JSON；浏览器 `/` 跳 GitHub 登录后能看到全部知识库概览
7. 观察 24h 磁盘/内存曲线再开全量采集
