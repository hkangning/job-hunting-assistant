/**
 * 播报单例（SRS §3.11 / 接口文档 §3.13）。
 *
 * - 逐段合成（`splitForTts` 切 ≤2000 字）顺序连播，播放第 n 段时**预取**第 n+1 段
 *   （段间无缝衔接，且同文案同音色后端有缓存、命中毫秒级）；
 * - 可随时打断：`stop()` 停音频、作废旧异步链路（token 防竞态串音）；
 * - 任一段失败（60002 / 网络）→ 整条队列**静默停止**（不弹错，用户可手动再点播报）；
 * - 全局同一时刻只播一条——`ttsSpeakingKey` 标记「谁在播」，供按钮显停止态。
 */
import { ref } from 'vue'
import { synthesizeSpeech } from '../api/voice.js'
import { splitForTts } from './ttsText.js'

export const ttsPlaying = ref(false)
export const ttsSpeakingKey = ref(null)

let token = 0
let audio = null
let liveUrls = new Set()

export function stopSpeech() {
  token += 1
  if (audio) {
    audio.onended = null
    audio.onerror = null
    try {
      audio.pause()
    } catch {
      /* 忽略 */
    }
    audio = null
  }
  for (const u of liveUrls) URL.revokeObjectURL(u)
  liveUrls.clear()
  ttsPlaying.value = false
  ttsSpeakingKey.value = null
}

async function synthUrl(text, voice) {
  const blob = await synthesizeSpeech(text, voice)
  const url = URL.createObjectURL(blob)
  liveUrls.add(url)
  return url
}

/** 播放一个 blob URL，返回是否正常播完（被打断 / 播错都返回 false）。 */
function playUrl(url) {
  return new Promise((resolve) => {
    const a = new Audio(url)
    audio = a
    a.onended = () => resolve(true)
    a.onerror = () => resolve(false)
    a.play().catch(() => resolve(false))
  })
}

export async function playSpeech(text, { voice, key } = {}) {
  stopSpeech()
  const my = ++token
  const parts = splitForTts(text)
  if (!parts.length) return
  ttsPlaying.value = true
  ttsSpeakingKey.value = key ?? null

  let next = synthUrl(parts[0], voice).catch(() => null)
  for (let i = 0; i < parts.length; i++) {
    const url = await next
    if (my !== token) {
      if (url) URL.revokeObjectURL(url)
      return
    }
    if (!url) break // 合成失败：静默停
    next = i + 1 < parts.length ? synthUrl(parts[i + 1], voice).catch(() => null) : null
    const ok = await playUrl(url)
    if (my !== token) return
    URL.revokeObjectURL(url)
    liveUrls.delete(url)
    if (!ok) break
  }
  if (my === token) {
    ttsPlaying.value = false
    ttsSpeakingKey.value = null
  }
}

export const ttsPlayer = { play: playSpeech, stop: stopSpeech }
