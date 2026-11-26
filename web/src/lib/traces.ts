/** 调用轨迹页的纯函数：不依赖 DOM 与网络，便于单测。 */

/** 凭据显示：优先名称，其次凭据摘要前 12 位，都没有则 unknown（规格 §2.2）。 */
export function credentialLabel(credential: { id: string | null; name: string | null }): string {
  return credential.name || credential.id || 'unknown'
}

/** 近 N 天的起点（ISO，UTC）；`now` 可注入，调用方的日期对象不被修改。 */
export function sinceFromDays(days: number, now: Date = new Date()): string {
  return new Date(now.getTime() - days * 24 * 60 * 60 * 1000).toISOString()
}

/** 漏斗转化率：分母为 0 时没有定义，显示 `—`（规格 §7）。 */
export function formatRatio(value: number, denominator: number): string {
  return denominator === 0 ? '—' : `${value.toFixed(2)}×`
}

/** 平均每次列出的工具数：没有成功列工具时为 `—`（规格 §7）。 */
export function formatAverageTools(value: number, listings: number): string {
  return listings === 0 ? '—' : String(value)
}
