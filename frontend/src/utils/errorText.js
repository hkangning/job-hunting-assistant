/**
 * 错误文案的统一口径（步骤 27 交互收口）。
 *
 * 两件事：
 * 1. `normalizeError`——后端 message 的规范化。后端个别文案是历史口径（如 10012 的
 *    「设置页」出自 LLM 配置尚在设置页的时期，前端页面名现为「AI 配置」），以及 10001
 *    校验失败会拼出 pydantic 英文串（`字段: Input should be…`，见后端 exceptions.py）——
 *    这两类不直接上屏，映射为面向用户的说法；其余文案后端本身已友好，原样透传。
 * 2. `fallbackText`——前端兜底文案表。按场景取，避免同一类失败在 14 个页面出现 14 种写法。
 */

/** 场景兜底文案。fetch = 拉取失败；submit = 提交 / 保存 / 删除等写操作失败。 */
const FALLBACKS = {
  network: '网络连接失败，请检查网络后重试',
  server: '服务暂时不可用，请稍后重试',
  fetch: '加载失败，请重试',
  submit: '操作失败，请重试'
}

/** 通用兜底（未知场景 / 空文案）。 */
export const GENERIC_ERROR = '操作失败，请重试'

/**
 * 按场景取兜底文案；未知场景回落通用兜底。
 * @param {'network'|'server'|'fetch'|'submit'} scene
 */
export function fallbackText(scene) {
  return FALLBACKS[scene] || GENERIC_ERROR
}

/**
 * 后端 message 规范化。空文案回落通用兜底；不认识的形态原样返回（宁可透传后端文案，
 * 不做过度改写）。
 * @param {string} message 后端返回的 message
 * @param {number} [code] 业务错误码
 */
export function normalizeError(message, code) {
  const text = typeof message === 'string' ? message.trim() : ''
  if (!text) return GENERIC_ERROR

  // 10012：历史文案含「设置页」，统一指向现页面名「AI 配置」
  if (code === 10012 && text.includes('设置页')) {
    return '未配置 AI 密钥，请前往「AI 配置」页完成配置'
  }

  // 10001：pydantic 英文串（形如「字段: String should …」，字段名可为中文）
  if (code === 10001 && /^[^:]+: [A-Za-z]/.test(text)) {
    return '输入内容有误，请检查后重试'
  }

  return text
}
