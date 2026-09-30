/**
 * 面经整理接口封装（接口文档 v1.33 §3.10）。
 *
 * 4 个 REST + 1 个 SSE（结构化提取）+ 1 个条目检索；响应由 `request.js` 拦截器解包，
 * 调用方直接拿 `data`。保存与提取分离是契约行为：`POST /experiences` 只存原文，
 * 提取走 `POST /stream/experience-extract`（done 时条目已落库）。
 */
import request from './request'
import { streamSSE } from '../utils/sse'

/** 保存面经原文。payload: { company?, position?, source?, original_text }（原文 ≤10000 字）。 */
export function createExperience(payload) {
  return request.post('/experiences', payload)
}

/** 面经列表。params: { page?, page_size? }；items 含 `item_count`（列表展示用）。 */
export function listExperiences(params) {
  return request.get('/experiences', { params })
}

/** 面经详情：全文 + `items`（结构化条目，含 source_type）。 */
export function getExperience(id) {
  return request.get(`/experiences/${id}`)
}

/** 删除面经（级联删条目）。 */
export function deleteExperience(id) {
  return request.delete(`/experiences/${id}`)
}

/** 结构化提取（SSE）。payload: { experience_id }；delta 为进度状态文字，done 时条目已落库。 */
export function experienceExtractStream(payload, handlers, options) {
  return streamSSE('/stream/experience-extract', payload, handlers, options)
}

/** 条目关键词检索。params: { keyword, page?, page_size? }；items 跨面经（company 联表）。 */
export function searchExperienceItems(params) {
  return request.get('/experience-items/search', { params })
}
