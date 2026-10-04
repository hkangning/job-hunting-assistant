/**
 * 站内日历的纯函数（FR-022 / 接口文档 §3.16 `/calendar`）：月份区间、月网格、按日分组。
 *
 * 全部零依赖、不读全局状态——日期一律用**本地时间**构造与格式化（不经过 `toISOString`
 * 的时区往返，否则东八区会在月初 / 月末差一天）。
 */

/** 本地日期 → `YYYY-MM-DD`。 */
export function dateKey(date) {
  const y = date.getFullYear()
  const m = String(date.getMonth() + 1).padStart(2, '0')
  const d = String(date.getDate()).padStart(2, '0')
  return `${y}-${m}-${d}`
}

/** 某月整月区间（月初 / 月末），供 `/calendar` 的 start / end。 */
export function monthRange(cursor) {
  const first = new Date(cursor.getFullYear(), cursor.getMonth(), 1)
  const last = new Date(cursor.getFullYear(), cursor.getMonth() + 1, 0)
  return { start: dateKey(first), end: dateKey(last) }
}

/**
 * 月网格：周一为列首，向前补到周一、向后补齐整周，每格 `{date, inMonth, day}`。
 * 返回长度恒为 7 的倍数（5 或 6 行）。
 */
export function buildMonthGrid(cursor) {
  const first = new Date(cursor.getFullYear(), cursor.getMonth(), 1)
  const leading = (first.getDay() + 6) % 7 // 周一 = 0
  const start = new Date(first)
  start.setDate(start.getDate() - leading)

  const cells = []
  const cursorDate = new Date(start)
  do {
    cells.push({
      date: dateKey(cursorDate),
      inMonth: cursorDate.getMonth() === cursor.getMonth(),
      day: cursorDate.getDate()
    })
    cursorDate.setDate(cursorDate.getDate() + 1)
  } while (cursorDate.getMonth() === cursor.getMonth() || cells.length % 7 !== 0)
  return cells
}

/** 事件按 `event_at` 的日期分组；缺时间字段的条目跳过（不炸，也不落格）。 */
export function groupByDay(items) {
  const map = {}
  for (const item of items || []) {
    const key = String(item?.event_at || '').slice(0, 10)
    if (!/^\d{4}-\d{2}-\d{2}$/.test(key)) continue
    ;(map[key] ||= []).push(item)
  }
  return map
}
