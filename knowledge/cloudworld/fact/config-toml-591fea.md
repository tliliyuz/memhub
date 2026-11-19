---
created_at: '2026-11-18T07:26:22Z'
id: cloudworld/fact/config-toml-591fea
kind: fact
project: cloudworld
source:
- captured_at: '2026-11-18T07:26:22Z'
  ref: cloudworld/other/config-toml.md
  type: wiki
supersedes: []
tags: []
tier: canonical
title: config-toml
updated_at: '2026-11-18T07:26:22Z'
---

# 定义

`%APPDATA%\cloud-world\config.toml` 是应用的用户级运行期配置文件，位于用户数据目录而非安装目录，因此不参与打包、不进二进制。

它是 [[打包分层模型]] 的第三层（配置），也是 [[运行期配置与凭据分离]] 中「配置」一侧的载体。

# 关键属性（承载的配置项）

| 配置项 | 作用 | 是否需重编 |
| --- | --- | --- |
| `profile` | 选择 relay 运行 profile（如 `default`） | 不用，改完重启应用 |
| 端口 | relay 监听端口（默认 8787） | 不用 |
| 面板地址 | 界面指向的面板/服务地址 | 不用 |
| `dev_resolve` | 开发期解析相关开关 | 不用 |

# 关系

- 被 [[relay 后台进程]] 在启动时读取（`--config-dir` 指定配置目录）。
- 与 [[系统凭据库]] 共同构成运行期可改、免重编的一侧。
- 与 [[cloud-world.exe]] 的编译期嵌入内容形成对照，见 [[编译期前端嵌入]]。

# Citations

- `crates/desktop/src-tauri/src/lib.rs`
- `crates/desktop/src-tauri/tauri.conf.json`
