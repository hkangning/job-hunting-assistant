<script setup>
/**
 * 全局 Agent 悬浮球（FR-011 / 步骤 19）：任意页面右下角唤起对话浮窗。
 *
 * 挂载于 App.vue 的默认壳内——blank 布局（登录/注册/入场动画）天然不渲染。
 * 浮窗打开时点球隐藏；跳转（结果卡片按钮）由卡片自行 closePanel 后 push。
 */
import { computed, ref } from 'vue'
import { Clock, Minus, Plus, Promotion, Service, VideoPause } from '@element-plus/icons-vue'
import AgentMessages from './AgentMessages.vue'
import AgentHistoryPanel from './AgentHistoryPanel.vue'
import { useAgentStore } from '../../stores/agent'
import { textLength } from '../../utils/text'

const store = useAgentStore()
const draft = ref('')

// 预设快捷指令（SRS §3.8 原文四项）
const CHIPS = ['记一笔投递', '出三道 Java 题', '今天有什么事', '抽两道错题']

const canSend = computed(
  () => !!draft.value.trim() && !store.streaming && textLength(draft.value) <= 2000
)

function sendChip(text) {
  if (store.streaming) return
  store.send(text)
}

function send() {
  if (!canSend.value) return
  const text = draft.value
  draft.value = ''
  store.send(text)
}

function onKeydown(event) {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    send()
  }
}
</script>

<template>
  <!-- 悬浮球（浮窗打开时让位） -->
  <button v-show="!store.open" class="agent-ball" title="AI 助手" @click="store.toggle()">
    <el-icon :size="26"><Service /></el-icon>
  </button>

  <!-- 对话浮窗 -->
  <section v-if="store.open" class="agent-panel">
    <header class="agent-panel__head">
      <el-icon class="agent-panel__brand"><Service /></el-icon>
      <span class="agent-panel__title">AI 助手</span>
      <div class="agent-panel__ops">
        <el-button link class="agent-panel__op" :icon="Clock" title="历史对话" @click="store.toggleHistory()" />
        <el-button link class="agent-panel__op" :icon="Plus" title="新对话" @click="store.newSession()" />
        <el-button link class="agent-panel__op" :icon="Minus" title="收起" @click="store.closePanel()" />
      </div>
    </header>

    <AgentHistoryPanel v-if="store.historyOpen" />

    <template v-else>
      <AgentMessages />

      <footer class="agent-panel__foot">
        <div class="agent-chips">
          <button
            v-for="chip in CHIPS"
            :key="chip"
            class="agent-chip"
            :disabled="store.streaming"
            @click="sendChip(chip)"
          >{{ chip }}</button>
        </div>
        <div class="agent-input">
          <el-input
            v-model="draft"
            type="textarea"
            :autosize="{ minRows: 1, maxRows: 4 }"
            resize="none"
            maxlength="2000"
            placeholder="说一句话办事，比如“记一笔投递”…"
            @keydown="onKeydown"
          />
          <el-button
            v-if="!store.streaming"
            class="agent-input__btn"
            type="primary"
            :icon="Promotion"
            :disabled="!canSend"
            circle
            title="发送"
            @click="send"
          />
          <el-button
            v-else
            class="agent-input__btn"
            type="primary"
            :icon="VideoPause"
            circle
            title="停止"
            @click="store.abort()"
          />
        </div>
      </footer>
    </template>
  </section>
</template>

<style scoped>
.agent-ball {
  position: fixed;
  right: 24px;
  bottom: 24px;
  z-index: 1800;
  width: 58px;
  height: 58px;
  border: none;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--brand);
  color: #fff;
  cursor: pointer;
  box-shadow: 0 8px 22px rgba(47, 91, 158, 0.36);
  transition: transform 0.16s ease, box-shadow 0.16s ease;
}
.agent-ball:hover {
  transform: scale(1.06);
  box-shadow: 0 10px 26px rgba(47, 91, 158, 0.46);
}
.agent-ball:active {
  transform: scale(0.97);
}
.agent-panel {
  position: fixed;
  right: 24px;
  bottom: 24px;
  z-index: 1800;
  width: 400px;
  height: min(620px, calc(100vh - 96px));
  display: flex;
  flex-direction: column;
  border: 1px solid var(--c-border);
  border-radius: var(--r-float);
  background: var(--c-card);
  box-shadow: 0 12px 40px rgba(42, 39, 64, 0.18);
  overflow: hidden;
  transform-origin: bottom right;
  animation: agent-in 0.18s ease-out;
}
@keyframes agent-in {
  from {
    opacity: 0;
    transform: translateY(8px) scale(0.97);
  }
}
.agent-panel__head {
  flex: none;
  display: flex;
  align-items: center;
  gap: 8px;
  height: 56px;
  padding: 0 10px 0 14px;
  border-bottom: 1px solid var(--c-divider);
  /* 头部用浅品牌底：与消息区（浅灰）和输入区（白）拉开层次，浮窗更像「产品」而非灰白拼盘 */
  background: color-mix(in srgb, var(--brand) 9%, var(--c-card));
}
.agent-panel__brand {
  color: var(--brand);
  font-size: 19px;
}
.agent-panel__title {
  font-size: var(--fs-title);
  font-weight: 600;
  color: var(--c-text);
}
.agent-panel__ops {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 2px;
}
/* 头部图标按钮：36×36 热区 + 18px 图标 + 悬停浅底——原为裸图标（约 20px 宽），点不准 */
.agent-panel__op.el-button {
  width: 36px;
  padding: 0;
  font-size: 18px;
  color: var(--c-text-2);
  border-radius: var(--r-menu);
}
.agent-panel__op.el-button:hover {
  background: color-mix(in srgb, var(--brand) 12%, var(--c-card));
  color: var(--brand);
}
.agent-panel__foot {
  flex: none;
  padding: 10px 12px 12px;
  border-top: 1px solid var(--c-divider);
  background: var(--c-card);
}
.agent-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 10px;
}
.agent-chip {
  padding: 6px 12px;
  border: 1px solid color-mix(in srgb, var(--brand) 30%, var(--c-border));
  border-radius: var(--r-control);
  background: color-mix(in srgb, var(--brand) 6%, var(--c-card));
  color: var(--brand);
  font-size: var(--fs-sm);
  cursor: pointer;
  transition: background 0.15s ease, border-color 0.15s ease;
}
.agent-chip:hover:not(:disabled) {
  background: color-mix(in srgb, var(--brand) 12%, var(--c-card));
  border-color: color-mix(in srgb, var(--brand) 55%, var(--c-border));
}
.agent-chip:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.agent-input {
  display: flex;
  align-items: flex-end;
  gap: 8px;
}
.agent-input :deep(.el-textarea__inner) {
  padding: 10px 12px;
  font-size: var(--fs-body);
}
/* 发送 / 停止按钮：40×40 热区 + 加大图标（原为默认档 32px 宽，浮窗内偏小）。
   circle 按钮的宽度不跟 --el-button-size（由 padding + 内容决定），需显式给宽。 */
.agent-input__btn {
  flex: none;
  --el-button-size: 40px;
  width: 40px;
  padding: 0;
  font-size: 17px;
}
</style>
