/**
 * mock 内存数据库：字段口径对齐《数据库设计文档》
 * §3.16 user / §3.15 user_profile / §3.14 config。
 * 进程内存储，重启 dev server 即清空（mock 仅服务开发期界面走查）。
 */
export const db = { users: [], profiles: new Map(), configs: new Map(), avatars: new Map(), seq: 0 }

export const nextId = () => ++db.seq
export const findById = (id) => db.users.find((u) => u.id === id)
export const findByUsername = (name) =>
  db.users.find((u) => u.username.toLowerCase() === String(name || '').toLowerCase())

const fmt = (ms) => (ms ? new Date(ms).toISOString().slice(0, 19).replace('T', ' ') : null)

/** 新建账号：预置画像与账号级默认配置（数据库设计 §4「注册时自动创建」）。 */
export function createUser({ username, password, nickname, email }) {
  const now = Date.now()
  const user = {
    id: nextId(), username, password,
    nickname: nickname || username, email: email || null, avatar: null,
    role: db.users.length === 0 ? 'ADMIN' : 'USER', plan: 'FREE',
    login_fail_count: 0, locked_until: null, last_login_at: null,
    password_changed_at: null, created_at: now, updated_at: now
  }
  db.users.push(user)
  db.profiles.set(user.id, {
    name: '', school: '', major: '', degree: '', gpa: '', english_level: '', resume_text: '',
    target_position: '', target_city: '', skills: '', weaknesses: '', note: ''
  })
  db.configs.set(user.id, {
    tts_enabled: 'false', voice_enabled: 'false', default_question_count: '8',
    asr_provider: 'funasr', tts_voice: 'zh-CN-XiaoxiaoNeural', guide_done: 'false'
  })
  return user
}

/** 对外用户 DTO：不含 password，字段同接口文档 §3.2 GET /auth/me。 */
export const toUserDto = (user) => ({
  id: user.id, username: user.username, nickname: user.nickname, email: user.email,
  avatar: user.avatar, role: user.role, plan: user.plan,
  created_at: fmt(user.created_at), last_login_at: fmt(user.last_login_at),
  llm_configured: false
})
