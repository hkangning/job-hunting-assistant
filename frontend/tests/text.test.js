import { test } from 'node:test'
import assert from 'node:assert/strict'
import { textLength } from '../src/utils/text.js'

test('textLength：ASCII 与中文按字符计数', () => {
  assert.equal(textLength('hello'), 5)
  assert.equal(textLength('你好，世界'), 5)
})

test('textLength：emoji 按码点计 1（与后端 Python len 一致）', () => {
  assert.equal(textLength('😀'), 1) // JS .length 为 2，用码点才是 1
  assert.equal(textLength('a😀b'), 3)
})

test('textLength：换行计入（\\r\\n 计 2，与后端一致）', () => {
  assert.equal(textLength('a\r\nb'), 4)
})

test('textLength：空值与坏输入返回 0', () => {
  assert.equal(textLength(''), 0)
  assert.equal(textLength(null), 0)
  assert.equal(textLength(undefined), 0)
})
