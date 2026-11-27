# memhub

Memhub 2.0：本地采集 → 云端提炼 → PostgreSQL 知识真源 → 图谱/检索 → MCP 读取。

- **没有 Proxy**：模型请求路径上没有任何 memhub 组件。设计动机见 [ADR-0001](docs/decisions/ADR-0001-no-proxy-in-request-path.md)。
- **采集端是哑管道**：客户端 collector 只做增量字节搬运与推送，不做解析与判断。
- **云端是唯一有状态者**：value filter → LLM 抽取 → 合并 → PostgreSQL `kb_*` 真源。

## 文档

先读 [docs/tech/architecture.md](docs/tech/architecture.md) 和 [docs/contracts/](docs/contracts/README.md)。开发约定见 [docs/guides/DEVELOPMENT.md](docs/guides/DEVELOPMENT.md)。

## 快速开始

```bash
python -m venv .venv
. .venv/Scripts/activate
python -m pip install -e ".[dev]"
cp .env.example .env
pytest
python scripts/check_env_example_keys.py
```

当前状态：工程骨架与契约模型已就位，采集 API / worker / kb / MCP 尚未实现（见 [docs/CHANGELOG.md](docs/CHANGELOG.md)）。

## 目录

```
docs/          架构、契约、ADR、开发指南
src/memhub/    contract / ingest / worker / kb / mcp / cli
tests/         unit / contract / fixtures
knowledge/     markdown 真源（运行时生成，不入库）
prompts/       各 source_type 抽取 profile
deploy/        compose / nginx / systemd / daemon.json
scripts/       治理检查
```
