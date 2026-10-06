/**
 * WAV 编码与重采样（纯函数）。
 *
 * 录音链路上传的是**自编码的 16bit PCM 单声道 WAV**（而非 MediaRecorder 的 webm）：
 * 时间轴按样本计数换算、切句不丢字、后端 PyAV 解码零悬念。参数与后端统一按 16kHz。
 */

/** Float32 样本 → 16bit PCM 单声道 WAV（44 字节头 + 小端数据）。 */
export function encodeWav(samples, sampleRate) {
  const dataSize = samples.length * 2
  const buf = new ArrayBuffer(44 + dataSize)
  const view = new DataView(buf)
  const writeStr = (offset, s) => {
    for (let i = 0; i < s.length; i++) view.setUint8(offset + i, s.charCodeAt(i))
  }
  writeStr(0, 'RIFF')
  view.setUint32(4, 36 + dataSize, true)
  writeStr(8, 'WAVE')
  writeStr(12, 'fmt ')
  view.setUint32(16, 16, true) // fmt chunk 大小
  view.setUint16(20, 1, true) // PCM
  view.setUint16(22, 1, true) // 单声道
  view.setUint32(24, sampleRate, true)
  view.setUint32(28, sampleRate * 2, true) // byteRate = 采样率 × 1 声道 × 2 字节
  view.setUint16(32, 2, true) // blockAlign
  view.setUint16(34, 16, true) // 位深
  writeStr(36, 'data')
  view.setUint32(40, dataSize, true)
  for (let i = 0; i < samples.length; i++) {
    const x = Math.max(-1, Math.min(1, samples[i]))
    view.setInt16(44 + i * 2, x < 0 ? x * 0x8000 : x * 0x7fff, true)
  }
  return buf
}

/**
 * 重采样到 16kHz（线性插值）。
 * AudioContext 指定 16000 采样率在 Chromium 上通常直接生效，此函数是
 * 「实际采样率非 16k」时的兜底；同采样率原样返回（不拷贝）。
 */
export function resampleTo16k(samples, fromRate) {
  if (fromRate === 16000) return samples
  const outLen = Math.round((samples.length * 16000) / fromRate)
  const out = new Float32Array(outLen)
  const ratio = fromRate / 16000
  for (let i = 0; i < outLen; i++) {
    const pos = i * ratio
    const idx = Math.floor(pos)
    const frac = pos - idx
    const a = samples[idx] ?? 0
    const b = samples[idx + 1] ?? a
    out[i] = a + (b - a) * frac
  }
  return out
}
