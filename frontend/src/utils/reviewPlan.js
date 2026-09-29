/**
 * 错题复习的时间文案（纯函数）。
 *
 * 档位（1/3/7/15 天）是内部机制，界面上只说人话——"什么时候再来复习"。
 * 列表与复习视图共用本模块，避免两处各写一份、一处改了另一处漏改。
 */

/** 与项目其他页面同口径的兼容解析（后端给 `YYYY-MM-DD HH:mm:ss`）。 */
function toDate(text) {
  return new Date(String(text || '').replace(/-/g, '/'))
}

/** 距今天数（向上取整；已到期为 0 或负，坏输入按 0 处理）。 */
function daysUntil(nextReviewAt, now = new Date()) {
  const diff = toDate(nextReviewAt) - now
  return Number.isNaN(diff) ? 0 : Math.ceil(diff / 86400000)
}

/** 列表条目的复习时间文案。 */
export function dueText(nextReviewAt, now = new Date()) {
  const days = daysUntil(nextReviewAt, now)
  return days <= 0 ? '今天该复习' : `${days} 天后复习`
}

/** 复习判定后的下次复习文案（含日期）。 */
export function nextPlanText(nextReviewAt, now = new Date()) {
  const days = daysUntil(nextReviewAt, now)
  const md = String(nextReviewAt || '').slice(5, 10)
  if (days <= 0) return `今天（${md}）`
  if (days === 1) return `明天（${md}）`
  return `${days} 天后（${md}）`
}
