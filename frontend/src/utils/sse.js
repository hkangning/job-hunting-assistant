/**
 * SSE 流式客户端（系统设计 5.1 / 接口文档 1.4）。
 *
 * `EventSource` 不支持 POST，故一律用 `fetch` + `ReadableStream` 手工解析；
 * 本模块是后续四条 AI 链路（JD 分析 / 陪练点评 / 模拟面试 / 面经复盘）的共同出口。
 *
 * 用法：
 *   const { abort } = streamSSE('/stream/demo', { message }, {
 *     onStart: (d) => (status.value = d.message),
 *     onDelta: (d) => (buffer.value += d.text),
 *     onDone:  (d) => (recordId.value = d.record_id),
 *     onError: (e) => (errMsg.value = e.message)
 *   })
 */
import { ElMessage } from 'element-plus'
import router from '../router'
import { useUserStore } from '../stores/user'

const BASE = '/api/v1'

/**
 * 发起一次流式请求。
 *
 * @param {string} url 以 / 开头的接口路径（本函数自行拼 /api/v1 前缀）
 * @param {object} body JSON 请求体
 * @param {object} [handlers] { onStart, onDelta, onToolCall, onDone, onError }，均可选
 * @param {object} [options] { signal } 外部中止信号（如组件卸载时联动）
 * @returns {{ abort: () => void }}
 */
export function streamSSE(url, body, handlers = {}, options = {}) {
  const { onStart, onDelta, onToolCall, onDone, onError } = handlers
  const controller = new AbortController()
  let aborted = false

  if (options.signal) {
    if (options.signal.aborted) controller.abort()
    else options.signal.addEventListener('abort', () => controller.abort(), { once: true })
  }

  /** 分派单个事件；返回 false 表示停止后续解析（error 事件即终止，接口文档 1.4）。 */
  function dispatch({ event, data }) {
    if (event === 'start') onStart?.(data)
    else if (event === 'delta') onDelta?.(data)
    else if (event === 'tool_call') onToolCall?.(data)
    else if (event === 'done') onDone?.(data)
    else if (event === 'error') {
      onError?.(data)
      return false
    }
    return true
  }

  /** 主动中止不算错误：AbortError 一律静默，不回吐给调用方。 */
  function reportError(err, fallback) {
    if (aborted || err?.name === 'AbortError') return
    onError?.({ code: undefined, message: fallback })
  }

  /** 登录态失效的处置与 request.js 拦截器同源（80001 未登录 / 80002 已过期）。 */
  function handleAuthExpired() {
    useUserStore().reset()
    ElMessage.error({ message: '登录状态已失效，请重新登录', grouping: true })
    router.replace('/login')
  }

  async function run() {
    let response
    try {
      response = await fetch(BASE + url, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${useUserStore().token}`
        },
        body: JSON.stringify(body),
        signal: controller.signal
      })
    } catch (err) {
      reportError(err, '网络异常，请检查后端服务是否已启动')
      return
    }

    if (!response.ok) {
      let code
      let message = `请求失败（HTTP ${response.status}）`
      try {
        const errBody = await response.json()
        code = errBody.code
        message = errBody.message || message
      } catch {
        // 响应体非 JSON：保留默认文案
      }
      if (aborted) return
      if (code === 80001 || code === 80002) return handleAuthExpired()
      onError?.({ code, message })
      return
    }

    // 收到非 SSE 响应：多半是 mock 层或反向代理接管了请求
    const contentType = response.headers.get('content-type') || ''
    if (!contentType.includes('text/event-stream')) {
      onError?.({
        code: undefined,
        message: '响应不是流式格式：请关闭 mock（VITE_USE_MOCK=false）并确认后端已启动'
      })
      return
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    try {
      for (;;) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })

        // 事件块可能被 TCP 拆到多个 chunk，只能在分隔空行处切分
        let idx
        while ((idx = buffer.indexOf('\n\n')) !== -1) {
          const parsed = parseEvent(buffer.slice(0, idx))
          buffer = buffer.slice(idx + 2)
          if (parsed && !dispatch(parsed)) return
        }
      }
    } catch (err) {
      reportError(err, '流式连接中断，请重试')
    }
  }

  run()

  return {
    abort() {
      aborted = true
      controller.abort()
    }
  }
}

/** 解析单个事件块，取出 `event:` 行与 `data:` 行（接口文档 1.4 的报文格式）。 */
function parseEvent(block) {
  let event = 'message'
  const dataLines = []
  for (const line of block.split('\n')) {
    if (line.startsWith('event:')) event = line.slice(6).trim()
    else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim())
  }
  if (!dataLines.length) return null
  try {
    return { event, data: JSON.parse(dataLines.join('\n')) }
  } catch {
    return null // 非法 JSON：跳过该事件，不影响后续
  }
}
