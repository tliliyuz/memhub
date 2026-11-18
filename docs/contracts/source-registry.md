# 本地源注册表 `sources.json`

> 版本: 0.1
> 由桌面端（agent-console）写入，采集器只读。位置：Windows `%APPDATA%\memhub\sources.json`，macOS `~/Library/Application Support/memhub/sources.json`，Linux `~/.config/memhub/sources.json`。

## 1. 结构

```json
{
  "version": 1,
  "device_id": "applesay-win-01",
  "collector": {
    "enabled": true,
    "scan_interval_sec": 300,
    "max_batch_bytes": 8388608,
    "quiet_hours": ["23:00-07:00"]
  },
  "sources": [
    {
      "id": "cc-sessions",
      "name": "Claude Code sessions",
      "type": "sessions",
      "path": "C:\\Users\\Applesay024\\.claude\\projects",
      "file_glob": "**/*.jsonl",
      "enabled": true,
      "project": "auto",
      "exclude": ["**/subagents/**"],
      "scan_interval_sec": 300
    },
    {
      "id": "wiki-export",
      "name": "本地 wiki 导出",
      "type": "wiki",
      "path": "D:\\workplace\\export_memhub\\me\\wiki",
      "file_glob": "**/*.md",
      "enabled": true,
      "project": "auto"
    }
  ]
}
```

## 2. 字段

| 字段 | 必填 | 说明 |
|---|---|---|
| `version` | ✓ | 当前 1；结构变更时递增，采集器拒绝未知版本 |
| `device_id` | ✓ | **首次运行由采集器生成的随机 UUID v4**，落在 state 目录；不使用硬件指纹（换硬件/重装即变，且涉及隐私） |
| `collector.enabled` | ✓ | 用户总开关 |
| `collector.scan_interval_sec` | | 默认 300 |
| `collector.max_batch_bytes` | | 单次推送上限，默认 8MiB；超出拆批 |
| `collector.quiet_hours` | | 可空；该时段不推送 |
| `sources[].id` | ✓ | 设备内唯一，`[a-z0-9-]+`；改名即视为新源（游标从零开始，服务端按 id 去重不会重复入库） |
| `sources[].type` | ✓ | `sessions` \| `wiki` \| `docs`；决定云端 prompt profile 与解析器 |
| `sources[].path` | ✓ | 绝对路径；manifest 外路径由桌面端在 UI 里让用户选 |
| `sources[].file_glob` | | 默认按 type：sessions→`**/*.jsonl`，wiki/docs→`**/*.md` |
| `sources[].enabled` | | 默认 true |
| `sources[].project` | | 归入哪个知识库项目；`auto` 由云端按路径/内容推断 |
| `sources[].exclude` | | glob 排除列表 |
| `sources[].scan_interval_sec` | | 覆盖全局 |

## 3. 写入约定

- 桌面端**原子写**（临时文件 + rename），采集器监听 mtime 后重载配置。
- 采集器**不得**修改 `sources.json`；它自己的进度另存 `state/<source_id>.json`（`cursor`、`source_rev`、`last_scan_at`、`skipped` 计数）。
- **禁止**：`sources.json`、`state/*.json`、任何采集器落盘文件里都不得出现 token、key、密码。`device_token` 只存操作系统凭据库（Windows Credential Manager / macOS Keychain / libsecret），由桌面端写入，采集器只读。
- 删除一个 source 后采集器停止推送，但**不通知云端删除数据**；清理是云端能力（`DELETE /ingest/source/{id}`，需显式调用）。

## 4. 采集器行为

1. 读取 `sources.json`；对每个 enabled 源，按 `file_glob` 扫目录。
2. 与云端对齐游标：`GET /ingest/cursor?device_id=..&source_id=..`（带 Bearer）。
3. 对本机 `state/<source_id>.json` 与云端游标取**较新者**（换机/重装后以云端为准，避免重推）。
4. 增量提取按文件追加语义：sessions 用 `(path, byte_offset)`，wiki 用 `(path, mtime, sha256)`。
5. **文件替换检测**：本地 `size < cursor.offset` 或 `mtime` 变小 → 该文件从 0 重扫，并递增 `source_rev` 随批次上报。
6. **Windows 文件系统**：跳过 reparse point 与 `FILE_ATTRIBUTE_OFFLINE` 占位文件（OneDrive/网络盘读取会触发下载或失败），跳过数量按类型计入心跳 `skipped`。
7. 打包成 `.jsonl` 或 `.txt` 容器（见 ingest-api.md），压缩后推送。
8. 成功后落本地 state；失败按契约退避。队列到上限时暂停并在心跳报 `paused`，不丢数据。

## 5. 隐私边界（必须在客户端 UI 明确展示）

- 只上传文本内容，**不上传**文件元数据之外的任何信息（不采集环境变量、凭据、浏览器数据）。
- `exclude` 支持排除敏感目录；客户端另提供全局"暂停采集"。
- 采集器本地日志只记录路径与字节数，不落正文。