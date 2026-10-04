import { test } from 'node:test'
import assert from 'node:assert/strict'
import { monthRange, buildMonthGrid, groupByDay, dateKey } from '../src/utils/campusCalendar.js'

test('monthRange：月初与月末（含闰年二月）', () => {
  assert.deepEqual(monthRange(new Date(2026, 9, 4)), { start: '2026-10-01', end: '2026-10-31' })
  assert.deepEqual(monthRange(new Date(2026, 1, 15)), { start: '2026-02-01', end: '2026-02-28' })
  assert.deepEqual(monthRange(new Date(2024, 1, 1)), { start: '2024-02-01', end: '2024-02-29' })
})

test('buildMonthGrid：周一为列首、补齐整周、含前后月占位', () => {
  const grid = buildMonthGrid(new Date(2026, 9, 1)) // 2026-10：10-01 为周四
  assert.equal(grid.length % 7, 0)
  assert.equal(grid[0].date, '2026-09-28') // 周一
  assert.equal(grid[0].inMonth, false)
  assert.equal(grid[grid.length - 1].inMonth, false)
  assert.ok(grid.some((c) => c.date === '2026-10-01' && c.inMonth === true))
  assert.ok(grid.some((c) => c.date === '2026-10-31' && c.inMonth === true))
  // 日期连续（后一格恒为前一天 +1）
  for (let i = 1; i < grid.length; i++) {
    const prev = new Date(`${grid[i - 1].date}T00:00:00`)
    prev.setDate(prev.getDate() + 1)
    assert.equal(grid[i].date, dateKey(prev))
  }
})

test('groupByDay：按 event_at 的日期分组、同日保序', () => {
  const map = groupByDay([
    { event_at: '2026-10-03T09:00:00', title: 'A' },
    { event_at: '2026-10-03T14:00:00', title: 'B' },
    { event_at: '2026-10-05T10:00:00', title: 'C' }
  ])
  assert.equal(Object.keys(map).length, 2)
  assert.deepEqual(map['2026-10-03'].map((i) => i.title), ['A', 'B'])
  assert.deepEqual(map['2026-10-05'].map((i) => i.title), ['C'])
})

test('groupByDay：空数组与缺时间字段兜底不炸', () => {
  assert.deepEqual(groupByDay([]), {})
  assert.deepEqual(groupByDay([{ title: '无时间' }]), {})
})

test('dateKey：本地日期格式化，不经过时区往返', () => {
  assert.equal(dateKey(new Date(2026, 0, 5)), '2026-01-05')
  assert.equal(dateKey(new Date(2026, 11, 31)), '2026-12-31')
})
