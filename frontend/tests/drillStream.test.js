import { test } from 'node:test'
import assert from 'node:assert/strict'
import { applyDelta, applyDone, createAttempt, reviewBody } from '../src/utils/drillStream.js'

test('createAttempt：空壳', () => {
  const a = createAttempt()
  assert.equal(a.score, null)
  assert.equal(a.review, '')
  assert.equal(a.recordId, null)
  assert.equal(a.seq, null)
  assert.equal(a.voiceMetrics, null)
})

test('score 段三种写法都能解析出分数，且可跨 delta 拼出来', () => {
  for (const [chunks, expected] of [
    [['8/10'], 8],
    [['8 分'], 8],
    [['评分 8/10'], 8],
    [['评分 ', '8/10'], 8],
    [['7.5 分'], 7.5]
  ]) {
    const a = createAttempt()
    for (const c of chunks) applyDelta(a, { section: 'score', text: c })
    assert.equal(a.score, expected, chunks.join(''))
  }
})

test('score 段解析不出时不写分数、也不污染点评正文', () => {
  const a = createAttempt()
  applyDelta(a, { section: 'score', text: '本次得分：' })
  applyDelta(a, { section: 'review', text: '## 点评\n亮点：条理清晰。' })
  assert.equal(a.score, null)
  assert.ok(a.review.includes('亮点：条理清晰。'))
})

test('review 段累进；无 section 的 delta 并入点评（纯文本降级）', () => {
  const a = createAttempt()
  applyDelta(a, { section: 'review', text: '亮点：先讲结论。' })
  applyDelta(a, { text: '不足：缺少示例。' })
  assert.equal(a.review, '亮点：先讲结论。不足：缺少示例。')
})

test('applyDone：回填 record_id / seq / voice_metrics；分数缺失时从点评正文兜底解析', () => {
  const a = createAttempt()
  applyDelta(a, { section: 'review', text: '## 点评\n评分 6/10，亮点：条理清晰。' })
  applyDone(a, { record_id: 12, seq: 3, extra: { voice_metrics: { version: 1, quality: 'OK' } } })
  assert.equal(a.recordId, 12)
  assert.equal(a.seq, 3)
  assert.deepEqual(a.voiceMetrics, { version: 1, quality: 'OK' })
  assert.equal(a.score, 6)

  const b = createAttempt()
  applyDone(b, { record_id: 13, seq: 1 })
  assert.equal(b.recordId, 13)
  assert.equal(b.score, null)
  assert.equal(b.voiceMetrics, null)
})

test('空 delta / 空 attempt 容错', () => {
  const a = createAttempt()
  assert.doesNotThrow(() => applyDelta(a, null))
  assert.doesNotThrow(() => applyDelta(a, { section: 'review' }))
  assert.doesNotThrow(() => applyDone(a, null))
  assert.equal(a.review, '')
})

test('reviewBody：剥标题行与评分行（与面试 / 陪练同口径）', () => {
  const a = createAttempt()
  applyDelta(a, { section: 'review', text: '## 点评\n评分 8/10，亮点：条理清晰。' })
  assert.equal(reviewBody(a), '亮点：条理清晰。')
  assert.equal(reviewBody(null), '')
})
