/**
 * VAD 纯函数状态机（SRS §3.11 FR-014 / 接口文档 §3.13）。
 *
 * 输入是「帧能量 + 该帧结束时刻」的序列（帧粒度 = worklet 批粒度 ~32ms），
 * 输出是切句事件——录音管理（voiceRecorder）只负责喂帧与拿事件，所有判定在这里，
 * 零 DOM 依赖、可直接单测。
 *
 * 关键口径：
 * - **噪声底**：前 300ms 校准期取 RMS 最小值（不低于 minRms）；运行期只在非语音帧、
 *   且帧能量低于当前噪声底 2 倍时才以 EMA 缓慢跟踪——环境变安静会自愈下降，
 *   语音帧不会把噪声底抬高。
 * - **双阈值滞回**：进入语音要求 max(noise*3, minRms)，维持语音放宽到
 *   max(noise*1.8, minRms*0.5)——避免句内字间空隙把一句话切碎。
 * - **时间轴取真实语音端点**：endMs 是最后一声超阈帧的时刻，不含尾部的静音段——
 *   步骤 25 表达力指标要按「句间停顿 = 下一句 start - 上一句 end」算，不能虚增。
 * - **静音阈值按语速自适应**（快 1.6s / 正常 2.65s / 慢 3.6s）：语速由调用方在
 *   每句转写回来后用 createSpeedTracker 估出，经 updateVadSilence 写入。
 */

export const SPEECH_MIN_MS = 400 // 有效语音最短（更短的段按噪声丢弃）
export const SENTENCE_MAX_MS = 15000 // 连说无停顿的强制切句上限
export const CALIBRATE_MS = 300 // 噪声底校准期
export const DEFAULT_SILENCE_MS = 2650 // 语速未知 / 正常档

/** 语速（字/秒）→ 静音阈值毫秒。null（未知）按正常档。 */
export function silenceMsForSpeed(charsPerSec) {
  if (charsPerSec == null || Number.isNaN(charsPerSec)) return DEFAULT_SILENCE_MS
  if (charsPerSec >= 4) return 1600
  if (charsPerSec >= 2) return DEFAULT_SILENCE_MS
  return 3600
}

/** 语速滑动平均（最近 windowSize 句），供 updateVadSilence 使用。 */
export function createSpeedTracker(windowSize = 3) {
  const list = []
  return {
    get value() {
      if (!list.length) return null
      return list.reduce((a, b) => a + b, 0) / list.length
    },
    push(chars, durationMs) {
      if (!(durationMs > 0)) return
      list.push(chars / (durationMs / 1000))
      if (list.length > windowSize) list.shift()
    },
    reset() {
      list.length = 0
    }
  }
}

export function createVadState({ silenceMs = DEFAULT_SILENCE_MS, minRms = 0.01 } = {}) {
  return {
    silenceMs,
    minRms,
    noiseFloor: null, // 校准完成前为 null（判定用 minRms 兜底）
    noiseMin: Infinity,
    noiseCalibrated: false,
    inSpeech: false,
    speechStartMs: 0,
    lastVoiceMs: 0
  }
}

/** 按最新语速改写静音阈值（下一帧判定即生效）。 */
export function updateVadSilence(state, charsPerSec) {
  state.silenceMs = silenceMsForSpeed(charsPerSec)
}

/**
 * 喂一帧能量。返回本帧产生的事件（通常为空数组）：
 * `{ type:'speech', startMs, endMs, durationMs, forced }`。
 */
export function pushVadFrame(state, rms, nowMs) {
  // 校准期：只收集噪声最小值、不做语音判定（学习期内判定没有可靠的噪声底可用，
  // 「开麦即说 / 高底噪」会把噪声底抬高或把噪声误判成语音）；到点后用
  // max(最小值, minRms) 作噪声底，本帧起即参与判定。
  if (!state.noiseCalibrated) {
    if (rms < state.noiseMin) state.noiseMin = rms
    if (nowMs < CALIBRATE_MS) return []
    state.noiseFloor = Math.max(state.noiseMin, state.minRms)
    state.noiseCalibrated = true
  } else if (!state.inSpeech && rms < state.noiseFloor * 2) {
    // 运行期跟踪：只让「明显低于噪声底」的静音帧把噪声底往下带
    state.noiseFloor = Math.max(state.noiseFloor * 0.95 + rms * 0.05, state.minRms)
  }

  const noise = state.noiseFloor ?? 0
  const enter = Math.max(noise * 3, state.minRms)
  const stay = Math.max(noise * 1.8, state.minRms * 0.5)

  if (!state.inSpeech) {
    if (rms >= enter) {
      state.inSpeech = true
      state.speechStartMs = nowMs
      state.lastVoiceMs = nowMs
    }
    return []
  }

  if (rms >= stay) state.lastVoiceMs = nowMs

  const silentFor = nowMs - state.lastVoiceMs
  const spokenFor = nowMs - state.speechStartMs
  const bySilence = silentFor >= state.silenceMs
  const forced = !bySilence && spokenFor >= SENTENCE_MAX_MS
  if (!bySilence && !forced) return []

  const durationMs = state.lastVoiceMs - state.speechStartMs
  const event = { type: 'speech', startMs: state.speechStartMs, endMs: state.lastVoiceMs, durationMs, forced }
  state.inSpeech = false
  return durationMs >= SPEECH_MIN_MS ? [event] : []
}
