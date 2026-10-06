/**
 * 分句时间轴（segments）组装（接口文档 §3.13「分句时间轴约定」）。
 *
 * 提交作答时随作答上传 `[{seq, start_ms, end_ms, text}]`——句间停顿只有前端知道，
 * 这是后端表达力指标的**唯一数据来源**；`text` 取**原始转写**（用户编辑只影响
 * 内容点评，不重算指标）。空文本（后端静音短路返回 `text=""`）不产生条目。
 */

/** 追加一句。trim 后为空 → 返回 false 不追加；否则按 seq 递增写入。 */
export function addSegment(list, { text, startMs, endMs }) {
  const t = String(text ?? '').trim()
  if (!t) return false
  list.push({ seq: list.length + 1, start_ms: startMs, end_ms: endMs, text: t })
  return true
}

/** 转提交用 payload：空列表 → null（调用方据此不携带该字段），否则原样返回。 */
export function toSegmentsPayload(list) {
  return list.length ? list : null
}
