<script setup>
/**
 * 全局 Agent 悬浮球（FR-011 / 步骤 19）：任意页面右下角唤起对话浮窗。
 *
 * 挂载于 App.vue 的默认壳内——blank 布局（登录/注册/入场动画）天然不渲染。
 * 浮窗打开时点球隐藏；跳转（结果卡片按钮）由卡片自行 closePanel 后 push。
 */
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { Clock, Minus, Plus, Promotion, Service, VideoPause } from '@element-plus/icons-vue'
import AgentMessages from './AgentMessages.vue'
import AgentHistoryPanel from './AgentHistoryPanel.vue'
import { useAgentStore } from '../../stores/agent'
import { textLength } from '../../utils/text'
import {
  BALL_SIZE,
  PANEL_W,
  ballFromPanel,
  clampBallPos,
  clampPanelRect,
  panelHeight,
  panelRectFromBall
} from '../../utils/agentPosition'

const store = useAgentStore()
const draft = ref('')

// —— 位置：球可拖到任意位置并记忆（localStorage），浮窗从球的位置朝屏幕中心展开 ——
const POS_KEY = 'jobpilot_agent_pos'
const ball = ref(loadBallPos())
const panelPos = ref({ left: 0, top: 0 })

function loadBallPos() {
  const fallback = { x: window.innerWidth - BALL_SIZE - 24, y: window.innerHeight - BALL_SIZE - 24 }
  try {
    const saved = JSON.parse(localStorage.getItem(POS_KEY) || 'null')
    const point = saved && Number.isFinite(saved.x) && Number.isFinite(saved.y) ? saved : fallback
    return clampBallPos(point.x, point.y, window.innerWidth, window.innerHeight)
  } catch {
    return clampBallPos(fallback.x, fallback.y, window.innerWidth, window.innerHeight)
  }
}

function saveBallPos() {
  localStorage.setItem(POS_KEY, JSON.stringify(ball.value))
}

// 打开浮窗时，面板从球的位置展开（resize 时同样重算，见 onResize）
watch(
  () => store.open,
  (open) => {
    if (open) {
      panelPos.value = panelRectFromBall(
        ball.value, window.innerWidth, window.innerHeight, PANEL_W, panelHeight(window.innerHeight)
      )
    }
  }
)

// —— 悬浮球：拖动改位置（位移 > 4px 判为拖动），未拖动视为点击（开/关浮窗） ——
let ballDrag = null
function onBallDown(e) {
  if (e.button !== 0) return
  ballDrag = { sx: e.clientX, sy: e.clientY, ox: ball.value.x, oy: ball.value.y, moved: false }
  window.addEventListener('mousemove', onBallMove)
  window.addEventListener('mouseup', onBallUp)
}
function onBallMove(e) {
  if (!ballDrag) return
  const dx = e.clientX - ballDrag.sx
  const dy = e.clientY - ballDrag.sy
  if (!ballDrag.moved && Math.abs(dx) + Math.abs(dy) > 4) ballDrag.moved = true
  if (ballDrag.moved) {
    ball.value = clampBallPos(ballDrag.ox + dx, ballDrag.oy + dy, window.innerWidth, window.innerHeight)
  }
}
function onBallUp() {
  window.removeEventListener('mousemove', onBallMove)
  window.removeEventListener('mouseup', onBallUp)
  if (!ballDrag) return
  if (ballDrag.moved) saveBallPos()
  else store.toggle() // 未拖动 = 点击
  ballDrag = null
}

// —— 浮窗头部：按住空白处拖动整窗（面板跟手），松手换算回球锚点（两套交互共用一个位置） ——
let headDrag = null
function onHeadDown(e) {
  if (e.button !== 0 || e.target.closest('button')) return // 头部按钮不触发拖动
  headDrag = { sx: e.clientX, sy: e.clientY, ol: panelPos.value.left, ot: panelPos.value.top, moved: false }
  window.addEventListener('mousemove', onHeadMove)
  window.addEventListener('mouseup', onHeadUp)
}
function onHeadMove(e) {
  if (!headDrag) return
  const dx = e.clientX - headDrag.sx
  const dy = e.clientY - headDrag.sy
  if (!headDrag.moved && Math.abs(dx) + Math.abs(dy) > 4) headDrag.moved = true
  if (headDrag.moved) {
    const vh = window.innerHeight
    panelPos.value = clampPanelRect(
      headDrag.ol + dx, headDrag.ot + dy, window.innerWidth, vh, PANEL_W, panelHeight(vh)
    )
  }
}
function onHeadUp() {
  window.removeEventListener('mousemove', onHeadMove)
  window.removeEventListener('mouseup', onHeadUp)
  if (headDrag?.moved) {
    ball.value = ballFromPanel(
      panelPos.value, window.innerWidth, window.innerHeight, PANEL_W, panelHeight(window.innerHeight)
    )
    saveBallPos()
  }
  headDrag = null
}

function onResize() {
  const vw = window.innerWidth
  const vh = window.innerHeight
  ball.value = clampBallPos(ball.value.x, ball.value.y, vw, vh)
  // 不 saveBallPos：resize 的钳制是临时视口的结果，不该覆盖用户拖出来的偏好位置
  // （否则「临时小窗口 → 换回大屏」后球会停在钳后的位置，而不是用户拖到的位置）
  if (store.open) {
    panelPos.value = panelRectFromBall(ball.value, vw, vh, PANEL_W, panelHeight(vh))
  }
}

onMounted(() => window.addEventListener('resize', onResize))
onUnmounted(() => {
  window.removeEventListener('resize', onResize)
  window.removeEventListener('mousemove', onBallMove)
  window.removeEventListener('mouseup', onBallUp)
  window.removeEventListener('mousemove', onHeadMove)
  window.removeEventListener('mouseup', onHeadUp)
})

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
  <!-- 悬浮球（浮窗打开时让位）：可拖到任意位置（未拖动 = 点击开/关浮窗） -->
  <button
    v-show="!store.open"
    class="agent-ball"
    :style="{ left: ball.x + 'px', top: ball.y + 'px' }"
    title="AI 助手（可拖动）"
    @mousedown.prevent="onBallDown"
  >
    <el-icon :size="26"><Service /></el-icon>
  </button>

  <!-- 对话浮窗（从球的位置展开；按住头部空白处可拖动整窗） -->
  <section
    v-if="store.open"
    class="agent-panel"
    :style="{ left: panelPos.left + 'px', top: panelPos.top + 'px' }"
  >
    <header class="agent-panel__head" title="按住空白处可拖动浮窗" @mousedown.prevent="onHeadDown">
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
  cursor: grab;
  box-shadow: 0 8px 22px rgba(47, 91, 158, 0.36);
  transition: transform 0.16s ease, box-shadow 0.16s ease;
}
.agent-ball:hover {
  transform: scale(1.06);
  box-shadow: 0 10px 26px rgba(47, 91, 158, 0.46);
}
.agent-ball:active {
  transform: scale(0.97);
  cursor: grabbing;
}
.agent-panel {
  position: fixed;
  /* 位置由 :style 驱动（从左/上定位，跟随球锚点展开） */
  z-index: 1800;
  /* border-box：宽度含 1px 边框——位置计算（agentPosition.js）按 400×620 计量，两处必须一致 */
  box-sizing: border-box;
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
  /* 按住空白处可拖动整窗（按钮除外，见 onHeadDown） */
  cursor: grab;
  user-select: none;
}
.agent-panel__head:active {
  cursor: grabbing;
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
