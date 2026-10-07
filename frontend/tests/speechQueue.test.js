import { test } from 'node:test'
import assert from 'node:assert/strict'
import { createSpeechQueue } from '../src/utils/speechQueue.js'

const tick = () => new Promise((r) => setTimeout(r, 0))

/**
 * 受控播放台：`play` 的 promise 由测试手动结束（模拟音频播完 / 被打断），
 * 合成默认「原样返回文本」，可按 `failText` 指定某句合成失败。
 */
function harness({ failText = null, lead } = {}) {
  const played = []
  const pending = []
  const released = []
  const synthCalls = []
  const keys = []
  const active = []
  let failed = 0
  const q = createSpeechQueue({
    synthesize: async (text) => {
      synthCalls.push(text)
      return text === failText ? null : text
    },
    play: (handle) =>
      new Promise((resolve) => {
        played.push(handle)
        pending.push({ handle, resolve })
      }),
    release: (h) => released.push(h),
    onKey: (k) => keys.push(k),
    onActive: (v) => active.push(v),
    onFail: () => (failed += 1),
    ...(lead == null ? {} : { lead })
  })
  return {
    q,
    played,
    released,
    keys,
    active,
    synthCalls,
    get failed() {
      return failed
    },
    /** 结束当前这一句的播放（`ok=false` 模拟播放失败）。 */
    endCurrent: (ok = true) => pending.shift()?.resolve(ok)
  }
}

test('顺序播放、逐句回调 key、播完自然结束并释放', async () => {
  const c = harness()
  c.q.start()
  c.q.push('一。', 'k1')
  c.q.push('二。', 'k2')
  c.q.finish()
  await tick()
  assert.deepEqual(c.played, ['一。'])
  c.endCurrent()
  await tick()
  assert.deepEqual(c.played, ['一。', '二。'])
  c.endCurrent()
  await tick()
  assert.deepEqual(c.keys, ['k1', 'k2'])
  assert.deepEqual(c.active, [true, false])
  assert.deepEqual(c.released, ['一。', '二。'])
})

test('抢跑合成有上界：领先播放游标 2 句', async () => {
  const c = harness()
  c.q.start()
  for (const t of ['一。', '二。', '三。', '四。', '五。']) c.q.push(t, t)
  await tick()
  assert.deepEqual(c.synthCalls, ['一。', '二。', '三。'])
  c.endCurrent()
  await tick()
  assert.deepEqual(c.synthCalls, ['一。', '二。', '三。', '四。'])
})

test('流式追加：等新句期间保持播放态，接上即播，finish 后收尾', async () => {
  const c = harness()
  c.q.start()
  c.q.push('一。', 'k1')
  await tick()
  c.endCurrent()
  await tick()
  assert.deepEqual(c.played, ['一。'])
  assert.deepEqual(c.active, [true]) // 还没 finish：仍在等后续句子
  c.q.push('二。', 'k2')
  await tick()
  assert.deepEqual(c.played, ['一。', '二。'])
  c.endCurrent()
  c.q.finish()
  await tick()
  assert.deepEqual(c.active, [true, false])
})

test('stop 作废整轮：在途结果释放、后续不播、状态归位', async () => {
  const c = harness()
  c.q.start()
  c.q.push('一。', 'k1')
  c.q.push('二。', 'k2')
  c.q.push('三。', 'k3')
  await tick()
  assert.deepEqual(c.played, ['一。'])
  c.q.stop()
  await tick()
  assert.deepEqual(c.active, [true, false])
  c.endCurrent() // 适配层掐音频后 play 以 false 结束：也不该继续播
  await tick()
  assert.deepEqual(c.played, ['一。'])
  assert.equal(c.released.length, 3) // 已就绪的三句产物都释放（顺序不敏感）
  for (const t of ['一。', '二。', '三。']) assert.ok(c.released.includes(t))
})

test('合成失败：整轮静默停，onFail 一次', async () => {
  const c = harness({ failText: '二。' })
  c.q.start()
  c.q.push('一。', 'k1')
  c.q.push('二。', 'k2')
  c.q.push('三。', 'k3')
  c.q.finish()
  await tick()
  c.endCurrent()
  await tick()
  assert.deepEqual(c.played, ['一。'])
  assert.equal(c.failed, 1)
  assert.deepEqual(c.active, [true, false])
})

test('播放失败（play 返回 false）：整轮停，不再播后续', async () => {
  const c = harness()
  c.q.start()
  c.q.push('一。', 'k1')
  c.q.push('二。', 'k2')
  c.q.finish()
  await tick()
  c.endCurrent(false)
  await tick()
  assert.deepEqual(c.played, ['一。'])
  assert.deepEqual(c.active, [true, false])
})

test('start 开新一轮：旧轮在途结果作废并释放', async () => {
  const c = harness()
  c.q.start()
  c.q.push('旧一。', 'o1')
  c.q.push('旧二。', 'o2')
  await tick()
  assert.deepEqual(c.played, ['旧一。'])
  c.q.start() // 新一轮（适配层同时掐掉当前音频）
  c.endCurrent(false)
  c.q.push('新一。', 'n1')
  await tick()
  assert.deepEqual(c.played, ['旧一。', '新一。'])
  assert.deepEqual(c.keys, ['o1', 'n1'])
  assert.ok(c.released.includes('旧二。'))
})

test('lead 可调：lead=1 时最多领先 2 句', async () => {
  const c = harness({ lead: 1 })
  c.q.start()
  for (const t of ['一。', '二。', '三。']) c.q.push(t, t)
  await tick()
  assert.deepEqual(c.synthCalls, ['一。', '二。'])
})
