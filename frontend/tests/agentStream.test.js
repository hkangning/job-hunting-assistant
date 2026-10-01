import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  applyAgentDelta, parseResultBlock, normalizeHistory, confirmFields, parseAgentError
} from '../src/utils/agentStream.js'

test('applyAgentDelta：普通 delta 追加文本', () => {
  const msg = { text: '', result: null, resultRaw: '' }
  applyAgentDelta(msg, { text: '好的，' })
  applyAgentDelta(msg, { text: '帮你记一笔' })
  assert.equal(msg.text, '好的，帮你记一笔')
  assert.equal(msg.result, null)
})

test('applyAgentDelta：result 段累积解析（抗网络拆帧）', () => {
  const msg = { text: '', result: null, resultRaw: '' }
  applyAgentDelta(msg, { text: '{"type":"list_app', section: 'result' })
  assert.equal(msg.result, null) // 分片未完整时不发散
  applyAgentDelta(msg, { text: 'lications","data":{"total":1,"items":[]}}', section: 'result' })
  assert.deepEqual(msg.result, { type: 'list_applications', data: { total: 1, items: [] } })
})

test('parseResultBlock：坏 JSON / 非对象 / 缺 type 返回 null', () => {
  assert.equal(parseResultBlock('{"type":'), null)
  assert.equal(parseResultBlock('[1,2]'), null)
  assert.equal(parseResultBlock('{"data":{}}'), null)
  assert.equal(parseResultBlock(''), null)
})

test('normalizeHistory：USER/ASSISTANT 映射、TOOL 跳过、顺序保持', () => {
  let n = 0
  const out = normalizeHistory([
    { role: 'USER', content: '记一笔' },
    { role: 'TOOL', content: '{"total":0}', tool_name: 'list_applications' },
    { role: 'ASSISTANT', content: '好的' }
  ], () => ++n)
  assert.deepEqual(out.map((m) => m.role), ['user', 'assistant'])
  assert.equal(out[0].text, '记一笔')
  assert.equal(out[1].streaming, false)
  assert.equal(out[1].toolCall, null)
})

test('confirmFields：create_application 只列有值字段', () => {
  const rows = confirmFields('create_application', {
    company: '浩鲸科技', position: 'Java 开发', applied_at: '2026-10-01', jd_text: 'xxx'
  })
  assert.deepEqual(rows, [
    { label: '公司', value: '浩鲸科技' },
    { label: '岗位', value: 'Java 开发' },
    { label: '投递日期', value: '2026-10-01' }
  ])
})

test('confirmFields：update_application_status 中文映射与 #id 兜底', () => {
  const rows = confirmFields('update_application_status', { application_id: 12, status: 'INTERVIEW' })
  assert.deepEqual(rows, [
    { label: '投递', value: '#12' },
    { label: '目标状态', value: '面试中' }
  ])
  const rows2 = confirmFields(
    'update_application_status',
    { application_id: 12, status: 'CLOSED', close_reason: 'FAILED' },
    { appName: '浩鲸科技' }
  )
  assert.deepEqual(rows2, [
    { label: '投递', value: '浩鲸科技' },
    { label: '目标状态', value: '已结束' },
    { label: '结束原因', value: '未通过' }
  ])
})

test('parseAgentError：10012 给配置入口、10002 提示会话失效、其余透传', () => {
  assert.equal(parseAgentError({ code: 10012 }).needConfig, true)
  assert.match(parseAgentError({ code: 10002 }).message, /会话已失效/)
  assert.equal(parseAgentError({ code: 10010, message: '模型异常' }).message, '模型异常')
  assert.equal(parseAgentError({}).needConfig, false)
})
