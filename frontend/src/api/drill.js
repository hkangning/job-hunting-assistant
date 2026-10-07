/**
 * 练习模式接口封装（接口文档 v1.50 §3.15）。
 *
 * **命名口径**：练习模式一律 `drill`（后端路径前缀 `/drills`）；项目内 `practice` 专指八股陪练
 * （FR-009），两者不可混用。响应由 `request.js` 拦截器解包，调用方直接拿 `data`。
 *
 * 6 个 REST + 1 个 SSE：列表 / 新建 / 详情 / 编辑归档、单次详情、跨次对比 + 点评流。
 */
import request from './request'
import { streamSSE } from '../utils/sse'

/**
 * 我的题目列表。
 * params: `{ archived?, source?, page?, page_size? }`——**默认只返回未归档**；
 * items 含聚合字段 `attempt_count` / `last_score` / `best_score`，供列表页展示进度概况。
 */
export function listDrills(params) {
  return request.get('/drills', { params })
}

/**
 * 新建题目。
 * payload: `{ title, question?, source?, ref_id? }`——`source` 非 `CUSTOM` 时 `ref_id` 必填
 * （来源实体 id，后端校验归属，不属于当前账号 → 10002）；**只记来源不复制内容**，
 * `question` 不传时由 AI 按 `title` + 来源生成。
 */
export function createDrill(payload) {
  return request.post('/drills', payload)
}

/** 题目详情：topic DTO + `attempts` 摘要数组（`{id, seq, is_voice, score, duration_ms, created_at}`，不含点评全文与指标）。 */
export function getDrill(topicId) {
  return request.get(`/drills/${topicId}`)
}

/**
 * 编辑 / 归档：**部分更新**语义（只更新请求体里出现的字段）——`title` / `question` / `archived`。
 * 归档后默认列表不展示、不可再作答（提交 → 409 + 40003），历史记录仍可查看。
 */
export function updateDrill(topicId, payload) {
  return request.put(`/drills/${topicId}`, payload)
}

/** 单次练习完整内容：`{id, topic_id, seq, answer, is_voice, voice_metrics, score, review, duration_ms, created_at}`。 */
export function getDrillAttempt(topicId, attemptId) {
  return request.get(`/drills/${topicId}/attempts/${attemptId}`)
}

/**
 * 跨次进步对比：`items` 按 `seq` 升序（画趋势线用），`deltas` 为**最近一次 vs 上一次**
 * ——练满 2 遍才有，首遍为 `null`；口径版本不一致的记录不参与对比。
 */
export function getDrillProgress(topicId) {
  return request.get(`/drills/${topicId}/progress`)
}

/**
 * 提交一次练习（SSE）。
 * payload: `{ topic_id, answer, is_voice?, segments?, duration_ms? }`——**语音作答必传 `segments`**
 * （分句时间轴，缺失则本次只出内容点评）。
 * 事件流：`start` → `delta`（section 依次 `score` / `review`）→ `done`（`record_id`、`seq`，
 * 语音作答且已算出指标时 `extra.voice_metrics`）。归档题 → 40003。
 */
export function drillReviewStream(payload, handlers, options) {
  return streamSSE('/stream/drill-review', payload, handlers, options)
}
