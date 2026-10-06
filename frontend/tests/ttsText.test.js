import { test } from 'node:test'
import assert from 'node:assert/strict'
import { toSpeakableText, expandSpeechChunks, splitForTts } from '../src/utils/ttsText.js'

test('toSpeakableText：点评剥标题行与评分行', () => {
  const review = '## 点评\n评分 8/10，亮点：条理清晰。\n不足：缺少示例。'
  const t = toSpeakableText('review', review)
  assert.ok(!t.includes('##'))
  assert.ok(!t.includes('评分'))
  assert.ok(t.includes('亮点：条理清晰。'))
})

test('toSpeakableText：提问走纯文本、空值安全', () => {
  assert.equal(toSpeakableText('question', '## 下一题\n请讲讲缓存雪崩的成因。'), '请讲讲缓存雪崩的成因。')
  assert.equal(toSpeakableText('review', ''), '')
  assert.equal(toSpeakableText('question', null), '')
  assert.equal(toSpeakableText('question', undefined), '')
})

test('expandSpeechChunks：多段展开、段内切分、key 透传、空段过滤', () => {
  const long = '句子。'.repeat(900) // 2700 字 → 段内切 2 块
  const chunks = expandSpeechChunks([
    { text: '第一段。', key: 'k1' },
    { text: long, key: 'k2' },
    { text: '   ', key: 'k3' } // 空段不产生块
  ])
  assert.equal(chunks[0].text, '第一段。')
  assert.equal(chunks[0].key, 'k1')
  assert.ok(chunks.length >= 3)
  assert.ok(chunks.slice(1).every((c) => c.key === 'k2'))
  for (const c of chunks) assert.ok(c.text.length <= 2000)
  assert.deepEqual(expandSpeechChunks(null), [])
  assert.deepEqual(expandSpeechChunks([]), [])
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
