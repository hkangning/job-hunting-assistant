/**
 * 投喂原文暂存：岗位列表契约不下发 raw_excerpt（NFR-016 / 接口文档 §3.16），
 * 而「分析匹配度」要预填 JD 原文——投喂确认入库时按岗位 id 存本机，取不到就提示用户粘贴。
 *
 * 纯逻辑 + 可注入 storage：单测注入内存实现；运行时缺省用 window.localStorage，
 * 隐私模式等场景存取抛异常时静默降级（功能退化为「提示粘贴」，不影响主流程）。
 */

const KEY_PREFIX = 'jobpilot_campus_ingest_'

/** 与投喂 text 上限一致（接口文档 §3.16）。 */
export const MAX_STASH_CHARS = 20000

export function stashKey(postingId) {
  return `${KEY_PREFIX}${postingId}`
}

function defaultStorage() {
  try {
    return typeof window !== 'undefined' ? window.localStorage : null
  } catch {
    return null
  }
}

/** 存原文；空文本 / 非法 id / 存储不可用 → 返回 false（不抛）。 */
export function saveIngestText(postingId, text, storage = defaultStorage()) {
  const body = String(text ?? '').trim()
  if (!postingId || !body || !storage) return false
  try {
    storage.setItem(stashKey(postingId), body.slice(0, MAX_STASH_CHARS))
    return true
  } catch {
    return false
  }
}

/** 取原文；无暂存 / 存储不可用 → null。 */
export function loadIngestText(postingId, storage = defaultStorage()) {
  if (!postingId || !storage) return null
  try {
    const value = storage.getItem(stashKey(postingId))
    return value || null
  } catch {
    return null
  }
}
