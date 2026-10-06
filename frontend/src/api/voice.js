/**
 * 语音接口封装（接口文档 §3.13，步骤 24 后端已就绪）。
 *
 * - transcribe：multipart `file`，单片段 ≤2MB，返回 `{text, duration_ms}`；
 *   失败（60001）由调用方降级（保留音频可重试），故带 silent；
 * - synthesize：成功为**音频流**（blob 直通，不走统一响应体）；失败（60002 或网络错误）
 *   一律静默——调用方在播放链路上静默停止，不弹错；
 * - voices：14 个中文音色，账号所配音色置顶（`{id, name, gender, style}`）。
 */
import request from './request'

export function transcribeAudio(blob) {
  const form = new FormData()
  form.append('file', blob, 'segment.wav')
  return request.post('/asr/transcribe', form, { silent: true })
}

export function synthesizeSpeech(text, voice) {
  return request.post(
    '/tts/synthesize',
    voice ? { text, voice } : { text },
    { responseType: 'blob', silent: true }
  )
}

export function getTtsVoices() {
  return request.get('/tts/voices')
}
