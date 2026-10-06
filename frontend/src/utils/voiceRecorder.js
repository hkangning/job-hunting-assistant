/**
 * 录音管理（SRS §3.11 FR-014）：getUserMedia → AudioContext(16k) → AudioWorklet 采批
 * → VAD 状态机切句（audioVad.js）→ 自编码 WAV → **串行上传**转写。
 *
 * 为什么串行：后端本地模型加载与推理均加锁串行化，前端并发上传无收益且会乱序——
 * 顺序即句序，segments 的 seq 依赖它。
 *
 * 失败语义：单句转写失败不阻塞流程——音频进 `failed` 列表，UI 提示「N 句转写失败 · 重试」，
 * `retryFailed()` 重传（重传走同一处理路径，再失败重新入列）。
 */
import { transcribeAudio } from '../api/voice.js'
import { encodeWav, resampleTo16k } from './audioWav.js'
import {
  createVadState, createSpeedTracker, pushVadFrame, updateVadSilence, SPEECH_MIN_MS
} from './audioVad.js'

const TARGET_RATE = 16000

export function createVoiceRecorder({ onLevel, onSentence, onError, onPendingChange } = {}) {
  let stream = null
  let ctx = null
  let node = null
  let vad = createVadState()
  const speed = createSpeedTracker(3)
  let pending = 0
  let speechBuffer = [] // 当前句累积的批样本（[Float32Array]）
  let queue = Promise.resolve()
  const failed = [] // 失败句：{ wav, event, samples }
  let active = false

  function concat(chunks) {
    let len = 0
    for (const c of chunks) len += c.length
    const out = new Float32Array(len)
    let off = 0
    for (const c of chunks) {
      out.set(c, off)
      off += c.length
    }
    return out
  }

  function rmsOf(samples) {
    let sum = 0
    for (let i = 0; i < samples.length; i++) sum += samples[i] * samples[i]
    return Math.sqrt(sum / samples.length)
  }

  /** 上传一段 WAV：成功 → onSentence + 语速更新；失败 → 入 failed + onError。 */
  async function upload(wav, event, samples) {
    pending += 1
    onPendingChange?.(pending)
    try {
      const { text } = await transcribeAudio(wav)
      const t = String(text ?? '').trim()
      if (t) {
        speed.push(t.length, event.durationMs)
        updateVadSilence(vad, speed.value)
        onSentence?.({ text: t, startMs: event.startMs, endMs: event.endMs })
      }
    } catch {
      failed.push({ wav, event, samples })
      onError?.()
    } finally {
      pending -= 1
      onPendingChange?.(pending)
    }
  }

  function toWav(samples) {
    return new Blob([encodeWav(samples, TARGET_RATE)], { type: 'audio/wav' })
  }

  function enqueue(samples, event) {
    const wav = toWav(samples)
    queue = queue.then(() => upload(wav, event, samples))
  }

  function handleBatch({ samples, startSample }) {
    const rate = ctx.sampleRate
    const endMs = ((startSample + samples.length) * 1000) / rate
    const rms = rmsOf(samples)
    // 音量指示：RMS → 0~1（开方拉高低音量段的可见度）
    onLevel?.(Math.min(1, Math.sqrt(rms) * 4))

    const events = pushVadFrame(vad, rms, endMs)
    if (vad.inSpeech) speechBuffer.push(samples)
    for (const e of events) {
      const buffered = speechBuffer
      speechBuffer = []
      let seg = concat(buffered)
      if (rate !== TARGET_RATE) seg = resampleTo16k(seg, rate)
      enqueue(seg, e)
    }
  }

  async function start() {
    if (active) return
    const media = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, channelCount: 1 }
    })
    try {
      const audioCtx = new AudioContext({ sampleRate: TARGET_RATE })
      // worklet 脚本放 public/（见 public/pcm-worklet.js 顶部注释：addModule 不接受
      // Vite 对小块资产的内联 data URL）；BASE_URL 兼容非根路径部署
      await audioCtx.audioWorklet.addModule(`${import.meta.env.BASE_URL}pcm-worklet.js`)
      const worklet = new AudioWorkletNode(audioCtx, 'pcm-collector')
      const source = audioCtx.createMediaStreamSource(media)
      const mute = audioCtx.createGain()
      mute.gain.value = 0 // 静默：只为激活处理链，不外放麦克风声音（防啸叫）
      source.connect(worklet)
      worklet.connect(mute)
      mute.connect(audioCtx.destination)

      stream = media
      ctx = audioCtx
      node = worklet
      vad = createVadState()
      speed.reset()
      speechBuffer = []
      worklet.port.onmessage = (e) => handleBatch(e.data)
      active = true
    } catch (err) {
      media.getTracks().forEach((t) => t.stop())
      throw err
    }
  }

  async function stop() {
    if (!active) return
    active = false
    // 手动停止时当前句未完：把已说出的部分作为尾句切出（同 VAD 口径）
    if (vad.inSpeech) {
      const event = {
        type: 'speech',
        startMs: vad.speechStartMs,
        endMs: vad.lastVoiceMs,
        durationMs: vad.lastVoiceMs - vad.speechStartMs,
        forced: true
      }
      vad.inSpeech = false
      if (event.durationMs >= SPEECH_MIN_MS) {
        const buffered = speechBuffer
        speechBuffer = []
        let seg = concat(buffered)
        if (ctx.sampleRate !== TARGET_RATE) seg = resampleTo16k(seg, ctx.sampleRate)
        enqueue(seg, event)
      }
    }
    try {
      if (node) node.port.onmessage = null
      await ctx?.close()
    } catch {
      /* 关闭异常忽略 */
    }
    stream?.getTracks().forEach((t) => t.stop())
    stream = null
    ctx = null
    node = null
  }

  function retryFailed() {
    const items = failed.splice(0)
    for (const { wav, event, samples } of items) {
      queue = queue.then(() => upload(wav, event, samples))
    }
  }

  function failedCount() {
    return failed.length
  }

  function isRecording() {
    return active
  }

  function dispose() {
    void stop()
    failed.length = 0
  }

  return { start, stop, retryFailed, failedCount, isRecording, dispose }
}
