import { test } from 'node:test'
import assert from 'node:assert/strict'
import { TOUR_STEPS, filterAvailableSteps, shouldStartTour } from '../src/utils/guide.js'

test('TOUR_STEPS：5 步、锚点唯一非空、标题与说明齐备', () => {
  assert.equal(TOUR_STEPS.length, 5)
  assert.deepEqual(
    TOUR_STEPS.map((s) => s.element),
    [
      '[data-tour="Applications"]',
      '[data-tour="JdAnalysis"]',
      '[data-tour="InterviewList"]',
      '[data-tour="Practice"]',
      '[data-tour="UserMenu"]'
    ]
  )
  for (const s of TOUR_STEPS) {
    // driver.js 的 DriveStep 结构：文案在 popover 子对象里（放顶层不会被渲染）
    assert.ok(s.popover?.title && s.popover?.description)
  }
})

test('shouldStartTour：仅 guide_done !== true 启动；异常输入不启动', () => {
  assert.equal(shouldStartTour({ guide_done: false }), true)
  assert.equal(shouldStartTour({ guide_done: true }), false)
  assert.equal(shouldStartTour({ tts_enabled: false }), true) // 字段缺失 = 未确认
  assert.equal(shouldStartTour(null), false) // 设置拉取失败：静默不启动
  assert.equal(shouldStartTour(undefined), false)
})

test('filterAvailableSteps：注入 query 桩过滤缺失锚点；全缺失返回空数组', () => {
  const steps = [{ element: 'a' }, { element: 'b' }, { element: 'c' }]
  const all = filterAvailableSteps(steps, () => ({}))
  assert.deepEqual(all.map((s) => s.element), ['a', 'b', 'c'])

  const some = filterAvailableSteps(steps, (sel) => (sel === 'b' ? null : {}))
  assert.deepEqual(some.map((s) => s.element), ['a', 'c'])

  assert.deepEqual(filterAvailableSteps(steps, () => null), [])
})
