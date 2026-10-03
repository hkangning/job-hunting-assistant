// 校招情报常量与展示口径（接口文档 §3.16；状态枚举见数据库设计 §5）
// 系统设计 §4.8 第 3 条：信息状态不复用投递状态色——CHANGED 用角标、EXPIRED 用灰化表达。

/** 信息状态元数据：changed = 打「已变更」角标；muted = 整行灰化。 */
const EVENT_STATUS_FLAGS = {
  ACTIVE: { changed: false, muted: false },
  CHANGED: { changed: true, muted: false },
  EXPIRED: { changed: false, muted: true }
}

/** 状态判定；未知 / 空值兜底为普通态——协议将来扩状态时旧前端不炸。 */
export function campusEventStatus(status) {
  return EVENT_STATUS_FLAGS[status] || { changed: false, muted: false }
}

/** 来源站点：逗号分隔多来源 → 数组（逐项 trim、滤空）；非字符串 / 空值返回 []。 */
export function splitSourceSites(value) {
  if (typeof value !== 'string') return []
  return value
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)
}

/** 概览行的来源站点摘要：单来源原样；多来源显示首个 + “+N”（完整列表走 title 悬浮）。 */
export function sourceSiteBrief(value) {
  const sites = splitSourceSites(value)
  if (!sites.length) return ''
  return sites.length === 1 ? sites[0] : `${sites[0]} +${sites.length - 1}`
}
