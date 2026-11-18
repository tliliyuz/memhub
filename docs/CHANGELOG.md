# CHANGELOG

## 2026-11-18

- 新仓库建立；确立「无 Proxy」拓扑（ADR-0001）、markdown 真源（ADR-0002）、device token 作用域（ADR-0003）。
- 契约 v0.2：节点 schema、源注册表、采集 API、MCP 工具（`docs/contracts/`）。
- 工程骨架：`src/memhub/contract` 契约模型 + 契约测试；`pyproject.toml`（ruff/mypy strict）；环境键集治理脚本。
- 待办：ingest API、worker、kb 检索、MCP、部署文件、历史数据导入。

## 2026-11-18（追加）

- `feat(ingest)`：采集 API dev stub 可用（内存存储）——`/devices/register`、`/ingest/cursor`、`/ingest/raw`、`/ingest/heartbeat`；Bearer + 设备绑定、`source_rev` 重扫、1004 游标回退、24h 幂等重放、二进制拒收。契约测试 8 条。
- 本地联调：`MEMHUB_DEV_TOKEN=<任意值> PYTHONPATH=src .venv/Scripts/python -m uvicorn memhub.ingest.app:create_app --factory --port 8700`。

## 2026-11-18（最小闭环打通）

- `feat(worker)`：真实 Claude Code 会话（约 4 万字符）→ 40 个知识节点 / 26 条边写入 `knowledge/memhub/`；`kind=question` 缺 `status` 的崩溃已修并加回归测试。
- `feat(kb)`：markdown 真源 → semantica `ContextGraph` 投影（`kb/kg.json`，48 节点 / 26 边），边按完整 id 或唯一 slug 解析，未解析目标在报告中列出。
- `feat(cli)`：`serve` 自动为 explorer 子进程补齐 `PYTHONUTF8` / `PYTHONIOENCODING` / `SEMANTICA_ALLOW_ANONYMOUS`（显式环境变量优先），并打印页面地址；`engine` extra 补 `python-multipart`（explorer 缺它启动即失败）。
- 验证：`http://127.0.0.1:8011/` 页面可见 48 nodes · 26 edges 图谱（decision 10 / fact 17 / pitfall 7 / procedure 6 / preference 4 / entity 2 / question 2）。测试 24 passed，ruff/mypy strict 通过。
- 待办：SQLite 真存储与游标、value_filter、多会话批量、去重合并调参、MCP server、历史导入、云端部署。

## 2026-11-18（MCP 检索组）

- `feat(mcp)`：stdio 传输的 MCP 服务，暴露 `kb_search` / `kb_read` / `kb_related` / `kb_audit_list`；JSON-RPC 2.0 按行分帧，通知不回包，解析/参数/方法错误按 -32700 / -32602 / -32601 区分。
- `feat(kb)`：`kb/query.py` 实现检索组读操作——标题/标签/正文关键词打分（中文补二元组）、默认只看 canonical 并提示候选数、出入边各限 20 条、depth ≤2 邻接、审计问题现算（矛盾/断链/孤立/低置信/陈旧）。
- `feat(cli)`：新增 `memhub mcp --knowledge-dir`；stdio 强制 UTF-8（Windows 管道默认 cp936 会把中文协议写坏）。
- 验证：44 passed，ruff/格式/mypy strict 通过；真实知识库（48 节点）经子进程管道冒烟，中文标题原样返回。远程 `/mcp`（Streamable HTTP）未实现。
- 待办：SQLite 真存储与游标、value_filter、多会话批量、去重合并调参、历史导入、云端部署。