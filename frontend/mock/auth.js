/**
 * /auth/* 7 个 handler（接口文档 §3.2 / SRS §3.13）。
 * 返回 [body, httpStatus]，由 index.js 统一写出。
 * 注：HTTP 状态码为合理推断（如锁定用 423），前端只依赖响应体 code，接口文档亦未规定状态码。
 */
import { ok, fail, readBody, parseMultipart, signToken, verifyToken, randomUUID } from './utils.js'
import { db, createUser, findByUsername, findById, toUserDto } from './db.js'

export const USERNAME_RE = /^[A-Za-z0-9_]{3,20}$/
const LOCK_MS = 5 * 60 * 1000

export const bearer = (req) => (/^Bearer\s+(.+)$/.exec(req.headers.authorization || '') || [])[1]

const jsonBody = async (req) => JSON.parse((await readBody(req)).toString() || '{}')

export async function register(req) {
  const { username, password, nickname, email } = await jsonBody(req)
  if (!USERNAME_RE.test(username || '')) return [fail(10001, '用户名需为 3~20 位字母、数字或下划线'), 400]
  if (!password || password.length < 6) return [fail(80006, '密码不能少于 6 位'), 400]
  if (findByUsername(username)) return [fail(80003, '该用户名已被注册'), 409]

  const user = createUser({ username, password, nickname, email })
  user.last_login_at = Date.now()
  // 注册成功即自动登录，Token 有效期 1 天（注册流程不含免登录选项）
  return [ok({ token: signToken(user), expires_at: null, user: toUserDto(user) }), 200]
}

export async function login(req) {
  const { username, password, remember_me } = await jsonBody(req)
  const user = findByUsername(username)
  // 用户名不存在与密码错误同款响应（80004），防用户名枚举
  if (!user) return [fail(80004, '用户名或密码错误'), 401]

  if (user.locked_until && user.locked_until > Date.now()) {
    const mins = Math.ceil((user.locked_until - Date.now()) / 60000)
    return [fail(80005, `账号已锁定，请 ${mins} 分钟后重试`), 423]
  }
  if (user.password !== password) {
    user.login_fail_count += 1
    if (user.login_fail_count >= 5) user.locked_until = Date.now() + LOCK_MS
    return [fail(80004, '用户名或密码错误'), 401]
  }

  user.login_fail_count = 0
  user.locked_until = null
  user.last_login_at = Date.now()
  return [ok({ token: signToken(user, !!remember_me), expires_at: null, user: toUserDto(user) }), 200]
}

export async function me(req) {
  const { user, error } = verifyToken(bearer(req), findById)
  return error ? [error, 401] : [ok(toUserDto(user)), 200]
}

export async function updateAccount(req) {
  const { user, error } = verifyToken(bearer(req), findById)
  if (error) return [error, 401]
  const { nickname, email } = await jsonBody(req)
  if (email && db.users.some((u) => u.id !== user.id && u.email === email)) {
    return [fail(10003, '该邮箱已被使用'), 409]
  }
  if (nickname !== undefined) user.nickname = nickname
  if (email !== undefined) user.email = email
  user.updated_at = Date.now()
  return [ok(toUserDto(user)), 200]
}

export async function changePassword(req) {
  const { user, error } = verifyToken(bearer(req), findById)
  if (error) return [error, 401]
  const { old_password, new_password } = await jsonBody(req)
  if (user.password !== old_password) return [fail(80007, '原密码错误'), 400]
  if (!new_password || new_password.length < 6) return [fail(80006, '密码不能少于 6 位'), 400]

  user.password = new_password
  user.password_changed_at = Date.now() // 早于此刻签发的 Token 全部作废（verifyToken 比对 iat）
  return [ok(null), 200]
}

export async function uploadAvatar(req) {
  const { user, error } = verifyToken(bearer(req), findById)
  if (error) return [error, 401]
  const file = parseMultipart(await readBody(req), req.headers['content-type'])
  if (!file) return [fail(10001, '请选择图片文件'), 400]
  if (file.bytes.length > 2 * 1024 * 1024) return [fail(10001, '头像不能超过 2MB'), 400]

  if (user.avatar) db.avatars.delete(user.avatar.split('/').pop()) // 换头像清理旧文件
  const name = `${user.id}_${randomUUID().slice(0, 8)}.png`
  db.avatars.set(name, file.bytes)
  user.avatar = `uploads/avatars/${name}`
  return [ok({ avatar: user.avatar }), 200]
}

export async function resetAvatar(req) {
  const { user, error } = verifyToken(bearer(req), findById)
  if (error) return [error, 401]
  if (user.avatar) db.avatars.delete(user.avatar.split('/').pop())
  user.avatar = null
  return [ok({ avatar: null }), 200]
}

export const AUTH_ROUTES = [
  ['POST', '/auth/register', register],
  ['POST', '/auth/login', login],
  ['GET', '/auth/me', me],
  ['PUT', '/auth/profile', updateAccount],
  ['PUT', '/auth/password', changePassword],
  ['POST', '/auth/avatar', uploadAvatar],
  ['DELETE', '/auth/avatar', resetAvatar]
]
