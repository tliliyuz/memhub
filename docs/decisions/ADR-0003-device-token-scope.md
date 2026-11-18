# ADR-0003 采集器使用独立 device token

| 属性 | 值 |
|:---|:---|
| 状态 | accepted |
| 日期 | 2026-11-18 |

## 背景

面板现有的 `user_key` 同时授权 `meta/*` 与 `knowledge/*`，每用户最多 20 把，最后一把不可吊销，且**服务端没有设备作用域**。采集器是无人值守的后台服务，若持有 `user_key`：

- 等于把整个面板的读写权限交给一个后台进程；
- 设备泄漏即全量泄漏，无法只吊销一台机器；
- 20 把上限会被多设备/重装耗尽。

## 决策

1. 新增 `POST /devices/register`：桌面端用**自己的**已有凭据调用，换取 `{device_id, device_token}`。
2. `device_token` 仅允许 `/ingest/*`，访问面板接口返回 `1009`。
3. token 只存操作系统凭据库（Credential Manager / Keychain / libsecret），不落任何 json 文件。
4. 每种设备独立吊销：`POST /devices/revoke`。
5. 不复用 PKCE：PKCE 解决"未认证客户端经浏览器取凭据"，采集器永远不做交互式认证。

## 备选与否决理由

| 备选 | 否决理由 |
|:---|:---|
| 采集器直接用 `user_key` | 权限过宽、无法按设备吊销、撞 20 把上限 |
| 复用 SSO 换票流程 | 同上，且 `expires_at` 恒为 null，无法做短期凭据 |
| 用户手动粘贴 token 到 `sources.json` | token 落盘，违反凭据不落盘原则 |

## 后果

- 服务端需新增 devices 表、scope 校验与吊销逻辑。
- 桌面端需把 token 写入凭据库；采集器启动时读取并自我校验。
- 用户换机 = 新注册一台设备；旧设备可吊销，不影响其他机器。