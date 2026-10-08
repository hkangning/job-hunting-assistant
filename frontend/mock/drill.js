/**
 * 练习模式（drill）的 dev mock：内存态题目 / 练习记录 + 点评 SSE + 三个导入源样例。
 *
 * 仅在 `VITE_USE_MOCK=true` 时生效（`mock/index.js` 注册）。后端 drill 接口落地前，
 * 前端靠它走查界面；契约见接口文档 §3.15。**走查结束后真链路复跑**，别把这里的数据当真实行为。
 *
 * 与真实后端的差异（有意为之，只保界面走查需要的那部分语义）：
 * - 归属校验真实做（题目按 `user_id` 隔离，跨账号访问 → 404 + 10002）；
 * - 分数与表达力指标是**按练习遍次构造的假数据**（越练越高 / 越快，用于看对比与趋势），
 *   不是真算法产出；`quality` 为 `TOO_SHORT` / `TEXT_ONLY` 时按契约**不下发** `voice_metrics`；
 * - 三个导入源（错题本 / 面经 / 投递记录）返回固定样例，供建题弹窗的选择器可用。
 */
import { ok, fail, readBody, verifyToken } from './utils.js'
import { findById } from './db.js'
import { bearer } from './auth.js'

const jsonBody = async (req) => JSON.parse((await readBody(req)).toString() || '{}')
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

/** 账号维度的内存态：user_id → { topics, attempts, seq }。 */
const byUser = new Map()

function bucket(userId) {
  if (!byUser.has(userId)) byUser.set(userId, { topics: [], attempts: [], seq: 0 })
  return byUser.get(userId)
}

export function resetDrill() {
  byUser.clear()
}

/** 导入源样例：字段名对齐各自模块的真实 DTO（错题用 `content`、投递用 `company` / `position`）。 */
const IMPORT_SOURCES = {
  WRONG: [
    {
      id: 901,
      content: '什么是缓存穿透？怎么防？',
      answer: '布隆过滤器 + 空值缓存',
      direction: 'BACKEND',
      source_type: 'INTERVIEW'
    }
  ],
  EXPERIENCE: [{ id: 902, title: '字节跳动前端一面：项目深挖' }],
  JD: [{ id: 903, company: '腾讯', position: '前端工程师' }]
}

const now = () => new Date().toISOString()

function topicDto(topic, state) {
  const attempts = state.attempts.filter((a) => a.topic_id === topic.id)
  const scores = attempts.map((a) => a.score).filter((s) => s != null)
  return {
    id: topic.id,
    title: topic.title,
    question: topic.question,
    source: topic.source,
    ref_id: topic.ref_id ?? null,
    archived: topic.archived ? 1 : 0,
    attempt_count: attempts.length,
    last_score: scores.length ? scores[scores.length - 1] : null,
    best_score: scores.length ? Math.max(...scores) : null,
    created_at: topic.created_at,
    updated_at: topic.updated_at
  }
}

function attemptSummary(attempt) {
  return {
    id: attempt.id,
    seq: attempt.seq,
    is_voice: attempt.is_voice,
    score: attempt.score,
    duration_ms: attempt.duration_ms,
    created_at: attempt.created_at
  }
}

function findTopic(state, topicId) {
  const topic = state.topics.find((t) => t.id === topicId)
  if (!topic) return { error: fail(10002, '题目不存在或不属于当前账号') }
  return { topic }
}

