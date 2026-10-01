/**
 * 全局 Agent 悬浮球状态（系统设计 §4.2：悬浮球开关、对话历史、工具确认卡片队列）。
 *
 * 消息模型（本地，不入库）：
 *   user       { id, role:'user', text }
 *   assistant  { id, role:'assistant', text, streaming, stopped, result, resultRaw, error }
 *   确认卡片    { id, role:'assistant', toolCall:{ tool_name, args, status, error, result } }
 *
 * 会话延迟创建（后端契约）：done 回传的 conversation_id 才落本地；404+10002 视为
 * 会话失效——清 id，重试即开新对话。断连不落库、重试即整轮重发，故中止只做本地标记。
 */
import { defineStore } from 'pinia'
import { reactive, ref } from 'vue'
import { agentChatStream, executeAgentTool, listConversations, listConversationMessages } from '../api/agent'
import { getPracticeMeta } from '../api/practice'
import { directionLabelMap } from '../utils/practiceMeta'
import { applyAgentDelta, normalizeHistory, parseAgentError } from '../utils/agentStream'
import { useOverviewStore } from './overview'

const CONV_KEY = 'jobpilot_agent_conv'

export const useAgentStore = defineStore('agent', () => {
  const open = ref(false)
  const messages = ref([])
  const conversationId = ref(Number(localStorage.getItem(CONV_KEY)) || null)
  const streaming = ref(false)
  const restoring = ref(false)
  const restoreError = ref('')
  const historyOpen = ref(false)
  const history = reactive({ items: [], total: 0, page: 0, loading: false })
  const directionLabels = ref(null)

  let stream = null
  let pendingAssistant = null
  let seq = 0
  let metaPromise = null
  // 会话加载代际：newSession / reset 使其 +1，迟到的加载响应据此丢弃
  // （否则「切换会话 / 恢复」进行中点了新对话，旧响应会把已清空的视图填回）
  let loadGen = 0

  function persistConv(id) {
    conversationId.value = id || null
    if (id) localStorage.setItem(CONV_KEY, String(id))
    else localStorage.removeItem(CONV_KEY)
  }

  function toggle() {
    open.value = !open.value
    if (open.value) {
      historyOpen.value = false
      if (!messages.value.length && conversationId.value) restore()
    }
  }

  function closePanel() {
    open.value = false
    historyOpen.value = false
  }

  /** 恢复当前会话（打开浮窗时自动触发；失败：404 静默开新对话、网络错显示重试）。 */
  async function restore() {
    if (!conversationId.value) return
    const gen = ++loadGen
    restoring.value = true
    restoreError.value = ''
    try {
      const items = await listConversationMessages(conversationId.value)
      if (gen !== loadGen) return
      messages.value = normalizeHistory(items, () => ++seq)
    } catch (e) {
      if (gen !== loadGen) return
      if (e?.code === 10002) persistConv(null)
      else restoreError.value = e?.message || '对话加载失败'
    } finally {
      if (gen === loadGen) restoring.value = false
    }
  }

  /** 发送一条消息（主流程）。 */
  function send(text) {
    const content = String(text || '').trim()
    if (!content || streaming.value) return
    restoreError.value = ''
    messages.value.push({ id: ++seq, role: 'user', text: content })

    const assistant = reactive({
      id: ++seq, role: 'assistant', text: '', streaming: true, stopped: false,
      result: null, resultRaw: '', error: null, toolCall: null
    })
    messages.value.push(assistant)
    pendingAssistant = assistant
    streaming.value = true

    const payload = { message: content }
    if (conversationId.value) payload.conversation_id = conversationId.value

    stream = agentChatStream(payload, {
      onDelta: (d) => applyAgentDelta(assistant, d),
      onToolCall: (d) => {
        messages.value.push({
          id: ++seq, role: 'assistant',
          toolCall: { tool_name: d?.tool_name, args: d?.args || {}, status: 'pending', error: '', result: null }
        })
      },
      onDone: (d) => {
        if (d?.conversation_id) persistConv(d.conversation_id)
        finish()
      },
      onError: (e) => {
        if (e?.code === 10002) persistConv(null) // 会话失效：重试即开新对话
        assistant.error = parseAgentError(e)
        finish()
      }
    })
  }

  function finish() {
    if (pendingAssistant) {
      pendingAssistant.streaming = false
      pendingAssistant = null
    }
    streaming.value = false
    stream = null
  }

  /** 中止：不算错误（sse.js 对 AbortError 静默）；后端不落库，刷新后该轮消失。 */
  function abort() {
    stream?.abort()
    if (pendingAssistant) {
      pendingAssistant.stopped = true
      pendingAssistant.streaming = false
      pendingAssistant = null
    }
    streaming.value = false
    stream = null
  }

  /** 重发上一条用户消息：移除该轮（用户消息 → 错误块之间）后整轮重发。 */
  function retryStream(assistantId) {
    const idx = messages.value.findIndex((m) => m.id === assistantId)
    if (idx < 0 || streaming.value) return
    let userIdx = -1
    for (let i = idx - 1; i >= 0; i--) {
      if (messages.value[i].role === 'user') { userIdx = i; break }
    }
    if (userIdx < 0) return
    const text = messages.value[userIdx].text
    messages.value.splice(userIdx, idx - userIdx + 1)
    send(text)
  }

  /** 确认卡片（乐观更新）：执行写操作，成功后同步概览（侧栏「今日待办」与统计）。 */
  async function confirmTool(messageId) {
    const tc = messages.value.find((m) => m.id === messageId)?.toolCall
    if (!tc || (tc.status !== 'pending' && tc.status !== 'failed')) return
    tc.status = 'executing'
    tc.error = ''
    try {
      tc.result = await executeAgentTool(tc.tool_name, tc.args)
      tc.status = 'done'
      useOverviewStore().fetch(true)
    } catch (e) {
      tc.status = 'failed'
      tc.error = e?.message || '执行失败，请重试'
    }
  }

  function cancelTool(messageId) {
    const tc = messages.value.find((m) => m.id === messageId)?.toolCall
    if (tc && tc.status === 'pending') tc.status = 'cancelled'
  }

  /** 历史会话列表：首次打开拉第一页，底部「加载更多」续页。 */
  async function loadHistory(reset = false) {
    if (reset) { history.items = []; history.page = 0; history.total = 0 }
    if (history.loading) return
    if (history.page && history.items.length >= history.total) return
    history.loading = true
    try {
      const data = await listConversations({ page: history.page + 1, page_size: 20 })
      history.items.push(...(data?.items || []))
      history.total = data?.total || 0
      history.page += 1
    } catch {
      // 加载失败保留已有列表，不打断面板
    } finally {
      history.loading = false
    }
  }

  function toggleHistory() {
    historyOpen.value = !historyOpen.value
    if (historyOpen.value && !history.items.length) loadHistory(true)
  }

  /** 切换到某历史会话（可续聊）。 */
  async function loadSession(id) {
    if (streaming.value) return
    const gen = ++loadGen
    historyOpen.value = false
    restoring.value = true
    restoreError.value = ''
    try {
      const items = await listConversationMessages(id)
      if (gen !== loadGen) return
      messages.value = normalizeHistory(items, () => ++seq)
      persistConv(id)
    } catch (e) {
      if (gen !== loadGen) return
      restoreError.value = e?.message || '对话加载失败'
    } finally {
      if (gen === loadGen) restoring.value = false
    }
  }

  function newSession() {
    loadGen++ // 使进行中的会话加载失效（迟到的响应不得回填已清空的视图）
    messages.value = []
    persistConv(null)
    historyOpen.value = false
    restoreError.value = ''
    restoring.value = false
  }

  /** 方向枚举 → 中文（结果卡片用）；拉一次缓存，失败由调用方兜底显示枚举原值。 */
  async function ensureDirections() {
    if (directionLabels.value) return
    if (!metaPromise) {
      metaPromise = getPracticeMeta()
        .then((meta) => { directionLabels.value = directionLabelMap(meta) })
        .catch(() => {})
    }
    await metaPromise
  }

  /** 登出清理（系统设计 §4.2 账号一致性：不留上一账号的对话与本地会话 id）。 */
  function reset() {
    stream?.abort()
    loadGen++ // 进行中的加载失效（换账号后旧响应不得回填）
    stream = null
    pendingAssistant = null
    streaming.value = false
    restoring.value = false
    restoreError.value = ''
    open.value = false
    historyOpen.value = false
    messages.value = []
    conversationId.value = null
    localStorage.removeItem(CONV_KEY)
    history.items = []
    history.total = 0
    history.page = 0
    history.loading = false
    directionLabels.value = null
    metaPromise = null
  }

  return {
    open, messages, conversationId, streaming, restoring, restoreError, historyOpen, history, directionLabels,
    toggle, closePanel, restore, send, abort, retryStream, confirmTool, cancelTool,
    loadHistory, toggleHistory, loadSession, newSession, ensureDirections, reset
  }
})
