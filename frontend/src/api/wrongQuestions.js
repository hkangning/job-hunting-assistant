/**
 * 错题本接口封装（接口文档 v1.29 §3.9）。
 *
 * 4 个端点：列表 / 添加 / 删除 / 复习判定。响应由 `request.js` 拦截器解包，调用方直接拿 `data`。
 */
import request from './request'

/**
 * 错题列表。
 * params: { status?: 'PENDING' | 'MASTERED', page?, page_size? }
 * 排序由后端给（未掌握优先 → 到期先后 → id 升序），前端不再排。
 */
export function listWrongQuestions(params) {
  return request.get('/wrong-questions', { params })
}

/**
 * 添加错题，两种形态：
 * - 题库题：`{ question_id }`（页面上不做，留给其他场景的入口）
 * - 知识点：`{ content, answer, direction, source_type: 'INTERVIEW' | 'DRILL' }`
 * 重复入本 → 409 + 10003；题不存在 → 404 + 10002。
 */
export function addWrongQuestion(payload) {
  return request.post('/wrong-questions', payload)
}

/** 删除错题条目。 */
export function deleteWrongQuestion(id) {
  return request.delete(`/wrong-questions/${id}`)
}

/**
 * 复习判定。
 * `answer` 传**选项标识**（选择题，如 `"B"`）或作答文本；
 * 返回 `{correct, explain, review_stage, next_review_at, mastered}`。
 * 已掌握后再复习 → 404 + 30002；空作答 → 400 + 10001；未配 AI 供应商 → 400 + 10012。
 */
export function reviewWrongQuestion(id, answer) {
  return request.post(`/wrong-questions/${id}/review`, { answer })
}
