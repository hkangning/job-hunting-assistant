import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  createTurn, applyDelta, getBlock, parseRoundScore, toPlainText, DIMENSION_LABELS
} from '../src/utils/practiceStream.js'

test('按 section 分流成块，同 section 的 delta 依次拼接', () => {
  const turn = createTurn()
  applyDelta(turn, { text: '7 分', section: 'round_score' })
  applyDelta(turn, { text: '，答得不错', section: 'round_score' })
  applyDelta(turn, { text: '缺少量化估算', section: 'review' })
  assert.equal(turn.blocks.length, 2)
  assert.equal(turn.blocks[0].section, 'round_score')
  assert.equal(turn.blocks[0].text, '7 分，答得不错')
  assert.equal(turn.blocks[1].section, 'review')
  assert.equal(turn.blocks[1].text, '缺少量化估算')
})

test('dimensions 是一次性 JSON：解析为对象，同时保留块供渲染定位', () => {
  const turn = createTurn()
  applyDelta(turn, {
    text: '{"framework":8,"quantification":5,"tradeoff":7,"fallback":6}',
    section: 'dimensions'
  })
  assert.deepEqual(turn.dimensions, { framework: 8, quantification: 5, tradeoff: 7, fallback: 6 })
  // 块必须留在 blocks 里：渲染是按 blocks 顺序遍历的，四维分栏也要有自己的位置
  assert.equal(turn.blocks.length, 1)
  assert.equal(turn.blocks[0].section, 'dimensions')
})

test('dimensions 非法 JSON 降级为文本块，不使整轮渲染失败', () => {
  const turn = createTurn()
  applyDelta(turn, { text: '不是 JSON', section: 'dimensions' })
  assert.equal(turn.dimensions, null)
  assert.equal(getBlock(turn, 'dimensions').text, '不是 JSON')
})

test('dimensions 分片到达时累积到可解析为止', () => {
  const turn = createTurn()
  applyDelta(turn, { text: '{"framework":8,', section: 'dimensions' })
  assert.equal(turn.dimensions, null)
  applyDelta(turn, { text: '"quantification":5,"tradeoff":7,"fallback":6}', section: 'dimensions' })
  assert.equal(turn.dimensions.framework, 8)
  assert.equal(turn.dimensions.fallback, 6)
})

test('无 section 的 delta 追加到最后一个块（纯文本降级）', () => {
  const turn = createTurn()
  applyDelta(turn, { text: '评分 6 分', section: 'round_score' })
  applyDelta(turn, { text: '，补充说明' })
  assert.equal(turn.blocks.length, 1)
  assert.equal(getBlock(turn, 'round_score').text, '评分 6 分，补充说明')
})

test('首个 delta 就没有 section 时自成一块', () => {
  const turn = createTurn()
  applyDelta(turn, { text: '一段没有锚点的文本' })
  assert.equal(turn.blocks.length, 1)
  assert.equal(turn.blocks[0].section, 'text')
})

test('getBlock 取不到返回 undefined', () => {
  assert.equal(getBlock(createTurn(), 'summary'), undefined)
})

test('toPlainText 剥掉标题行与行内强调标记', () => {
  assert.equal(toPlainText('## 本轮评分\n评分 0/10，答错了。'), '评分 0/10，答错了。')
  assert.equal(toPlainText('\n## 点评\n标准答案是……'), '\n标准答案是……')
  assert.equal(toPlainText('## 追问\n'), '')
  assert.equal(toPlainText('**重点**：`-Xmx` 参数没交代'), '重点：-Xmx 参数没交代')
  assert.equal(toPlainText('没有标题的纯文本'), '没有标题的纯文本')
  assert.equal(toPlainText(''), '')
})

test('parseRoundScore 适配后端实际下发的「评分 X/10」段落', () => {
  assert.deepEqual(parseRoundScore('## 本轮评分\n评分 0/10，答错了。'), { score: 0, note: '答错了。' })
  assert.deepEqual(parseRoundScore('## 本轮评分\n评分 7/10，思路清晰。'), { score: 7, note: '思路清晰。' })
  assert.deepEqual(parseRoundScore('评分 10 / 10。完整'), { score: 10, note: '完整' })
})

test('parseRoundScore 兼容「X 分」写法', () => {
  assert.deepEqual(parseRoundScore('7 分，答得不错'), { score: 7, note: '答得不错' })
  assert.deepEqual(parseRoundScore('**8 分**：思路清晰'), { score: 8, note: '思路清晰' })
  assert.deepEqual(parseRoundScore('10 分。完整'), { score: 10, note: '完整' })
})

test('parseRoundScore 取不出分数时整体作结论文本', () => {
  assert.deepEqual(parseRoundScore('答得还行'), { score: null, note: '答得还行' })
  assert.deepEqual(parseRoundScore('11 分'), { score: null, note: '11 分' })
  assert.deepEqual(parseRoundScore(''), { score: null, note: '' })
})

test('DIMENSION_LABELS 覆盖四个维度', () => {
  assert.deepEqual(Object.keys(DIMENSION_LABELS), ['framework', 'quantification', 'tradeoff', 'fallback'])
})
