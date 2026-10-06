import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  silenceMsForSpeed, createSpeedTracker, createVadState,
  updateVadSilence, pushVadFrame,
  SPEECH_MIN_MS, SENTENCE_MAX_MS, DEFAULT_SILENCE_MS, CALIBRATE_MS
} from '../src/utils/audioVad.js'

const STEP = 32 // 帧粒度 32ms（与 worklet 批一致）

/** 连续喂 rms 值共 durationMs 毫秒，收集所有事件；返回 [events, 最后 nowMs] */
function feed(state, rms, durationMs, startMs) {
  const events = []
  let now = startMs
  const end = startMs + durationMs
  while (now < end) {
    now += STEP
    events.push(...pushVadFrame(state, rms, now))
  }
  return [events, now]
}

test('silenceMsForSpeed：三档阈值与缺省值', () => {
  assert.equal(silenceMsForSpeed(null), DEFAULT_SILENCE_MS)
  assert.equal(silenceMsForSpeed(5), 1600)
  assert.equal(silenceMsForSpeed(4), 1600)
  assert.equal(silenceMsForSpeed(3), 2650)
  assert.equal(silenceMsForSpeed(2), 2650)
  assert.equal(silenceMsForSpeed(1.5), 3600)
})

test('speedTracker：滑动平均与窗口滚动', () => {
  const t = createSpeedTracker(3)
  assert.equal(t.value, null)
  t.push(4, 1000) // 4 字/秒
  assert.equal(t.value, 4)
  t.push(2, 1000)
  assert.equal(t.value, 3)
  t.push(6, 1000)
  assert.equal(t.value, 4)
  t.push(10, 1000) // 窗口滚动：只留最近 3 句
  assert.equal(t.value, 6)
})

test('静音切句：事件时间轴正确且不含尾部静音', () => {
  const s = createVadState({ silenceMs: 1000, minRms: 0.01 })
  let [, now] = feed(s, 0.0005, 300, 0) // 校准静音
  const [evs, now2] = feed(s, 0.2, 1000, now) // 说话 1s
  const [events, now3] = feed(s, 0.0005, 1100, now2) // 静音 1.1s > 阈值 1s
  const all = [...evs, ...events]
  assert.equal(all.length, 1)
  const e = all[0]
  assert.equal(e.type, 'speech')
  assert.equal(e.forced, false)
  assert.ok(e.startMs >= CALIBRATE_MS && e.startMs <= CALIBRATE_MS + 2 * STEP) // 语音始于校准结束后的首个判定帧（≤2 帧延迟）
  // endMs = 最后一声（落在说话段末尾，容 2 帧），而不是静音判定点（第三段末尾 ~now3）
  assert.ok(e.endMs >= e.startMs + 900 && e.endMs <= e.startMs + 1000)
  assert.ok(e.endMs < now3)
  assert.equal(e.durationMs, e.endMs - e.startMs)
})

test('连说 15s 无停顿触发强制切句', () => {
  const s = createVadState({ silenceMs: 100000, minRms: 0.01 })
  feed(s, 0.0005, 300, 0)
  const [evs] = feed(s, 0.3, SENTENCE_MAX_MS + 1000, 288)
  assert.ok(evs.length >= 1)
  assert.equal(evs[0].forced, true)
  assert.ok(Math.abs(evs[0].durationMs - SENTENCE_MAX_MS) < STEP * 2)
})

test('有效语音不足 400ms 的段丢弃', () => {
  const s = createVadState({ silenceMs: 500, minRms: 0.01 })
  feed(s, 0.0005, 300, 0)
  const [evs1, now] = feed(s, 0.2, 200, 288) // 说话 200ms
  const [evs2] = feed(s, 0.0005, 600, now)
  assert.equal(evs1.length + evs2.length, 0)
  assert.ok(SPEECH_MIN_MS > 200)
})

test('噪声底随静音期自愈下降', () => {
  const s = createVadState({ minRms: 0.005 })
  // 校准期就给高噪声（模拟开麦即说 / 环境噪）
  feed(s, 0.05, 350, 0)
  assert.ok(s.noiseFloor >= 0.05 - 1e-9)
  // 长时间真实静音 → 噪声底被 EMA 拉低
  feed(s, 0.001, 3000, 320)
  assert.ok(s.noiseFloor < 0.02)
})

test('updateVadSilence：改写阈值后按新值切句', () => {
  const s = createVadState({ silenceMs: 3600, minRms: 0.01 })
  feed(s, 0.0005, 300, 0)
  const [evs, now] = feed(s, 0.2, 1000, 288)
  assert.equal(evs.length, 0)
  updateVadSilence(s, 5) // 语速快 → 1.6s 档
  assert.equal(s.silenceMs, 1600)
  const [evs2] = feed(s, 0.0005, 1700, now)
  assert.equal(evs2.filter((e) => e.type === 'speech' && !e.forced).length, 1)
})
