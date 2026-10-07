/**
 * 播报单例（SRS §3.11 / 接口文档 §3.13）。
 *
 * 本模块是**浏览器适配层**：把 `Audio`、blob URL、`ttsSpeakingKey` 接进
 * `utils/speechQueue.js` 的队列核心（顺序、抢跑、作废、失败静默停都在那里，纯逻辑可单测）。
 *
 * 两种播法共用同一条队列，天然互斥：
 * - **整段播**（`play`）：手动点播报 / 设置页试听——段数组 `[{text, key}]` 展开成
 *   ≤2000 字的 chunk 后一次播完；key = 该段归属的消息对象，用于段级点亮；
 * - **流式播**（`start` / `push` / `finish`）：模拟面试边输出边念——`utils/ttsStream.js`
 *   在页面上把 delta 切成句子，凑满一句 `push` 一句，图文基本同步。
 *
 * 打断：`stop()` 停音频并作废整条队列；手动播放与流式播放互相打断。
 * 失败（60002 / 网络 / `play()` 被拒）：整轮静默停止，不弹错——用户可手动再点播报。
 */
import { ref } from 'vue'
import { synthesizeSpeech } from '../api/voice.js'
import { expandSpeechChunks, toSpeakableText } from './ttsText.js'
import { createSpeechQueue } from './speechQueue.js'

export const ttsPlaying = ref(false)
export const ttsSpeakingKey = ref(null)

let audio = null
let settleCurrent = null
const liveUrls = new Set()

const queue = createSpeechQueue({
  synthesize: async (text, ctx) => {
    const blob = await synthesizeSpeech(text, ctx?.voice)
    const url = URL.createObjectURL(blob)
    liveUrls.add(url)
    return url
  },
  play: playUrl,
  release: (url) => {
    liveUrls.delete(url)
    URL.revokeObjectURL(url)
  },
  onKey: (key) => {
    ttsSpeakingKey.value = key
  },
  onActive: (on) => {
    ttsPlaying.value = on
    // 播完 / 被停：点亮态一并收回（否则最后一句的图标会一直停在「停止」态）
    if (!on) ttsSpeakingKey.value = null
  }
})

/** 播放一个 blob URL；返回是否正常播完（被打断 / 播错都返回 false）。 */
function playUrl(url) {
  return new Promise((resolve) => {
    const a = new Audio(url)
    let settled = false
    const settle = (ok) => {
      if (settled) return
      settled = true
      if (audio === a) {
        audio = null
        settleCurrent = null
      }
      resolve(ok)
    }
    audio = a
    settleCurrent = settle
    a.onended = () => settle(true)
    a.onerror = () => settle(false)
    a.play().catch(() => settle(false))
  })
}

/** 掐掉正在播的音频，并让挂起的 `play` 以 false 结束（队列的旧泵据此退出）。 */
function stopAudio() {
  const a = audio
  audio = null
  if (a) {
    a.onended = null
    a.onerror = null
    try {
      a.pause()
    } catch {
      /* 忽略 */
    }
  }
  const settle = settleCurrent
  settleCurrent = null
  settle?.(false)
}

/** 开一轮播报：先掐掉上一轮（音频 + 队列），再换上新参数。 */
function beginRun(ctx) {
  stopAudio()
  queue.start(ctx)
}

/** 立即停：停音频、作废队列、收回点亮态。 */
export function stopSpeech() {
  queue.stop()
  stopAudio()
  for (const url of liveUrls) URL.revokeObjectURL(url)
  liveUrls.clear()
  ttsPlaying.value = false
  ttsSpeakingKey.value = null
}

/** 流式播报：开一轮（每轮作答开始时调，会停掉上一轮）。 */
export function startStream() {
  beginRun({ voice: null }) // 会话内用账号设置音色，由后端取默认
}

/** 流式播报：追加一句（句子来自 `ttsStream` 的增量分句）。 */
export function pushSpeech(text, key) {
  if (text) queue.push(text, key)
}

/** 流式播报：本轮不再有新句子（余量播完自然收尾）。 */
export function finishStream() {
  queue.finish()
}

/** 整段播放：段数组 `[{text, key}]`（手动播报 / 回看页 / 设置页试听）。 */
export function playSpeech(segments, { voice } = {}) {
  beginRun({ voice })
  for (const chunk of expandSpeechChunks(segments)) queue.push(chunk.text, chunk.key)
  queue.finish()
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

export const ttsPlayer = {
  play: playSpeech,
  stop: stopSpeech,
  startStream,
  pushSpeech,
  finishStream
}
