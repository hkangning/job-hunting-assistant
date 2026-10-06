/**
 * 播报单例（SRS §3.11 / 接口文档 §3.13）。
 *
 * - 播放单元为**段数组** `[{text, key}]`（key = 该段归属的消息对象，用于段级点亮）：
 *   段内按 ≤2000 字切 chunk 顺序连播，播放第 n 个 chunk 时预取第 n+1 个（段间无缝，
 *   同文案同音色后端有缓存、命中毫秒级）；
 * - **段级点亮**：播到某段时 `ttsSpeakingKey` = 该段 key——自动播报「点评 + 下一题」
 *   整轮时，对应消息的图标随之逐个亮起；
 * - 可随时打断：`stop()` 停音频、作废旧异步链路（token 防竞态串音）；
 * - 任一段失败（60002 / 网络）→ 整条队列**静默停止**（不弹错，用户可手动再点播报）；
 * - 全局同一时刻只播一条。
 */
import { ref } from 'vue'
import { synthesizeSpeech } from '../api/voice.js'
import { expandSpeechChunks, toSpeakableText } from './ttsText.js'

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

export async function playSpeech(segments, { voice } = {}) {
  stopSpeech()
  const my = ++token
  const chunks = expandSpeechChunks(segments)
  if (!chunks.length) return
  ttsPlaying.value = true

  let next = synthUrl(chunks[0].text, voice).catch(() => null)
  for (let i = 0; i < chunks.length; i++) {
    const url = await next
    if (my !== token) {
      if (url) URL.revokeObjectURL(url)
      return
    }
    if (!url) break // 合成失败：静默停
    ttsSpeakingKey.value = chunks[i].key // 段级点亮（同段多 chunk 保持同 key）
    next = i + 1 < chunks.length ? synthUrl(chunks[i + 1].text, voice).catch(() => null) : null
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

/** 播放一条消息（所见即所播）：点评播点评正文、提问播题干。 */
export function speakMessage(m) {
  if (!m) return
  const text = toSpeakableText(m.kind, m.text)
  if (text) playSpeech([{ text, key: m }])
}

/** 「朗读 / 停止」toggle：正在播这条即停，否则播放它。 */
export function toggleSpeakMessage(m) {
  if (!m) return
  if (ttsSpeakingKey.value === m) {
    stopSpeech()
    return
  }
  speakMessage(m)
}

export const ttsPlayer = { play: playSpeech, stop: stopSpeech }
