import { test } from 'node:test'
import assert from 'node:assert/strict'
import { dueText, nextPlanText } from '../src/utils/reviewPlan.js'

const NOW = new Date('2026-09-29T20:00:00')

test('dueText：已到期（含当天早先）→ 今天该复习', () => {
  assert.equal(dueText('2026-09-29 09:00:00', NOW), '今天该复习')
  assert.equal(dueText('2026-09-28 09:00:00', NOW), '今天该复习')
})

test('dueText：未到期 → N 天后复习（向上取整）', () => {
  assert.equal(dueText('2026-09-30 09:00:00', NOW), '1 天后复习')
  assert.equal(dueText('2026-10-02 09:00:00', NOW), '3 天后复习')
})

test('nextPlanText：今天 / 明天 / N 天后（带 MM-DD）', () => {
  assert.equal(nextPlanText('2026-09-29 09:00:00', NOW), '今天（09-29）')
  assert.equal(nextPlanText('2026-09-30 09:00:00', NOW), '明天（09-30）')
  assert.equal(nextPlanText('2026-10-02 09:00:00', NOW), '3 天后（10-02）')
})

test('空值不炸：坏输入按「今天」处理', () => {
  assert.equal(dueText('', NOW), '今天该复习')
  assert.ok(nextPlanText('', NOW).startsWith('今天'))
})
