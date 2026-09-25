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
  // 账号级偏好 + 系统级抓取配置（结构对齐接口文档 §3.13）
  return [ok({ ...db.configs.get(user.id), crawl_enabled: 'false', crawl_url: '' }), 200]
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

/** 概览：统计返回 0 值结构（个人中心数据概览卡片取用；步骤 9 扩充真实聚合）。 */
export async function overview(req) {
  const { error } = verifyToken(bearer(req), findById)
  if (error) return [error, 401]
  return [ok({
    stats: { application_count: 0, interview_count: 0, wrong_question_count: 0 },
    follow_ups: [], upcoming_events: [], wrong_question_reminders: [], campus_events: []
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
