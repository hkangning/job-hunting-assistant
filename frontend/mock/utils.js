/** mock 层公共工具：统一响应体、请求体解析、mock token 签发与校验。 */
import { randomUUID } from 'node:crypto'

export const ok = (data = null) => ({ code: 0, message: 'ok', data })
export const fail = (code, message, data = null) => ({ code, message, data })

const TTL_DAY = 24 * 60 * 60 * 1000

/** 读请求体原始字节（JSON 与 multipart 共用入口）。 */
export function readBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = []
    req.on('data', (c) => chunks.push(c))
    req.on('end', () => resolve(Buffer.concat(chunks)))
    req.on('error', reject)
  })
}

/**
 * 极简 multipart 解析：只取第一个带 filename 的文件字段。
 * 以 latin1 切分——它是字节到字符的一一映射，二进制内容不会被破坏。
 */
export function parseMultipart(buf, contentType) {
  const m = /boundary=(.+)$/.exec(contentType || '')
  if (!m) return null
  const boundary = '--' + m[1].replace(/^"|"$/g, '')
  const parts = buf.toString('latin1').split(boundary).slice(1, -1)
  for (const part of parts) {
    const idx = part.indexOf('\r\n\r\n')
    if (idx === -1) continue
    const head = part.slice(0, idx)
    if (!/filename=/.test(head)) continue
    const name = /filename="([^"]*)"/.exec(head)?.[1] || 'upload.png'
    const bytes = Buffer.from(part.slice(idx + 4, part.lastIndexOf('\r\n')), 'latin1')
    return { name, bytes }
  }
  return null
}

/** 签发 mock token：payload 结构对齐系统设计 §3.5（sub/username/iat/exp）。 */
export const signToken = (user, rememberMe = false) => {
  const now = Date.now()
  const payload = { sub: user.id, username: user.username, iat: now, exp: now + (rememberMe ? 30 : 1) * TTL_DAY }
  return 'mock.' + Buffer.from(JSON.stringify(payload)).toString('base64url')
}

/**
 * 校验 token。返回 { user } 或 { error }（80001 无效 / 80002 过期或改密作废）。
 * 规则对齐系统设计 §3.5 的校验链：验签 → 查用户 → 验 exp → 比对 iat 与 password_changed_at。
 */
export function verifyToken(token, findUser) {
  if (!token || !token.startsWith('mock.')) return { error: fail(80001, '未登录或登录状态已失效') }
  let payload
  try {
    payload = JSON.parse(Buffer.from(token.slice(5), 'base64url').toString('utf8'))
  } catch {
    return { error: fail(80001, '未登录或登录状态已失效') }
  }
  const user = findUser(payload.sub)
  if (!user) return { error: fail(80001, '未登录或登录状态已失效') }
  if (Date.now() > payload.exp) return { error: fail(80002, '登录状态已过期，请重新登录') }
  if (user.password_changed_at && payload.iat < user.password_changed_at) {
    return { error: fail(80002, '密码已修改，请重新登录') }
  }
  return { user }
}

export { randomUUID }
