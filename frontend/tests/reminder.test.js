import { test } from 'node:test'
import assert from 'node:assert/strict'
import { reminderMeta, remindDayLabel } from '../src/constants/reminder.js'

test('reminderMeta：四类类型的标签与跳转落点', () => {
  assert.equal(reminderMeta('INTERVIEW').label, '面试提醒')
  assert.equal(reminderMeta('INTERVIEW').route, '/applications')
  assert.equal(reminderMeta('FOLLOW_UP').route, '/applications')
  assert.equal(reminderMeta('WRONG_QUESTION').route, '/wrong-questions')
  assert.equal(reminderMeta('INFO_MATCH').route, '/campus')
})

test('reminderMeta：未知类型兜底（原值展示、不跳转），不炸', () => {
  const m = reminderMeta('SOMETHING_NEW')
  assert.equal(m.label, 'SOMETHING_NEW')
  assert.equal(m.route, null)
  assert.ok(m.color)
  assert.equal(reminderMeta(null).label, '提醒')
})

test('remindDayLabel：今天 / 昨天 / 更早显示 MM-DD', () => {
  const p2 = (n) => String(n).padStart(2, '0')
  const fmt = (d) => `${d.getFullYear()}-${p2(d.getMonth() + 1)}-${p2(d.getDate())}`
  const today = new Date()
  assert.equal(remindDayLabel(fmt(today)), '今天')
  const y = new Date(today)
  y.setDate(y.getDate() - 1)
  assert.equal(remindDayLabel(fmt(y)), '昨天')
  const old = new Date(today)
  old.setDate(old.getDate() - 5)
  assert.match(remindDayLabel(fmt(old)), /^\d{2}-\d{2}$/)
})

test('remindDayLabel：带时间的 datetime 只取日期部分；坏输入原样返回不炸', () => {
  const p2 = (n) => String(n).padStart(2, '0')
  const d = new Date()
  assert.equal(remindDayLabel(`${d.getFullYear()}-${p2(d.getMonth() + 1)}-${p2(d.getDate())} 07:00:00`), '今天')
  assert.equal(remindDayLabel(''), '')
  assert.equal(remindDayLabel(null), '')
  assert.equal(remindDayLabel('坏数据'), '坏数据')
})
