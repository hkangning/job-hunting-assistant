/**
 * 全局 Agent 事件流 → 视图模型（接口文档 v1.39 §3.11 / 台账 #93 的协议事实）。
 *
 * 纯函数、不触网络，可脱离组件直接单测。三条协议要点：
 * ① `section="result"` 是**一次性 JSON 块**（`{"type": 工具名, "data": {...}}`，整块直通）——
 *    与陪练 `dimensions` / `next_choices` 同构：累积原文 + 尝试解析，成功才挂 result（抗拆帧）；
 * ② `tool_call` 的 `args` 是**服务端补全后的完整参数**，前端原样渲染与提交，不再拼装；
 * ③ 历史消息里 `TOOL` 行仅存档（助手文字已含总结），回看时跳过。
 */
// 带 .js 扩展名：本模块被 node:test 直跑（Node 的 ESM 解析不补扩展名；Vite 侧两者皆可）
import { STATUS_LABELS, CLOSE_REASON_LABELS } from '../constants/application.js'

/** 写操作工具的中文名（与后端 ToolSpec.label 一致，卡片标题用）。 */
export const TOOL_LABELS = {
  create_application: '记录一条投递',
  update_application_status: '更新投递进度'
}

/** 消费一个 delta：`result` 段累积解析，其余（含无 section 的追问）追加文本。 */
export function applyAgentDelta(msg, delta) {
  const { text = '', section } = delta || {}
  if (section === 'result') {
    msg.resultRaw = (msg.resultRaw || '') + text
    const parsed = parseResultBlock(msg.resultRaw)
    if (parsed) msg.result = parsed
    return
  }
  msg.text += text
}

/** 解析 result 段：`{type, data}` 形状的对象才有效，否则 null（不渲染卡片）。 */
export function parseResultBlock(raw) {
  const trimmed = String(raw || '').trim()
  if (!trimmed.startsWith('{')) return null
  try {
    const parsed = JSON.parse(trimmed)
    if (parsed && typeof parsed === 'object' && typeof parsed.type === 'string') return parsed
    return null
  } catch {
    return null
  }
}

/** 历史消息（接口正序）→ 本地消息模型；TOOL 行跳过。`nextId` 为本地 id 生成器。 */
export function normalizeHistory(items, nextId) {
  const out = []
  for (const item of items || []) {
    if (item?.role === 'USER') {
      out.push({ id: nextId(), role: 'user', text: item.content || '' })
    } else if (item?.role === 'ASSISTANT') {
      out.push({
        id: nextId(), role: 'assistant', text: item.content || '', streaming: false,
        stopped: false, result: null, resultRaw: '', error: null, toolCall: null
      })
    }
  }
  return out
}

/**
 * 确认卡片字段行（中文标签 + 展示值）。
 * `options.appName`：update_application_status 补拉到的公司名（覆盖 #id 兜底）。
 */
export function confirmFields(toolName, args = {}, options = {}) {
  if (toolName === 'create_application') {
    const rows = []
    const put = (label, value) => {
      if (value != null && String(value).trim()) rows.push({ label, value: String(value) })
    }
    put('公司', args.company)
    put('岗位', args.position)
    put('城市', args.city)
    put('投递日期', args.applied_at)
    put('渠道', args.channel)
    return rows
  }
  if (toolName === 'update_application_status') {
    const name = options.appName || args.company
    const rows = [
      { label: '投递', value: name || (args.application_id != null ? `#${args.application_id}` : '—') },
      { label: '目标状态', value: STATUS_LABELS[args.status] || args.status || '—' }
    ]
    if (args.close_reason) {
      rows.push({ label: '结束原因', value: CLOSE_REASON_LABELS[args.close_reason] || args.close_reason })
    }
    if (args.remark) rows.push({ label: '备注', value: String(args.remark) })
    return rows
  }
  return Object.entries(args).map(([key, value]) => ({ label: key, value: String(value ?? '') }))
}

/** 流错误的展示模型：`needConfig` 供「去 AI 配置」按钮。 */
export function parseAgentError(err) {
  const code = err?.code
  if (code === 10012) {
    return { code, needConfig: true, message: '还没有配置 AI 供应商——去「AI 配置」填一个，回来就能用' }
  }
  if (code === 10002) {
    return { code, needConfig: false, message: '会话已失效，重试将开始新对话' }
  }
  return { code, needConfig: false, message: err?.message || '对话失败，请重试' }
}
