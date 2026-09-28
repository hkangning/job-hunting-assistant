/**
 * 八股陪练接口封装（接口文档 v1.26 §3.8）。
 *
 * 8 个端点：元数据 / 抽题 / 会话（开·结算·历史·回看）/ 掌握度，逐轮点评走 SSE。
 * 响应由 `request.js` 拦截器解包，调用方直接拿 `data`。
 */
import request from './request'
import { streamSSE } from '../utils/sse'

/** 训练元数据：技术栈与下辖领域、岗位→栈映射、题型、五种模式、四层攻击面、限时档。 */
export function getPracticeMeta() {
  return request.get('/practice/meta')
}

/** 抽题（不含答案）。params: { stacks?, directions?, qtypes?, count?, strategy? } */
export function drawQuestions(params) {
  return request.post('/practice/questions', params)
}

/** 开一场训练（纯落库、零 LLM 调用）。payload: { question_id, mode, time_limit? } */
export function createSession(payload) {
  return request.post('/practice/sessions', payload)
}

/** 结算（纯计算、幂等：重复调用结果一致且不重复入本）。 */
export function finishSession(sessionId) {
  return request.post(`/practice/sessions/${sessionId}/finish`)
}

/** 训练历史列表。params: { mode?, page?, page_size? } */
export function listSessions(params) {
  return request.get('/practice/sessions', { params })
}

/** 单场回看：会话信息 + 逐轮记录（按 round_index 升序）。 */
export function getSession(sessionId) {
  return request.get(`/practice/sessions/${sessionId}`)
}

/** 领域掌握度列表（按技术栈分组）。params: { stack? } */
export function getMastery(params) {
  return request.get('/practice/mastery', { params })
}

/**
 * 每轮统一入口（SSE）：首次调用即初始作答，之后为追问 / 提示 / 复述 / 找错轮。
 * payload: { session_id, user_input?, action?, elapsed_ms?, timed_out? }
 */
export function practiceTurnStream(payload, handlers, options) {
  return streamSSE('/stream/practice-turn', payload, handlers, options)
}
