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

// ---------- 岗位 / 类型 / 采集状态（接口文档 §3.16，步骤 23） ----------

/** 岗位类型（job_posting.job_type）。 */
export const JOB_TYPE_META = {
  CAMPUS: { label: '校招' },
  INTERN: { label: '实习' },
  SOCIAL: { label: '社招' }
}

/** 活动信息类型（campus_event.info_type；`JOB` 仅订阅维度用，不在本表）。 */
export const INFO_TYPE_META = {
  TALK: { label: '宣讲会' },
  FAIR: { label: '双选会' }
}

/** 入库通道（job_posting.ingest_source）。 */
export const INGEST_SOURCE_META = {
  AUTO: { label: '自动抓取' },
  FEED: { label: '我投喂的' }
}

/**
 * 日历事件类型（接口文档 §3.16 `/calendar`）：label 为中文名，className 供组件挂色点
 * ——颜色属样式层，定义在组件 scoped CSS（活动取模块色、笔试/面试取投递状态色，系统设计 §4.5.1）。
 */
export const CALENDAR_TYPE_META = {
  TALK: { label: '宣讲会', className: 'is-talk' },
  FAIR: { label: '双选会', className: 'is-fair' },
  EXAM: { label: '笔试', className: 'is-exam' },
  INTERVIEW: { label: '面试', className: 'is-interview' }
}

/** 源采集状态（crawl_source.last_status）：type 直接给 el-tag 用。 */
export const CRAWL_STATUS_META = {
  OK: { label: '成功', type: 'success' },
  FAILED: { label: '失败', type: 'danger' },
  BLOCKED: { label: '受限', type: 'warning' }
}

export function jobTypeLabel(value) {
  return JOB_TYPE_META[value]?.label || ''
}

export function infoTypeLabel(value) {
  return INFO_TYPE_META[value]?.label || ''
}

export function ingestSourceLabel(value) {
  return INGEST_SOURCE_META[value]?.label || ''
}

/** 未知类型兜底：空 label + 中性色类——协议扩类型时旧前端不炸。 */
export function calendarTypeMeta(value) {
  return CALENDAR_TYPE_META[value] || { label: '', className: 'is-unknown' }
}

export function crawlStatusMeta(value) {
  return CRAWL_STATUS_META[value] || { label: '未知', type: 'info' }
}
