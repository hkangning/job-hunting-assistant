// 站内提醒常量与展示映射（接口文档 §3.14；类型枚举见数据库设计 §5、SRS §3.10）
// 四类：FOLLOW_UP 投递跟进 / WRONG_QUESTION 错题复习 / INTERVIEW 待面试 / INFO_MATCH 订阅命中（步骤 22 起出现）

export const REMINDER_TYPES = {
  FOLLOW_UP: { label: '跟进提醒', color: 'var(--m-application)', route: '/applications' },
  WRONG_QUESTION: { label: '错题复习', color: 'var(--m-wrong)', route: '/wrong-questions' },
  INTERVIEW: { label: '面试提醒', color: 'var(--m-interview)', route: '/applications' },
  INFO_MATCH: { label: '校招情报', color: 'var(--m-campus)', route: '/campus' }
}

/** 类型元数据；未知类型兜底为「原值展示、不跳转」——协议将来扩类型时旧前端不炸。 */
export function reminderMeta(type) {
  return REMINDER_TYPES[type] || { label: type || '提醒', color: 'var(--m-system)', route: null }
}

/** 提醒日期显示：今天 / 昨天 / MM-DD（带时间戳的 datetime 只取日期部分）；坏输入原样返回。 */
export function remindDayLabel(value) {
  if (!value) return ''
  const day = String(value).slice(0, 10)
  const p2 = (n) => String(n).padStart(2, '0')
  const now = new Date()
  const fmt = (d) => `${d.getFullYear()}-${p2(d.getMonth() + 1)}-${p2(d.getDate())}`
  if (day === fmt(now)) return '今天'
  const y = new Date(now)
  y.setDate(y.getDate() - 1)
  if (day === fmt(y)) return '昨天'
  if (/^\d{4}-\d{2}-\d{2}$/.test(day)) return day.slice(5)
  return String(value)
}
