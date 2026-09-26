/**
 * 日期时间显示格式化。
 *
 * 后端返回的时间字段是 **ISO 格式**（`YYYY-MM-DDTHH:mm:ss`，Pydantic 的默认序列化；
 * 换 MySQL 前 SQLite 下曾是空格分隔，故历史代码对两种形态都要能处理）。
 * 界面一律显示为 `MM-DD HH:mm`——位置切片对两种分隔符都成立（`T`/空格都在第 10 位）。
 */

/** `2026-09-27T14:00:00` → `09-27 14:00`；空值返回空串，长度不足的原样返回。 */
export function shortDateTime(value) {
  const text = String(value || '')
  return text.length >= 16 ? `${text.slice(5, 10)} ${text.slice(11, 16)}` : text
}

/** 取日期部分：`2026-09-27T14:00:00` → `2026-09-27`（两种分隔符同样成立）。 */
export function datePart(value) {
  return String(value || '').slice(0, 10)
}
