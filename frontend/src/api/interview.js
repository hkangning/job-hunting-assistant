/**
 * 模拟面试接口封装（接口文档 v1.33 §3.7）。
 *
 * 3 个 REST + 1 个 SSE 出口；响应由 `request.js` 拦截器解包，调用方直接拿 `data`。
 * 总结与回看（`/stream/interview-summary`）属步骤 16，本文件不含。
 */
import request from './request'
import { streamSSE } from '../utils/sse'

/** 新建会话。payload: { application_id? | company+position, direction?, question_count? } */
export function createInterviewSession(payload) {
  return request.post('/interview-sessions', payload)
}

/** 会话列表。params: { status?, page?, page_size? }；items 含 `qa_count`（已落库条数，供进度显示）。 */
export function listInterviewSessions(params) {
  return request.get('/interview-sessions', { params })
}

/** 会话详情：session DTO + `qa_list`（按 seq 升序）。 */
export function getInterviewSession(id) {
  return request.get(`/interview-sessions/${id}`)
}

/** 作答 / 请首题 / 跳过（SSE）。payload: { session_id, answer?, skip? } */
export function interviewChatStream(payload, handlers, options) {
  return streamSSE('/stream/interview-chat', payload, handlers, options)
}
