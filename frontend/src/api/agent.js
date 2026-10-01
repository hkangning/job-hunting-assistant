/**
 * 全局 Agent 接口封装（接口文档 v1.39 §3.11）。
 *
 * 4 个端点：对话 SSE / 确认卡片执行 / 会话列表 / 会话消息。响应由 `request.js`
 * 拦截器解包，调用方直接拿 `data`；会话 404 + 10002 走拦截器 reject（带 code）。
 */
import request from './request'
import { streamSSE } from '../utils/sse'

/** 对话（SSE）。payload: { conversation_id?, message }；done 回传 conversation_id。 */
export function agentChatStream(payload, handlers, options) {
  return streamSSE('/stream/agent-chat', payload, handlers, options)
}

/** 执行写操作工具（确认卡片）。args 为 tool_call 事件下发的完整参数。 */
export function executeAgentTool(tool, args) {
  return request.post(`/agent/tools/${tool}/execute`, args)
}

/** 会话列表。params: { page?, page_size? }；items = [{id, title, updated_at}]。 */
export function listConversations(params) {
  return request.get('/agent/conversations', { params })
}

/** 会话消息（时间正序）。items = [{id, role, content, tool_name, created_at}]。 */
export function listConversationMessages(id) {
  return request.get(`/agent/conversations/${id}/messages`)
}
