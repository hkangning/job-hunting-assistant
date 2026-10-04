import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  campusEventStatus,
  splitSourceSites,
  sourceSiteBrief,
  JOB_TYPE_META,
  INFO_TYPE_META,
  INGEST_SOURCE_META,
  CALENDAR_TYPE_META,
  CRAWL_STATUS_META,
  jobTypeLabel,
  infoTypeLabel,
  ingestSourceLabel,
  calendarTypeMeta,
  crawlStatusMeta
} from '../src/constants/campus.js'

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

test('jobTypeLabel / infoTypeLabel / ingestSourceLabel：中文名 + 未知空值兜底', () => {
  assert.equal(jobTypeLabel('CAMPUS'), '校招')
  assert.equal(jobTypeLabel('INTERN'), '实习')
  assert.equal(jobTypeLabel('SOCIAL'), '社招')
  assert.equal(jobTypeLabel('XXX'), '')
  assert.equal(jobTypeLabel(null), '')
  assert.equal(infoTypeLabel('TALK'), '宣讲会')
  assert.equal(infoTypeLabel('FAIR'), '双选会')
  assert.equal(infoTypeLabel(null), '')
  assert.equal(ingestSourceLabel('FEED'), '我投喂的')
  assert.equal(ingestSourceLabel('AUTO'), '自动抓取')
  assert.equal(ingestSourceLabel(undefined), '')
})

test('calendarTypeMeta：四类事件中文名 + 未知兜底', () => {
  assert.equal(calendarTypeMeta('TALK').label, '宣讲会')
  assert.equal(calendarTypeMeta('FAIR').label, '双选会')
  assert.equal(calendarTypeMeta('EXAM').label, '笔试')
  assert.equal(calendarTypeMeta('INTERVIEW').label, '面试')
  assert.equal(calendarTypeMeta('SOMETHING_NEW').label, '')
})

test('crawlStatusMeta：三态中文名 + 未知兜底', () => {
  assert.equal(crawlStatusMeta('OK').label, '成功')
  assert.equal(crawlStatusMeta('FAILED').label, '失败')
  assert.equal(crawlStatusMeta('BLOCKED').label, '受限')
  assert.equal(crawlStatusMeta('XXX').label, '未知')
  assert.equal(crawlStatusMeta(null).label, '未知')
})

test('映射表把全部已知枚举登记齐（防漏登记）', () => {
  assert.deepEqual(Object.keys(JOB_TYPE_META).sort(), ['CAMPUS', 'INTERN', 'SOCIAL'])
  assert.deepEqual(Object.keys(INFO_TYPE_META).sort(), ['FAIR', 'TALK'])
  assert.deepEqual(Object.keys(INGEST_SOURCE_META).sort(), ['AUTO', 'FEED'])
  assert.deepEqual(Object.keys(CALENDAR_TYPE_META).sort(), ['EXAM', 'FAIR', 'INTERVIEW', 'TALK'])
  assert.deepEqual(Object.keys(CRAWL_STATUS_META).sort(), ['BLOCKED', 'FAILED', 'OK'])
})
