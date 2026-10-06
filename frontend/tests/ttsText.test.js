import { test } from 'node:test'
import assert from 'node:assert/strict'
import { buildRoundSpeech, splitForTts } from '../src/utils/ttsText.js'

test('buildRoundSpeech：剥标题行与评分行、两段拼接', () => {
  const review = '## 点评\n评分 8/10，亮点：条理清晰。\n不足：缺少示例。'
  const question = '## 下一题\n请讲讲缓存雪崩的成因。'
  const text = buildRoundSpeech(review, question)
  assert.ok(!text.includes('##'))
  assert.ok(!text.includes('评分'))
  assert.ok(text.includes('亮点：条理清晰。'))
  assert.ok(text.includes('请讲讲缓存雪崩的成因。'))
  assert.ok(text.indexOf('亮点') < text.indexOf('请讲讲')) // 点评在前、下一题在后
})

test('buildRoundSpeech：单段缺省与全空', () => {
  assert.equal(buildRoundSpeech('', '## 下一题\n题目'), '题目')
  assert.equal(buildRoundSpeech('## 点评\n直接给结论。', ''), '直接给结论。')
  assert.equal(buildRoundSpeech('', ''), '')
  assert.equal(buildRoundSpeech(null, undefined), '')
})

test('splitForTts：段落切分与空白过滤', () => {
  assert.deepEqual(splitForTts('第一段。\n\n第二段。'), ['第一段。', '第二段。'])
  assert.deepEqual(splitForTts('  \n\n  '), [])
  assert.deepEqual(splitForTts(''), [])
})

test('splitForTts：超长段落按句切分且每段不超限', () => {
  const long = '句子。'.repeat(900) // 2700 字、无空行
  const parts = splitForTts(long)
  assert.ok(parts.length >= 2)
  for (const p of parts) assert.ok(p.length <= 2000)
  assert.equal(parts.join(''), long)
})

test('splitForTts：单句超限硬切', () => {
  const monster = 'a'.repeat(2500) // 无标点长串
  const parts = splitForTts(monster)
  assert.deepEqual(parts.map((p) => p.length), [2000, 500])
  assert.equal(parts.join(''), monster)
})
