# TIME_CONVENTIONS — 时间与时区规范

| 适用范围 | 时间的存储、解析、展示与业务时区口径 |
| 不负责 | 业务运行周期与幂等键；见各仓的 OPERATION_TIME |

本文件定义时间处理的两条轴：存储与接口使用 UTC 绝对时刻，业务与展示按仓库声明的
`business_timezone` 统一格式化。配置键见
[治理配置契约](../contracts/governance-toml.md)，文档写法见
[DOCUMENT_GOVERNANCE](../guides/DOCUMENT_GOVERNANCE.md)。

## 1. 存储与接口

- 存储与接口一律使用绝对时刻，统一 UTC ISO 8601（以 `Z` 结尾）。
- 时间列使用带时区类型；不得用无时区字符串承载绝对时刻。
- 对外契约字段名前缀按本仓约定，但语义必须是 UTC 绝对时刻。

## 2. 业务时区

- 每个仓在 `governance.toml` 的 `[time] business_timezone` 声明唯一业务时区，
  取 IANA 名称（如 `Asia/Shanghai`）或 `UTC`。
- 业务日切分、报表与界面展示一律转换到该时区后再格式化。
- 未声明 `business_timezone` 时 `time_conventions` 检查整体跳过，便于渐进接入；
  存储与接口的 UTC 口径仍然有效。

## 3. 展示

- 展示必须经过显式时区的格式化函数（如前端传入 `timeZone`，后端显式转换）。
- 禁止把 UTC 串直接截取时钟位或把 `T` 换成空格后展示。
- 禁止在展示层依赖进程或浏览器本地时区推断业务时区。

## 4. 解析与构造

- 禁止无时区地构造「现在」，必须显式指定时区或使用 UTC。
- 禁止按进程时区解析裸时间字符串；外部输入必须带时区或按业务时区显式解释。
- 测试代码可使用简化构造，不参与生产路径的检查。

## 5. 检查与豁免

- 内置禁止规则覆盖无时区构造、按进程时区解析裸时间串、截取 ISO 时钟位与裸
  DATETIME 渲染；命中时 `time_conventions` 失败并给出文件与行。
- `[time] allow_paths` 追加豁免前缀或 glob，用于规则定义文件或历史兼容代码。
- `[[time.forbid]]` 追加本仓专用禁用规则，字段为 `pattern`、`globs` 与 `message`。
- 豁免必须说明理由与退出条件，不得成为无期限绕过。

## 6. 验收

- 时间相关变更执行 `governance verify`，确认 `time_conventions` 通过。
- 新增展示路径时，检查是否显式传入了业务时区。
- 新增解析路径时，检查输入是否带时区或按业务时区显式解释。