<script setup>
/**
 * 浮窗消息区：气泡 + 流式 + 卡片分发 + 错误块 + 空态。
 *
 * 滚动吸附与 InterviewChat 同款：MutationObserver 跟随内容增长，用户手动上滚即脱离，
 * 回到底部附近重新吸附（打字机逐字增长也跟随）。
 */
import { onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Service } from '@element-plus/icons-vue'
import StreamText from '../StreamText.vue'
import AgentConfirmCard from './AgentConfirmCard.vue'
import AgentResultCard from './AgentResultCard.vue'
import { useAgentStore } from '../../stores/agent'

const store = useAgentStore()
const router = useRouter()

const scroller = ref(null)
let stick = true
let observer = null

function onScroll() {
  const el = scroller.value
  if (!el) return
  stick = el.scrollHeight - el.scrollTop - el.clientHeight < 40
}

function scrollToBottom() {
  const el = scroller.value
  if (el) el.scrollTop = el.scrollHeight
}

onMounted(() => {
  observer = new MutationObserver(() => {
    if (stick) scrollToBottom()
  })
  observer.observe(scroller.value, { childList: true, subtree: true, characterData: true })
  scrollToBottom()
})

onUnmounted(() => observer?.disconnect())

function goConfig() {
  store.closePanel()
  router.push('/ai-config')
}
</script>

<template>
  <div ref="scroller" class="agent-msgs" @scroll="onScroll">
    <div v-if="store.restoring" class="agent-msgs__hint">正在加载对话…</div>

    <div v-else-if="store.restoreError" class="agent-msgs__hint">
      {{ store.restoreError }}
      <el-button link type="primary" @click="store.restore()">重试</el-button>
    </div>

    <div v-else-if="!store.messages.length" class="agent-empty">
      <el-icon :size="34" class="agent-empty__icon"><Service /></el-icon>
      <p class="agent-empty__title">你好，我是求职助手</p>
      <p class="agent-empty__desc">记投递、查进度、出题、找面经——说一句话就能办</p>
    </div>

    <template v-else>
      <div v-for="m in store.messages" :key="m.id" class="agent-msg" :class="`agent-msg--${m.role}`">
        <div v-if="m.role === 'user'" class="agent-bubble agent-bubble--user">{{ m.text }}</div>

        <template v-else>
          <div v-if="m.text" class="agent-bubble agent-bubble--bot">
            <StreamText :text="m.text" :streaming="m.streaming" />
          </div>
          <p v-if="m.stopped" class="agent-msg__stopped">已停止</p>

          <div v-if="m.error" class="agent-error">
            <span class="agent-error__text">{{ m.error.message }}</span>
            <div class="agent-error__ops">
              <el-button v-if="m.error.needConfig" link type="primary" @click="goConfig">去 AI 配置</el-button>
              <el-button link type="primary" @click="store.retryStream(m.id)">重试</el-button>
            </div>
          </div>

          <AgentConfirmCard v-if="m.toolCall" :message="m" />
          <AgentResultCard v-if="m.result" :message="m" />
        </template>
      </div>
    </template>
  </div>
</template>

<style scoped>
.agent-msgs {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 14px 14px 10px;
  background: var(--c-bg);
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.agent-msgs__hint {
  margin-top: 40px;
  text-align: center;
  color: var(--c-text-2);
  font-size: var(--fs-sm);
}
.agent-empty {
  margin: auto;
  text-align: center;
  padding: 20px 0;
}
.agent-empty__icon {
  color: color-mix(in srgb, var(--brand) 30%, var(--c-card));
}
.agent-empty__title {
  margin: 10px 0 4px;
  font-size: var(--fs-title);
  font-weight: 600;
  color: var(--c-text);
}
.agent-empty__desc {
  margin: 0;
  font-size: var(--fs-sm);
  color: var(--c-text-2);
}
.agent-msg {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.agent-msg--user {
  align-items: flex-end;
}
.agent-msg--assistant {
  align-items: flex-start;
}
.agent-bubble {
  max-width: 85%;
  padding: 9px 12px;
  font-size: var(--fs-body);
  line-height: 1.65;
  white-space: pre-wrap;
  word-break: break-word;
}
.agent-bubble--user {
  background: var(--brand);
  color: #fff;
  border-radius: 10px 10px 2px 10px;
}
.agent-bubble--bot {
  background: var(--c-card);
  color: var(--c-text);
  border: 1px solid var(--c-border);
  border-radius: 10px 10px 10px 2px;
}
.agent-msg__stopped {
  margin: 0;
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}
.agent-error {
  width: 100%;
  padding: 9px 12px;
  border: 1px solid color-mix(in srgb, var(--el-color-danger) 35%, var(--c-border));
  background: color-mix(in srgb, var(--el-color-danger) 6%, var(--c-card));
  border-radius: var(--r-card);
  font-size: var(--fs-sm);
}
.agent-error__text {
  color: var(--el-color-danger);
  line-height: 1.6;
}
.agent-error__ops {
  display: flex;
  justify-content: flex-end;
  gap: 4px;
  margin-top: 4px;
}
</style>
