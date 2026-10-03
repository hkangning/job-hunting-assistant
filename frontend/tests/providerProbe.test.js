import { test } from 'node:test'
import assert from 'node:assert/strict'
import { probeParams } from '../src/utils/providerProbe.js'

/** 编辑态的已存配置：Key 已保存、端点为注册表默认。 */
const ITEM = { key_set: true, base_url: 'https://api.deepseek.com' }

test('probeParams：编辑态填了新 Key —— 用表单值探测（本次修复的核心口径）', () => {
  // 用户「换 Key」的主路径：填了新 Key 点刷新 / 失焦，就该用新 Key 去拉列表，
  // 而不是继续用已存的旧 Key（旧实现恒取已存 Key，「填 Key 刷新列表」反而报旧 Key 的错）
  assert.deepEqual(probeParams({ api_key: 'sk-new', base_url: ITEM.base_url }, ITEM), {
    apiKey: 'sk-new',
    baseUrl: ''
  })
})

test('probeParams：编辑态未填 Key —— 不携带，后端回落已存配置', () => {
  assert.deepEqual(probeParams({ api_key: '', base_url: ITEM.base_url }, ITEM), {
    apiKey: '',
    baseUrl: ''
  })
})

test('probeParams：端点与已存相同视同未改、不携带；改动才携带', () => {
  assert.equal(probeParams({ api_key: '', base_url: ITEM.base_url }, ITEM).baseUrl, '')
  assert.equal(
    probeParams({ api_key: '', base_url: 'https://proxy.example.com' }, ITEM).baseUrl,
    'https://proxy.example.com'
  )
})

test('probeParams：新增态（无已存配置）填了就携带', () => {
  assert.deepEqual(probeParams({ api_key: 'sk-a', base_url: 'http://127.0.0.1:9000/v1' }, null), {
    apiKey: 'sk-a',
    baseUrl: 'http://127.0.0.1:9000/v1'
  })
})

test('probeParams：防御 —— 字段缺失按未填处理', () => {
  assert.deepEqual(probeParams({}, null), { apiKey: '', baseUrl: '' })
})