/** 假的表达力指标：越练越快、填充词越少（只为让对比与趋势有形状）。 */
function fakeMetrics({ isVoice, durationMs, segments, attemptCount }) {
  if (!isVoice || !segments?.length) return null
  const totalMs = durationMs || 60000
  if (totalMs < 10000) return null // 不足 10 秒：契约不下发（quality=TOO_SHORT）
  const ratio = Math.max(0.4, 1 - attemptCount * 0.15)
  const filler = Math.max(1, Math.round(12 * ratio))
  const pauses = Math.max(1, Math.round(3 * ratio))
  return {
    version: 1,
    quality: 'OK',
    total_ms: totalMs,
    speech_ms: Math.round(totalMs * 0.82),
    silence_ms: Math.round(totalMs * 0.18),
    char_count: segments.reduce((n, s) => n + (s.text?.length || 0), 0),
    speech_rate: Math.round(210 + attemptCount * 12),
    speech_ratio: 0.71 + Math.min(0.2, attemptCount * 0.06),
    filler_count: filler,
    filler_rate: 0.03,
    filler_detail: { 然后: Math.max(1, filler - 2), 就是: Math.min(2, filler) },
    pauses: Array.from({ length: pauses }, (_, i) => ({
      after_seq: i + 1,
      duration_ms: 1800 + i * 400,
      context: '缓存雪崩',
      level: i >= 2 ? 'HIGH' : 'LOW'
    })),
    longest_pause_ms: 1800 + (pauses - 1) * 400,
    fluency_trend: { direction: attemptCount >= 2 ? 'IMPROVING' : 'STABLE', segments: [] }
  }
}

export async function listDrills(req, query) {
  const { user, error } = verifyToken(bearer(req), findById)
  if (error) return [error, 401]
  const state = bucket(user.id)
  const archived = query.get('archived')
  const source = query.get('source')
  const page = Number(query.get('page') || 1)
  const pageSize = Number(query.get('page_size') || 10)
  let rows = state.topics.filter((t) => (archived == null ? !t.archived : !!t.archived === (archived === 'true')))
  if (source) rows = rows.filter((t) => t.source === source)
  rows = rows.sort((a, b) => b.id - a.id)
  const items = rows.slice((page - 1) * pageSize, page * pageSize).map((t) => topicDto(t, state))
  return [ok({ items, total: rows.length, page, page_size: pageSize }), 200]
}

export async function createDrill(req) {
  const { user, error } = verifyToken(bearer(req), findById)
  if (error) return [error, 401]
  const body = await jsonBody(req)
  const title = String(body.title || '').trim()
  if (!title) return [fail(10001, '题目标题不能为空'), 400]
  if (title.length > 50) return [fail(10001, '题目标题不能超过 50 字'), 400]
  const source = body.source || 'CUSTOM'
  // ref_id 口径与后端 §3.15 实现口径 1 同步（IS-68）：CUSTOM / INTRO 免 ref_id，RESUME 暂缓
  if (source === 'RESUME') return [fail(10001, '暂不支持从画像经历导入，请改用手动写题'), 400]
  if (!['CUSTOM', 'INTRO'].includes(source) && body.ref_id == null) {
    return [fail(10001, '该来源必须提供 ref_id'), 400]
  }
  const state = bucket(user.id)
  const topic = {
    id: ++state.seq,
    title,
    question: body.question || `（AI 待生成）${title}`,
    source,
    ref_id: body.ref_id ?? null,
    archived: 0,
    created_at: now(),
    updated_at: now()
  }
  state.topics.push(topic)
  return [ok(topicDto(topic, state)), 200]
}

export async function getDrill(req, query, topicId) {
  const { user, error } = verifyToken(bearer(req), findById)
  if (error) return [error, 401]
  const state = bucket(user.id)
  const found = findTopic(state, topicId)
  if (found.error) return [found.error, 404]
  const attempts = state.attempts
    .filter((a) => a.topic_id === topicId)
    .sort((a, b) => a.seq - b.seq)
    .map(attemptSummary)
  return [ok({ ...topicDto(found.topic, state), attempts }), 200]
}

export async function updateDrill(req, query, topicId) {
  const { user, error } = verifyToken(bearer(req), findById)
  if (error) return [error, 401]
  const state = bucket(user.id)
  const found = findTopic(state, topicId)
  if (found.error) return [found.error, 404]
  const body = await jsonBody(req)
  const topic = found.topic
  if (body.title != null) topic.title = String(body.title).trim()
  if (body.question != null) topic.question = String(body.question)
  if (body.archived != null) topic.archived = body.archived ? 1 : 0
  topic.updated_at = now()
  return [ok(topicDto(topic, state)), 200]
}

