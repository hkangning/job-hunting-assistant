/**
 * 账号链路之外的接口：画像 / 设置 / 概览 / 业务空响应 / 头像静态文件。
 * 业务接口同样走鉴权校验——白名单只有 /health、/auth/register、/auth/login（接口文档 §1.1）。
 */
import { ok, fail, readBody, verifyToken } from './utils.js'
import { db, findById } from './db.js'
import { bearer } from './auth.js'

const jsonBody = async (req) => JSON.parse((await readBody(req)).toString() || '{}')

export async function getProfile(req) {
  const { user, error } = verifyToken(bearer(req), findById)
  if (error) return [error, 401]
  return [ok(db.profiles.get(user.id)), 200]
}

export async function putProfile(req) {
  const { user, error } = verifyToken(bearer(req), findById)
  if (error) return [error, 401]
  const body = await jsonBody(req)
  // 请求体不接受 user_id：归属只由登录态决定（系统设计 §3.6）
  delete body.user_id
  db.profiles.set(user.id, { ...db.profiles.get(user.id), ...body })
  return [ok(db.profiles.get(user.id)), 200]
}

export async function getSettings(req) {
  const { user, error } = verifyToken(bearer(req), findById)
  if (error) return [error, 401]
  // 账号级偏好 + 系统级抓取配置（结构对齐接口文档 §3.12）
  // mock 未实现讯飞凭据存储，asr_key_set 恒为未配置；crawl_url 已废弃（改由信息源清单承载）
  return [
    ok({
      ...db.configs.get(user.id),
      asr_key_set: false,
      crawl_enabled: 'false'
    }),
    200
  ]
}

export async function putSettings(req) {
  const { user, error } = verifyToken(bearer(req), findById)
  if (error) return [error, 401]
  const body = await jsonBody(req)
  const config = db.configs.get(user.id)
  for (const [key, value] of Object.entries(body)) {
    if (key in config) config[key] = String(value)
  }
  return [ok(config), 200]
}

/** 概览：样例数据供界面走查（步骤 9 前端先行，真后端就绪后走 VITE_USE_MOCK=false）。
 *  刻意造出的形态：明日那条**排在后面**、days 4 排在 6 前面——用来验证前端的置顶与降序真的在起作用，
 *  而不是照搬后端顺序；CLOSED 有值而 wrong_question_count 为 0，以便同时看到计数与空态。 */
export async function overview(req) {
  const { error } = verifyToken(bearer(req), findById)
  if (error) return [error, 401]

  const p = (n) => String(n).padStart(2, '0')
  const day = (offset) => {
    const d = new Date()
    d.setDate(d.getDate() + offset)
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
  }
  const at = (offset, hour) => `${day(offset)} ${p(hour)}:00:00`

  return [ok({
    application_stats: { APPLIED: 5, WRITTEN: 2, INTERVIEW: 3, OFFER: 1, CLOSED: 4 },
    upcoming_events: [
      { application_id: 2, company: '某某科技', position: '前端开发', event_at: at(3, 10), status: 'WRITTEN' },
      { application_id: 1, company: '浩鲸科技', position: 'Java 后端开发', event_at: at(1, 14), status: 'INTERVIEW' }
    ],
    follow_ups: [
      { application_id: 3, company: '云启信息', position: '后端开发', applied_at: at(-4, 10), days: 4 },
      { application_id: 4, company: '星环数据', position: '数据开发', applied_at: at(-6, 10), days: 6 }
    ],
    wrong_question_count: 0,
    campus_events: [],
    last_crawl_at: null,
    stats: { application_count: 15, wrong_question_count: 0, interview_count: 3 }
  }), 200]
}

/** 其余业务接口：鉴权通过则返回空数据结构，保证 mock 模式下各页面不报错。 */
export async function emptyData(req) {
  const { error } = verifyToken(bearer(req), findById)
  if (error) return [error, 401]
  return [ok({ total: 0, items: [] }), 200]
}

export const health = () => [ok({ status: 'ok' }), 200]

/** 头像静态文件：返回上传时的原始字节（二进制，不经统一响应体）。 */
export function staticAvatar(req) {
  const name = decodeURIComponent(req.url.split('?')[0].replace('/uploads/avatars/', ''))
  const bytes = db.avatars.get(name)
  return bytes ? [bytes, 200] : [null, 404]
}

export const fail404 = () => fail(10002, '资源不存在')
