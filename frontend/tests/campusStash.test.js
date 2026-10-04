import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  stashKey,
  saveIngestText,
  loadIngestText,
  MAX_STASH_CHARS
} from '../src/utils/campusStash.js'

/** 内存存储替身：与 localStorage 同接口，供纯函数用例注入。 */
function memoryStorage() {
  const map = new Map()
  return {
    getItem: (k) => (map.has(k) ? map.get(k) : null),
    setItem: (k, v) => map.set(k, String(v)),
    removeItem: (k) => map.delete(k)
  }
}

test('stashKey：按岗位 id 生成固定前缀的键', () => {
  assert.equal(stashKey(12), 'jobpilot_campus_ingest_12')
})

test('save / load：同一岗位存取原文', () => {
  const s = memoryStorage()
  assert.equal(saveIngestText(3, '某公司招聘后端开发……', s), true)
  assert.equal(loadIngestText(3, s), '某公司招聘后端开发……')
  assert.equal(loadIngestText(4, s), null)
})

test('超长原文截断到上限（避免撑爆存储）', () => {
  const s = memoryStorage()
  saveIngestText(5, 'x'.repeat(MAX_STASH_CHARS + 100), s)
  assert.equal(loadIngestText(5, s).length, MAX_STASH_CHARS)
})

test('空文本 / 非法 id 不写入', () => {
  const s = memoryStorage()
  assert.equal(saveIngestText(6, '   ', s), false)
  assert.equal(saveIngestText(null, '文本', s), false)
  assert.equal(saveIngestText(undefined, '文本', s), false)
  assert.equal(loadIngestText(6, s), null)
})

test('存储抛异常（隐私模式等）时静默降级，不炸', () => {
  const broken = {
    getItem: () => { throw new Error('denied') },
    setItem: () => { throw new Error('denied') },
    removeItem: () => {}
  }
  assert.equal(saveIngestText(7, '文本', broken), false)
  assert.equal(loadIngestText(7, broken), null)
})