export async function getAttempt(req, query, topicId, attemptId) {
  const { user, error } = verifyToken(bearer(req), findById)
  if (error) return [error, 401]
  const state = bucket(user.id)
  const found = findTopic(state, topicId)
  if (found.error) return [found.error, 404]
  const attempt = state.attempts.find((a) => a.id === attemptId && a.topic_id === topicId)
  if (!attempt) return [fail(10002, '练习记录不存在'), 404]
  return [ok(attempt), 200]
}

export async function getProgress(req, query, topicId) {
  const { user, error } = verifyToken(bearer(req), findById)
  if (error) return [error, 401]
  const state = bucket(user.id)
  const found = findTopic(state, topicId)
  if (found.error) return [found.error, 404]
  const all = state.attempts.filter((a) => a.topic_id === topicId).sort((a, b) => a.seq - b.seq)
  // 口径版本过滤：与**最新一条有指标的记录**同版本才参与对比（版本不一致宁可少展示）
  const latestVersion = [...all].reverse().find((a) => a.voice_metrics)?.voice_metrics?.version
  const comparable = all.filter(
    (a) => !a.voice_metrics || latestVersion == null || a.voice_metrics.version === latestVersion
  )
  const items = comparable.map((a) => ({
    seq: a.seq,
    score: a.score,
    duration_ms: a.duration_ms,
    speech_rate: a.voice_metrics?.speech_rate ?? null,
    filler_count: a.voice_metrics?.filler_count ?? null,
    pause_count: a.voice_metrics?.pauses?.length ?? null,
    speech_ratio: a.voice_metrics?.speech_ratio ?? null
  }))
  let deltas = null
  if (items.length >= 2) {
    const [from, to] = items.slice(-2)
    deltas = {
      score: diff(from.score, to.score),
      duration_ms: diff(from.duration_ms, to.duration_ms),
      filler_count: diff(from.filler_count, to.filler_count),
      pause_count: diff(from.pause_count, to.pause_count)
    }
  }
  return [ok({ topic_id: topicId, attempt_count: all.length, items, deltas }), 200]
}

const diff = (from, to) => (from == null || to == null ? null : to - from)

/** 三个导入源的选择器数据（真实链路下由各自接口提供，这里给固定样例）。 */
export async function listImportSource(req, query, kind) {
  const { error } = verifyToken(bearer(req), findById)
  if (error) return [error, 401]
  const rows = IMPORT_SOURCES[kind] || []
  return [ok({ items: rows, total: rows.length, page: 1, page_size: 20 }), 200]
}

/**
 * 点评 SSE：`start` → `delta`（score → review）→ `done`。
 * 直接写 `res`，返回 `null` 表示「已自行响应」（mock/index.js 据此不再包 JSON）。
 */
