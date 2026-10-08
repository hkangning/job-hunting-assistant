import { test } from 'node:test'
import assert from 'node:assert/strict'
import { normalizeError, fallbackText } from '../src/utils/errorText.js'

test('normalizeError：10012 后端默认文案的「设置页」映射为「AI 配置」页', () => {
  // 后端默认文案来自步骤 6 之前的口径（LLM 配置曾在设置页），前端页面名现为「AI 配置」
  assert.equal(
    normalizeError('未配置 AI 密钥，请前往设置页配置', 10012),
    '未配置 AI 密钥，请前往「AI 配置」页完成配置'
  )
})

test('normalizeError：10012 已指向 AI 配置页的文案原样透传', () => {
  assert.equal(
    normalizeError('API Key 无效或无权限，请前往 AI 配置页检查', 10012),
    'API Key 无效或无权限，请前往 AI 配置页检查'
  )
})

test('normalizeError：10001 的 pydantic 英文串转为友好文案', () => {
  assert.equal(
    normalizeError("username: String should match pattern '^[A-Za-z0-9_]{3,20}$'", 10001),
    '输入内容有误，请检查后重试'
  )
  // 字段名含中文同样识别（后端拼格式为「字段: msg」）
  assert.equal(
    normalizeError('岗位JD: String should have at most 10000 characters', 10001),
    '输入内容有误，请检查后重试'
  )
})

test('normalizeError：10001 的中文业务文案原样透传', () => {
  assert.equal(normalizeError('音频格式不支持或文件已损坏', 10001), '音频格式不支持或文件已损坏')
  assert.equal(normalizeError('参数校验失败', 10001), '参数校验失败')
})

test('normalizeError：其余错误码与文案原样透传', () => {
  assert.equal(normalizeError('该方向暂无题目，请更换方向', 30001), '该方向暂无题目，请更换方向')
  assert.equal(normalizeError('用户名或密码错误', 80004), '用户名或密码错误')
})

test('normalizeError：空 message 回落通用兜底', () => {
  assert.equal(normalizeError('', 10000), '操作失败，请重试')
  assert.equal(normalizeError(null, undefined), '操作失败，请重试')
  assert.equal(normalizeError(undefined, 10012), '操作失败，请重试')
})

test('fallbackText：四类场景文案', () => {
  assert.equal(fallbackText('network'), '网络连接失败，请检查网络后重试')
  assert.equal(fallbackText('server'), '服务暂时不可用，请稍后重试')
  assert.equal(fallbackText('fetch'), '加载失败，请重试')
  assert.equal(fallbackText('submit'), '操作失败，请重试')
})

test('fallbackText：未知场景回落通用兜底', () => {
  assert.equal(fallbackText('unknown'), '操作失败，请重试')
  assert.equal(fallbackText(), '操作失败，请重试')
})
