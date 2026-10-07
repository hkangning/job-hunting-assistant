/**
 * 练习模式一次作答的流式归集（FR-020 / 接口文档 §3.15）。
 *
 * `POST /stream/drill-review` 的事件流：`start` → `delta`（section 依次 `score` / `review`）
 * → `done`（`record_id`、`seq`，语音作答时 `extra.voice_metrics`）。
 *
 * 与面试 / 陪练的差异：**分数是独立 section**（`score`），不在点评正文里；但后端的文本形态
 * 未被契约钉死（可能下发 `8/10`、`8 分` 或 `评分 8/10`），故这里用与两页同一套
 * `parseRoundScore` 解析，解析不出就留空——宁可少显示一个分数，也不显示错的。
 *
 * 纯函数（无 IO），单测 `tests/drillStream.test.js`。
 */
import { parseRoundScore } from './practiceStream.js'

/** 一次作答的流式状态（视图模型）。 */
export function createAttempt() {
  return {
    score: null,
    scoreText: '',
    review: '',
    recordId: null,
    seq: null,
    voiceMetrics: null
  }
}

/** 吃一个 delta；`score` 段只影响分数，其余（含无 section 的降级文本）并入点评正文。 */
export function applyDelta(attempt, delta) {
  if (!attempt) return attempt
  const text = delta?.text
  if (!text) return attempt
  if (delta?.section === 'score') {
    attempt.scoreText += text
    const { score } = parseRoundScore(attempt.scoreText)
    if (score != null) attempt.score = score
  } else {
    attempt.review += text
  }
  return attempt
}

/** `done`：回填记录 id / 遍次 / 表达力指标；分数段没给出来时从点评正文兜底解析一次。 */
export function applyDone(attempt, done) {
  if (!attempt) return attempt
  if (done?.record_id != null) attempt.recordId = done.record_id
  if (done?.seq != null) attempt.seq = done.seq
  attempt.voiceMetrics = done?.extra?.voice_metrics ?? null
  if (attempt.score == null) {
    const { score } = parseRoundScore(attempt.review)
    if (score != null) attempt.score = score
  }
  return attempt
}

/** 点评正文：剥标题行与可能存在的评分行（分数已由徽章承担，与面试 / 陪练同口径）。 */
export function reviewBody(attempt) {
  return parseRoundScore(attempt?.review || '').note
}
