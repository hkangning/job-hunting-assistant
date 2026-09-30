import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  buildMessages, applyDelta, appendAnswer, insertSkipped, sealStreaming, splitReview, stageProgress,
  INTENSITY_LABELS, parseCandidates
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

// ---------------- splitReview：点评正文分段 ----------------

test('splitReview：标准三节解析为 亮点 / 不足 / 参考要点', () => {
  const parts = splitReview(
    '亮点：说清了线程私有区域。\n不足：没提直接内存。\n参考要点：线程私有 —— 程序计数器、虚拟机栈；共享 —— 堆、方法区。'
  )
  assert.deepEqual(parts, [
    { kind: 'good', label: '亮点', text: '说清了线程私有区域。' },
    { kind: 'bad', label: '不足', text: '没提直接内存。' },
    { kind: 'note', label: '参考要点', text: '线程私有 —— 程序计数器、虚拟机栈；共享 —— 堆、方法区。' }
  ])
})

test('splitReview：容忍 `- ` 前缀、半角冒号与「参考答案」措辞', () => {
  const parts = splitReview('- 亮点: 有个好细节\n- 参考答案: 骨架如下')
  assert.equal(parts[0].kind, 'good')
  assert.equal(parts[0].text, '有个好细节')
  assert.equal(parts[1].label, '参考要点')
  assert.equal(parts[1].text, '骨架如下')
})

test('splitReview：无前缀的续行并入上一段（长段落换行不断段）', () => {
  const parts = splitReview('- 不足：没有提到直接内存，\n它在 NIO 场景下很关键。\n- 参考要点：略。')
  assert.equal(parts.length, 2)
  assert.equal(parts[0].text, '没有提到直接内存，\n它在 NIO 场景下很关键。')
})

test('splitReview：无结构文本原样返回单段（含段内空行）', () => {
  const parts = splitReview('这是一段没有分节的点评。\n\n第二段。')
  assert.deepEqual(parts, [{ kind: 'plain', label: null, text: '这是一段没有分节的点评。\n\n第二段。' }])
})

test('splitReview：总结报告的「建议」归指导类（note）', () => {
  const parts = splitReview('- 建议：补 JVM 第 2、3 章。')
  assert.deepEqual(parts, [{ kind: 'note', label: '建议', text: '补 JVM 第 2、3 章。' }])
})

// ---------------- stageProgress：面试阶段进度 ----------------

const STAGES = [
  { stage: 'INTRO', count: 1 },
  { stage: 'TECH', count: 5 },
  { stage: 'PROJECT', count: 2 }
]

test('stageProgress：按题号定位阶段与阶段内进度', () => {
  assert.deepEqual(stageProgress(STAGES, 1), { stage: 'INTRO', label: '自我介绍', index: 1, count: 1 })
  assert.deepEqual(stageProgress(STAGES, 2), { stage: 'TECH', label: '技术问答', index: 1, count: 5 })
  assert.deepEqual(stageProgress(STAGES, 6), { stage: 'TECH', label: '技术问答', index: 5, count: 5 })
  assert.deepEqual(stageProgress(STAGES, 7), { stage: 'PROJECT', label: '项目深挖', index: 1, count: 2 })
})

test('stageProgress：无简历的计划（不含项目段）', () => {
  const plan = [
    { stage: 'INTRO', count: 1 },
    { stage: 'TECH', count: 7 }
  ]
  assert.equal(stageProgress(plan, 5).index, 4)
  assert.equal(stageProgress(plan, 8).stage, 'TECH')
})

test('stageProgress：越界与无计划返回 null（调用方降级为「第 N/M 题」）', () => {
  assert.equal(stageProgress(STAGES, 9), null)
  assert.equal(stageProgress(STAGES, 0), null)
  assert.equal(stageProgress(null, 3), null)
  assert.equal(stageProgress([], 3), null)
})

// ---------------- INTENSITY_LABELS：面试强度中文名 ----------------

test('INTENSITY_LABELS：三档中文名齐全', () => {
  assert.equal(INTENSITY_LABELS.LARGE, '大厂')
  assert.equal(INTENSITY_LABELS.MEDIUM, '中厂')
  assert.equal(INTENSITY_LABELS.SMALL, '小厂')
})

// ---------------- parseCandidates：总结流错题候选段 ----------------

test('parseCandidates：正常 JSON 返回候选数组', () => {
  const text = '{"candidates":[{"content":"JVM 分代回收","answer":"新生代…","direction":"JVM"}]}'
  const list = parseCandidates(text)
  assert.equal(list.length, 1)
  assert.equal(list[0].content, 'JVM 分代回收')
  assert.equal(list[0].direction, 'JVM')
})

test('parseCandidates：```json 围栏与前后杂文剥离', () => {
  const text = '好的：\n```json\n{"candidates":[{"content":"A","answer":"B","direction":"GENERAL"}]}\n```\n以上。'
  assert.equal(parseCandidates(text).length, 1)
})

test('parseCandidates：坏 JSON / 空 / 结构不符返回 []', () => {
  assert.deepEqual(parseCandidates(''), [])
  assert.deepEqual(parseCandidates('not json'), [])
  assert.deepEqual(parseCandidates('{"foo":1}'), [])
  assert.deepEqual(parseCandidates('{"candidates":[{"answer":"无题干"}]}'), [])
})
