import { test } from 'node:test'
import assert from 'node:assert/strict'
import { campusEventStatus, splitSourceSites, sourceSiteBrief } from '../src/constants/campus.js'

test('splitSourceSites：逗号分隔多来源拆为数组，逐项 trim', () => {
  assert.deepEqual(splitSourceSites('njust-91job'), ['njust-91job'])
  assert.deepEqual(splitSourceSites('njust-91job, njust-bysjy'), ['njust-91job', 'njust-bysjy'])
  assert.deepEqual(splitSourceSites('a,,b'), ['a', 'b'])
})

test('splitSourceSites：空值 / 空白 / 非字符串返回空数组，不炸', () => {
  assert.deepEqual(splitSourceSites(''), [])
  assert.deepEqual(splitSourceSites(null), [])
  assert.deepEqual(splitSourceSites(undefined), [])
  assert.deepEqual(splitSourceSites(' , '), [])
  assert.deepEqual(splitSourceSites(123), [])
})

test('sourceSiteBrief：单来源原样；多来源显示首个 + “+N”', () => {
  assert.equal(sourceSiteBrief('njust-91job'), 'njust-91job')
  assert.equal(sourceSiteBrief('a,b'), 'a +1')
  assert.equal(sourceSiteBrief('a, b, c'), 'a +2')
  assert.equal(sourceSiteBrief(''), '')
  assert.equal(sourceSiteBrief(null), '')
})

test('campusEventStatus：CHANGED 打角标、EXPIRED 灰化、ACTIVE 不标记', () => {
  assert.deepEqual(campusEventStatus('CHANGED'), { changed: true, muted: false })
  assert.deepEqual(campusEventStatus('EXPIRED'), { changed: false, muted: true })
  assert.deepEqual(campusEventStatus('ACTIVE'), { changed: false, muted: false })
})

test('campusEventStatus：未知 / 空值兜底为普通态，不炸', () => {
  assert.deepEqual(campusEventStatus('SOMETHING_NEW'), { changed: false, muted: false })
  assert.deepEqual(campusEventStatus(null), { changed: false, muted: false })
})