export async function drillReviewStream(req, res) {
  const { user, error } = verifyToken(bearer(req), findById)
  if (error) {
    res.statusCode = 401
    res.setHeader('Content-Type', 'application/json; charset=utf-8')
    res.end(JSON.stringify(error))
    return null
  }
  const body = await jsonBody(req)
  const state = bucket(user.id)
  const found = findTopic(state, body.topic_id)
  if (found.error) {
    res.statusCode = 404
    res.setHeader('Content-Type', 'application/json; charset=utf-8')
    res.end(JSON.stringify(found.error))
    return null
  }
  if (found.topic.archived) {
    res.statusCode = 409
    res.setHeader('Content-Type', 'application/json; charset=utf-8')
    res.end(JSON.stringify(fail(40003, '该题目已归档，恢复后可继续练习')))
    return null
  }

  const attemptCount = state.attempts.filter((a) => a.topic_id === body.topic_id).length
  const score = Math.min(9, 5 + attemptCount)
  const metrics = fakeMetrics({
    isVoice: !!body.is_voice,
    durationMs: body.duration_ms,
    segments: body.segments,
    attemptCount
  })
  const attempt = {
    id: ++state.seq,
    topic_id: found.topic.id,
    seq: attemptCount + 1,
    answer: body.answer || '',
    is_voice: body.is_voice ? 1 : 0,
    voice_metrics: metrics,
    score,
    review: '',
    duration_ms: body.duration_ms ?? null,
    created_at: now()
  }
  state.attempts.push(attempt)

  res.statusCode = 200
  res.setHeader('Content-Type', 'text/event-stream; charset=utf-8')
  res.setHeader('Cache-Control', 'no-cache')
  res.setHeader('Connection', 'keep-alive')
  const send = (event, data) => res.write(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`)

  send('start', { message: '正在点评…' })
  await sleep(400)
  const scoreText = `评分 ${score}/10`
  for (let i = 0; i < scoreText.length; i += 3) {
    send('delta', { text: scoreText.slice(i, i + 3), section: 'score' })
    await sleep(120)
  }
  const review =
    '## 点评\n' +
    `亮点：条理清晰，先给结论再展开（第 ${attempt.seq} 遍）。\n` +
    '不足：缺少具体示例，建议补充一个项目里的真实场景与量化结果。\n' +
    '参考要点：可以按「现象—排查—定位—修复」四步来组织表达。'
  for (let i = 0; i < review.length; i += 6) {
    send('delta', { text: review.slice(i, i + 6), section: 'review' })
    await sleep(80)
  }
  attempt.review = review
  send('done', {
    record_id: attempt.id,
    seq: attempt.seq,
    ...(metrics ? { extra: { voice_metrics: metrics } } : { extra: {} })
  })
  res.end()
  return null
}

/**
 * 假的语音转写：mock 不做识别，固定回一句（带点随机性，方便看逐句回填）。
 * 只为让走查能跑通「录音 → 断句 → 回填 → 带 segments 提交」这条链路，真链路走 FunASR（§3.13）。
 */
export async function transcribeMock(req) {
  const { error } = verifyToken(bearer(req), findById)
  if (error) return [error, 401]
  await readBody(req)
  const texts = ['这是练习模式的第一句话。', '第二句话用来验证连续说话的回填效果。', '最后再说一句收尾的话。']
  const text = texts[Math.floor(Math.random() * texts.length)]
  return [ok({ text, duration_ms: 1500 }), 200]
}

/**
 * 路由匹配：`route` 是去掉 `/api/v1` 前缀后的路径。
 * 返回 `[handler, params]` 或 null（未命中则落到 mock/index.js 的兜底）。
 */
export function matchDrill(method, route) {
  if (method === 'POST' && route === '/asr/transcribe') return { handler: transcribeMock }
  const importSource = /^\/(wrong-questions|experiences|applications)$/.exec(route)
  if (method === 'GET' && importSource) {
    const kind = { 'wrong-questions': 'WRONG', experiences: 'EXPERIENCE', applications: 'JD' }[importSource[1]]
    return { handler: (req, query) => listImportSource(req, query, kind) }
  }
  if (route === '/drills') {
    if (method === 'GET') return { handler: listDrills }
    if (method === 'POST') return { handler: createDrill }
    return null
  }
  if (route === '/stream/drill-review' && method === 'POST') {
    return { handler: drillReviewStream, raw: true }
  }
  let m = /^\/drills\/(\d+)$/.exec(route)
  if (m) {
    const id = Number(m[1])
    if (method === 'GET') return { handler: (req, query) => getDrill(req, query, id) }
    if (method === 'PUT') return { handler: (req, query) => updateDrill(req, query, id) }
    return null
  }
  m = /^\/drills\/(\d+)\/attempts\/(\d+)$/.exec(route)
  if (m && method === 'GET') {
    const topicId = Number(m[1])
    const attemptId = Number(m[2])
    return { handler: (req, query) => getAttempt(req, query, topicId, attemptId) }
  }
  m = /^\/drills\/(\d+)\/progress$/.exec(route)
  if (m && method === 'GET') {
    const topicId = Number(m[1])
    return { handler: (req, query) => getProgress(req, query, topicId) }
  }
  return null
}
