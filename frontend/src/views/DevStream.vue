<script setup>
/**
 * 流式协议调试页（步骤 11，路由 /dev/stream）——**不进侧边导航**，仅供联调与回归。
 *
 * 靶子是后端 POST /stream/demo 自检端点：走真实 LLM 链路但不落库，用于核对事件顺序、
 * 打字机手感与首字延迟。该端点需要鉴权，且**须连真后端**——mock 与代理互斥，开着 mock
 * 时本页收不到 SSE（页面会提示关闭 mock）。
 */
import { ref } from 'vue'
import StreamText from '../components/StreamText.vue'
import { streamSSE } from '../utils/sse'

const message = ref('用三句话介绍一下你自己')
const status = ref('')
const text = ref('')
const errorMsg = ref('')
const extra = ref(null)
const streaming = ref(false)
const logs = ref([])
let controller = null

function stamp() {
  return new Date().toLocaleTimeString('zh-CN', { hour12: false })
}

function log(name, detail) {
  logs.value.push({ time: stamp(), name, detail: JSON.stringify(detail) })
}

function start() {
  if (streaming.value) return
  status.value = ''
  text.value = ''
  errorMsg.value = ''
  extra.value = null
  logs.value = []
  streaming.value = true

  controller = streamSSE(
    '/stream/demo',
    { message: message.value },
    {
      onStart: (d) => {
        status.value = d.message
        log('start', d)
      },
      onDelta: (d) => {
        if (!text.value) log('首个 delta', { text: d.text }) // 只记首条，避免刷屏
        text.value += d.text
      },
      onDone: (d) => {
        streaming.value = false
        extra.value = d.extra
        log('done', d)
      },
      onError: (e) => {
        streaming.value = false
        errorMsg.value = e.message
        log('error', e)
      }
    }
  )
}

function abort() {
  controller?.abort()
  streaming.value = false
  status.value = '已中止（客户端主动断开）'
  log('abort', { note: '主动中止不视为错误' })
}
</script>

<template>
  <div class="dev-stream">
    <h2 class="dev-stream__title">SSE 流式协议调试</h2>
    <p class="dev-stream__hint">
      靶子端点 <code>POST /api/v1/stream/demo</code>——走真实 AI 链路、不落库。须连真后端
      （<code>VITE_USE_MOCK=false</code>），且当前账号已在
      <router-link to="/ai-config">AI 配置页</router-link> 配好供应商。
    </p>

    <div class="dev-stream__row">
      <el-input
        v-model="message"
        maxlength="500"
        show-word-limit
        placeholder="输入一句话，交给 AI 流式回答"
        :disabled="streaming"
      />
      <el-button type="primary" :disabled="streaming || !message.trim()" @click="start">开始</el-button>
      <el-button :disabled="!streaming" @click="abort">中止</el-button>
    </div>

    <el-alert v-if="status" class="dev-stream__status" :title="status" type="info" :closable="false" />
    <el-alert
      v-if="errorMsg"
      class="dev-stream__status"
      :title="errorMsg"
      type="error"
      :closable="false"
    />

    <div class="dev-stream__body">
      <StreamText :text="text" :streaming="streaming" />
    </div>

    <div v-if="extra" class="dev-stream__extra">
      字数 {{ extra.chars }} · 首字 {{ extra.first_token_ms }}ms · 总耗时 {{ extra.elapsed_ms }}ms
    </div>

    <div v-if="logs.length" class="dev-stream__logs">
      <div class="dev-stream__logs-title">事件日志</div>
      <div v-for="(item, i) in logs" :key="i" class="dev-stream__log">
        <span class="dev-stream__log-time">{{ item.time }}</span>
        <span class="dev-stream__log-name">{{ item.name }}</span>
        <span class="dev-stream__log-detail">{{ item.detail }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.dev-stream {
  max-width: 880px;
}
.dev-stream__title {
  margin: 0 0 6px;
  font-size: 18px;
  color: var(--c-text);
}
.dev-stream__hint {
  margin: 0 0 16px;
  font-size: 13px;
  line-height: 1.6;
  color: var(--c-text-2);
}
.dev-stream__row {
  display: flex;
  gap: 8px;
  align-items: center;
}
.dev-stream__status {
  margin-top: 12px;
}
.dev-stream__body {
  min-height: 120px;
  margin-top: 12px;
  padding: 14px 16px;
  border: 1px solid var(--c-border);
  border-radius: var(--r-card);
  background: var(--c-card);
  font-size: 14px;
  line-height: 1.8;
  color: var(--c-text);
}
.dev-stream__extra {
  margin-top: 10px;
  font-size: 13px;
  color: var(--c-text-2);
}
.dev-stream__logs {
  margin-top: 18px;
  font-size: 12px;
  color: var(--c-text-2);
}
.dev-stream__logs-title {
  margin-bottom: 6px;
  font-weight: 600;
}
.dev-stream__log {
  display: flex;
  gap: 10px;
  padding: 3px 0;
  border-bottom: 1px dashed var(--c-divider);
}
.dev-stream__log-time {
  flex-shrink: 0;
  color: var(--c-text-3);
}
.dev-stream__log-name {
  flex-shrink: 0;
  min-width: 76px;
  color: var(--brand);
}
.dev-stream__log-detail {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
