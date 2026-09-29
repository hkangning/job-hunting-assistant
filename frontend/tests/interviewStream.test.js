import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  buildMessages, applyDelta, appendAnswer, insertSkipped, sealStreaming
} from '../src/utils/interviewStream.js'

// ---------------- buildMessages：qa_list 展开 ----------------

test('空 qa_list → 无消息、tail=empty', () => {
  const { messages, tail } = buildMessages({ question_count: 8 }, [])
  assert.deepEqual(messages, [])
  assert.equal(tail, 'empty')
})

test('完整一轮展开为 提问/作答/点评 三条消息', () => {
  const qa = [{ seq: 1, question: 'Q1', answer: 'A1', skipped: 0, score: 8, review: 'R1' }]
  const { messages } = buildMessages({ question_count: 8 }, qa)
  assert.deepEqual(messages, [
    { kind: 'question', seq: 1, text: 'Q1' },
    { kind: 'answer', text: 'A1', skipped: false },
    { kind: 'review', score: 8, text: 'R1' }
  ])
})

test('跳过条目：作答消息带 skipped 标记、无点评卡片', () => {
  const qa = [{ seq: 1, question: 'Q1', answer: null, skipped: 1, score: null, review: null }]
  const { messages } = buildMessages({ question_count: 8 }, qa)
  assert.deepEqual(messages, [
    { kind: 'question', seq: 1, text: 'Q1' },
    { kind: 'answer', text: '', skipped: true }
  ])
})

// ---------------- buildMessages：尾态判定 ----------------

test('末条未作答 → tail=awaiting-answer，且不生成作答/点评消息', () => {
  const qa = [
    { seq: 1, question: 'Q1', answer: 'A1', skipped: 0, score: 8, review: 'R1' },
    { seq: 2, question: 'Q2', answer: null, skipped: 0, score: null, review: null }
  ]
  const { messages, tail } = buildMessages({ question_count: 8 }, qa)
  assert.equal(tail, 'awaiting-answer')
  assert.equal(messages.length, 4)
  assert.equal(messages[3].kind, 'question')
})

test('满题量且末条已作答 → tail=finished', () => {
  const qa = [
    { seq: 1, question: 'Q1', answer: 'A1', skipped: 0, score: 8, review: 'R1' },
    { seq: 2, question: 'Q2', answer: 'A2', skipped: 0, score: 7, review: 'R2' }
  ]
  const { tail } = buildMessages({ question_count: 2 }, qa)
  assert.equal(tail, 'finished')
})

test('满题量时末条点评缺失也按 finished（面试已到题量，不再出题）', () => {
  const qa = [{ seq: 1, question: 'Q1', answer: 'A1', skipped: 0, score: null, review: null }]
  const { tail } = buildMessages({ question_count: 1 }, qa)
  assert.equal(tail, 'finished')
})

test('已作答、下一题未生成（未满题量）→ tail=midway', () => {
  const qa = [
    { seq: 1, question: 'Q1', answer: 'A1', skipped: 0, score: 8, review: 'R1' },
    { seq: 2, question: 'Q2', answer: 'A2', skipped: 0, score: 7, review: 'R2' }
  ]
  const { tail } = buildMessages({ question_count: 5 }, qa)
  assert.equal(tail, 'midway')
})

test('已作答但点评未完成 → tail=midway（流断在点评中途，可继续）', () => {
  const qa = [{ seq: 1, question: 'Q1', answer: 'A1', skipped: 0, score: null, review: null }]
  const { tail } = buildMessages({ question_count: 5 }, qa)
  assert.equal(tail, 'midway')
})

test('跳过后未满题量 → tail=midway（同下一题未生成）', () => {
  const qa = [{ seq: 1, question: 'Q1', answer: null, skipped: 1, score: null, review: null }]
  const { tail } = buildMessages({ question_count: 8 }, qa)
  assert.equal(tail, 'midway')
})

// ---------------- applyDelta：流式增量归段 ----------------

test('review 段建点评卡片、后续增量拼接', () => {
  const messages = []
  applyDelta(messages, { text: '亮点：', section: 'review' })
  applyDelta(messages, { text: '答得清楚', section: 'review' })
  assert.equal(messages.length, 1)
  assert.equal(messages[0].kind, 'review')
  assert.equal(messages[0].text, '亮点：答得清楚')
  assert.equal(messages[0].streaming, true)
})

test('next_question 段建提问、seq 续已有最大题号', () => {
  const messages = [
    { kind: 'question', seq: 1, text: 'Q1' },
    { kind: 'answer', text: 'A1', skipped: false },
    { kind: 'review', score: 8, text: 'R1' }
  ]
  applyDelta(messages, { text: '第 2 题：', section: 'next_question' })
  applyDelta(messages, { text: '说一下 JVM', section: 'next_question' })
  const last = messages[messages.length - 1]
  assert.equal(messages.length, 4)
  assert.equal(last.kind, 'question')
  assert.equal(last.seq, 2)
  assert.equal(last.text, '第 2 题：说一下 JVM')
})

test('首题（无 review，直接 next_question）→ seq=1', () => {
  const messages = []
  applyDelta(messages, { text: '你好，先自我介绍一下', section: 'next_question' })
  assert.equal(messages[0].kind, 'question')
  assert.equal(messages[0].seq, 1)
})

test('无 section 的 delta 追加到末尾流式消息', () => {
  const messages = [{ kind: 'question', seq: 1, text: 'Q1', streaming: true }]
  applyDelta(messages, { text: '补充' })
  assert.equal(messages[0].text, 'Q1补充')
})

test('无 section 且末尾无流式消息 → 忽略，不建游离消息', () => {
  const messages = [{ kind: 'question', seq: 1, text: 'Q1' }]
  applyDelta(messages, { text: '游离文本' })
  assert.equal(messages.length, 1)
  assert.equal(messages[0].text, 'Q1')
})

// ---------------- sealStreaming / 本地插入 ----------------

test('sealStreaming：流式标记全部清掉', () => {
  const messages = [
    { kind: 'review', score: null, text: 'R', streaming: true },
    { kind: 'question', seq: 2, text: 'Q', streaming: true }
  ]
  sealStreaming(messages)
  assert.equal(messages[0].streaming, false)
  assert.equal(messages[1].streaming, false)
})

test('appendAnswer / insertSkipped：两种作答消息形态', () => {
  const messages = []
  appendAnswer(messages, '我的作答')
  insertSkipped(messages)
  assert.deepEqual(messages[0], { kind: 'answer', text: '我的作答', skipped: false })
  assert.deepEqual(messages[1], { kind: 'answer', text: '', skipped: true })
})
