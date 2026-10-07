import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  METRICS,
  deltaTone,
  durationText,
  formatDelta,
  metricValue,
  sourceLabel,
  trendSeries
} from '../src/utils/drillMeta.js'

test('sourceLabel：六值中文标签，未知值兜底返回原值', () => {
  assert.equal(sourceLabel('CUSTOM'), '手动新建')
  assert.equal(sourceLabel('WRONG'), '错题本')
  assert.equal(sourceLabel('EXPERIENCE'), '面经')
  assert.equal(sourceLabel('JD'), '投递记录')
  assert.equal(sourceLabel('RESUME'), '画像经历')
  assert.equal(sourceLabel('INTRO'), '自我介绍')
  assert.equal(sourceLabel('FOO'), 'FOO')
  assert.equal(sourceLabel(null), '')
})

test('durationText：分秒口径与空值', () => {
  assert.equal(durationText(68000), '1分08秒')
  assert.equal(durationText(95000), '1分35秒')
  assert.equal(durationText(45000), '45秒')
  assert.equal(durationText(60000), '1分00秒')
  assert.equal(durationText(null), '—')
  assert.equal(durationText(undefined), '—')
})

test('metricValue：按指标口径格式化，缺值统一 —', () => {
  assert.equal(metricValue('score', 8), '8')
  assert.equal(metricValue('duration_ms', 68000), '1分08秒')
  assert.equal(metricValue('speech_rate', 235), '235')
  assert.equal(metricValue('speech_ratio', 0.85), '85%')
  assert.equal(metricValue('filler_count', 0), '0')
  assert.equal(metricValue('filler_count', null), '—')
  assert.equal(metricValue('pause_count', undefined), '—')
})

test('formatDelta：好坏方向按指标定义，无优劣的指标不带箭头，缺值 —', () => {
  assert.equal(formatDelta('filler_count', 12, 4), '12→4 ↓')
  assert.equal(formatDelta('score', 5, 8), '5→8 ↑')
  assert.equal(formatDelta('score', 8, 5), '8→5 ↓')
  assert.equal(formatDelta('pause_count', 3, 3), '3→3 →')
  assert.equal(formatDelta('duration_ms', 95000, 68000), '1分35秒→1分08秒 ↓')
  assert.equal(formatDelta('speech_rate', 210, 235), '210→235') // 语速无优劣，不带箭头
  assert.equal(formatDelta('speech_ratio', 0.71, 0.85), '71%→85% ↑')
  assert.equal(formatDelta('score', null, 8), '—')
  assert.equal(formatDelta('score', 5, undefined), '—')
})

test('deltaTone：好坏判读（着色用），无优劣方向或缺值 → null', () => {
  assert.equal(deltaTone('filler_count', 12, 4), 'good') // 填充词下降为好
  assert.equal(deltaTone('filler_count', 4, 12), 'bad')
  assert.equal(deltaTone('score', 5, 8), 'good')
  assert.equal(deltaTone('score', 8, 5), 'bad')
  assert.equal(deltaTone('pause_count', 3, 3), 'flat')
  assert.equal(deltaTone('speech_rate', 210, 235), null) // 语速只作参考
  assert.equal(deltaTone('score', null, 5), null)
})

test('METRICS：六项定义齐全、键名与接口字段一致', () => {
  assert.deepEqual(
    METRICS.map((m) => m.key),
    ['score', 'duration_ms', 'speech_rate', 'filler_count', 'pause_count', 'speech_ratio']
  )
  for (const m of METRICS) assert.ok(m.label && ['up', 'down', null].includes(m.better))
})

test('trendSeries：跳过缺该指标的遍次并记下来，其余按 seq 升序', () => {
  const items = [
    { seq: 1, score: 5, speech_rate: 210, filler_count: 12 },
    { seq: 2, score: 7, speech_rate: null, filler_count: 7 },
    { seq: 3, score: 8, speech_rate: 235, filler_count: 4 }
  ]
  assert.deepEqual(trendSeries(items, 'speech_rate'), {
    points: [
      { seq: 1, value: 210 },
      { seq: 3, value: 235 }
    ],
    skipped: [2]
  })
  assert.deepEqual(trendSeries(items, 'score').points.map((p) => p.value), [5, 7, 8])
  assert.deepEqual(trendSeries([], 'score'), { points: [], skipped: [] })
  assert.deepEqual(trendSeries(null, 'score'), { points: [], skipped: [] })
})
