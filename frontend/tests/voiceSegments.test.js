import { test } from 'node:test'
import assert from 'node:assert/strict'
import { addSegment, toSegmentsPayload } from '../src/utils/voiceSegments.js'

test('空文本 / 纯空白不追加', () => {
  const list = []
  assert.equal(addSegment(list, { text: '  ', startMs: 0, endMs: 100 }), false)
  assert.equal(addSegment(list, { text: '', startMs: 0, endMs: 100 }), false)
  assert.equal(addSegment(list, { text: null, startMs: 0, endMs: 100 }), false)
  assert.equal(list.length, 0)
})

test('seq 从 1 递增、字段为 snake_case、文本 trim', () => {
  const list = []
  addSegment(list, { text: '第一句 ', startMs: 100, endMs: 900 })
  addSegment(list, { text: '第二句。', startMs: 2000, endMs: 3000 })
  assert.deepEqual(list, [
    { seq: 1, start_ms: 100, end_ms: 900, text: '第一句' },
    { seq: 2, start_ms: 2000, end_ms: 3000, text: '第二句。' }
  ])
})

test('payload：空列表转 null，非空原样返回', () => {
  assert.equal(toSegmentsPayload([]), null)
  const list = []
  addSegment(list, { text: 'x', startMs: 0, endMs: 500 })
  assert.equal(toSegmentsPayload(list), list)
})
