import { test } from 'node:test'
import assert from 'node:assert/strict'
import { createSpeechSegmenter } from '../src/utils/ttsStream.js'

test('标题行与评分行不念，且跨 delta 切断也认', () => {
  const s = createSpeechSegmenter('review')
  assert.deepEqual(s.feed('## 点'), [])
  assert.deepEqual(s.feed('评\n评分 8'), [])
  assert.deepEqual(s.feed('/10，亮点：条理清晰。'), ['亮点：条理清晰。'])
})

test('评分行的三种写法（评分 X/10、X/10、X 分）都剥掉', () => {
  for (const head of ['评分 8/10，', '8/10，', '7 分，']) {
    const s = createSpeechSegmenter('review')
    assert.deepEqual(s.feed(`${head}不足：缺少示例。`), ['不足：缺少示例。'])
  }
})

test('段首是正常正文时不被评分前缀按住', () => {
  assert.deepEqual(createSpeechSegmenter('review').feed('亮点：条理清晰。'), ['亮点：条理清晰。'])
  assert.deepEqual(createSpeechSegmenter('review').feed('3 个要点：先讲背景。'), ['3 个要点：先讲背景。'])
})

test('提问段不剥评分样式的数字（剥离只对点评生效）', () => {
  const s = createSpeechSegmenter('question')
  assert.deepEqual(s.feed('## 下一题\n8/10 的把握从哪里来？'), ['8/10 的把握从哪里来？'])
})

test('句末标点即切；未结句的余量按住', () => {
  const s = createSpeechSegmenter('question')
  assert.deepEqual(s.feed('请讲讲'), [])
  assert.deepEqual(s.feed('缓存雪崩的成因。它是'), ['请讲讲缓存雪崩的成因。'])
  assert.deepEqual(s.flush(), ['它是'])
})

test('换行即断句（分条点评一句一条）', () => {
  const s = createSpeechSegmenter('review')
  assert.deepEqual(s.feed('亮点：条理清晰\n不足：缺少示例。'), ['亮点：条理清晰', '不足：缺少示例。'])
})

test('行内标记剥掉，跨 delta 的 ** 不留残迹', () => {
  const s = createSpeechSegmenter('review')
  assert.deepEqual(s.feed('**亮点**：条理'), [])
  assert.deepEqual(s.feed('清晰。'), ['亮点：条理清晰。'])
})

test('句尾的孤立 * 按住，与下一片的 * 配对后再吐出', () => {
  const s = createSpeechSegmenter('review')
  assert.deepEqual(s.feed('亮点：条理清晰*\n'), ['亮点：条理清晰'])
  assert.deepEqual(s.feed('*不足：缺少示例。'), ['不足：缺少示例。'])
})

test('无标点长串按 60 字硬切', () => {
  const s = createSpeechSegmenter('question')
  const parts = s.feed('啊'.repeat(150))
  assert.deepEqual(parts.map((p) => p.length), [60, 60])
  assert.deepEqual(s.flush().map((p) => p.length), [30])
})

test('flush 吐余量、空输入安全、独占的评分 token 丢弃', () => {
  const s = createSpeechSegmenter('question')
  assert.deepEqual(s.feed(''), [])
  assert.deepEqual(s.feed(null), [])
  assert.deepEqual(s.feed(undefined), [])
  assert.deepEqual(s.feed('没说完的半句'), [])
  assert.deepEqual(s.flush(), ['没说完的半句'])
  assert.deepEqual(s.flush(), [])

  const r = createSpeechSegmenter('review')
  assert.deepEqual(r.feed('评分 8/10'), [])
  assert.deepEqual(r.flush(), [])
})
