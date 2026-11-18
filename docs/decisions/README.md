# 架构决策记录（ADR）

命名：`ADR-NNNN-<topic>.md`，一旦接受不修改正文；结论变化时新增一条并互相引用。

| 编号 | 标题 | 状态 |
|:---|:---|:---|
| [ADR-0001](ADR-0001-no-proxy-in-request-path.md) | 记忆能力不进入模型请求路径 | accepted |
| [ADR-0002](ADR-0002-markdown-source-of-truth.md) | markdown 为真源，图谱/向量为可重建投影 | accepted |
| [ADR-0003](ADR-0003-device-token-scope.md) | 采集器使用独立 device token，不复用面板 user_key | accepted |

模板：

```markdown
# ADR-NNNN 标题

| 属性 | 值 |
|:---|:---|
| 状态 | proposed / accepted / superseded by ADR-XXXX |
| 日期 | YYYY-MM-DD |

## 背景
## 决策
## 备选与否决理由
## 后果
```