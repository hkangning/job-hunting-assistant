<script setup>
/**
 * 训练中：题干 + 轮次进度 + 限时倒计时 + 逐轮对话流 + 作答区。
 *
 * 倒计时绑定「作答框可用」期间：出题后起算、提交时停止；流式输出中暂停。
 * 结束时机不在这里判断——一律由父级依据 `done.extra.should_finish` 决定。
 */
import { computed, nextTick, onUnmounted, ref, watch } from 'vue'
import { ArrowDown, ArrowUp, Back } from '@element-plus/icons-vue'
import PracticeTurn from './PracticeTurn.vue'

const props = defineProps({
  session: { type: Object, required: true },
  turns: { type: Array, default: () => [] },
  meta: { type: Object, default: null },
  streaming: { type: Boolean, default: false }
})
const emit = defineEmits(['submit', 'hint', 'end', 'exit', 'timeout', 'retry'])

const answer = ref('')
const remaining = ref(null)
const showQuestion = ref(true)
let timer = null
let startedAt = 0

const modeMeta = computed(() => (props.meta?.modes || []).find((m) => m.value === props.session.mode) || null)
const faces = computed(() => props.meta?.faces || [])

const maxRounds = computed(() => modeMeta.value?.max_rounds || 0)
/** 当前是第几轮：已完成的轮次 + 1，封顶不超过模式上限（提示轮不虚增序号）。 */
const roundNo = computed(() =>
  maxRounds.value ? Math.min(props.turns.length + 1, maxRounds.value) : props.turns.length + 1
)

const isCoach = computed(() => props.session.mode === 'COACH')
const canSubmit = computed(() => !props.streaming)

/**
 * 作答计时的起点：出题后（即上一轮流结束、作答框可用）起算，提交时上报耗时。
 * 不限时也记起点——`elapsed_ms` 在非限时模式下同样上报，供复盘用。
 */
function beginAnswer() {
  stopTimer()
  startedAt = Date.now()
  if (!props.session.time_limit) {
    remaining.value = null
    return
  }
  remaining.value = props.session.time_limit
  timer = setInterval(() => {
    remaining.value -= 1
    if (remaining.value <= 0) {
      stopTimer()
      const elapsedMs = Date.now() - startedAt
      answer.value = '' // 超时自动提交，输入框清空
      emit('timeout', { elapsedMs })
    }
  }, 1000)
}

function stopTimer() {
  if (timer !== null) {
    clearInterval(timer)
    timer = null
  }
}

/** 作答框可用 = 非流式：出题后开始计时，流式输出中暂停。 */
watch(
  () => props.streaming,
  (busy) => {
    if (busy) stopTimer()
    else beginAnswer()
  },
  { immediate: true }
)

const elapsed = () => (startedAt ? Date.now() - startedAt : 0)

function submit() {
  if (!canSubmit.value) return
  stopTimer()
  emit('submit', { userInput: answer.value, timedOut: false, elapsedMs: elapsed() })
  answer.value = ''
}

const urgent = computed(() => remaining.value !== null && remaining.value <= 10)

const answerBox = ref(null)

/**
 * 新一轮开始时把作答区带进视野——轮次一多，对话流会把作答框顶到屏幕外，
 * 每次都要手动滚下去。用 nearest：已经在视野内就不动，避免无谓的跳动。
 */
watch(
  () => props.turns.length,
  async () => {
    await nextTick()
    answerBox.value?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }
)

onUnmounted(stopTimer)
</script>

<template>
  <div class="runner">
    <section class="runner__card runner__card--question">
      <header class="runner__question-head">
        <span class="runner__meta">
          <span class="runner__mode">{{ modeMeta ? modeMeta.label : session.mode }}</span>
          <span>第 {{ roundNo }}<template v-if="maxRounds">/{{ maxRounds }}</template> 轮</span>
        </span>
        <div class="runner__question-right">
          <span
            v-if="remaining !== null"
            class="runner__timer"
            :class="{ 'runner__timer--urgent': urgent }"
          >
            {{ remaining }}s
          </span>
          <el-button link @click="showQuestion = !showQuestion">
            {{ showQuestion ? '收起题目' : '查看题目' }}
            <el-icon class="el-icon--right">
              <ArrowUp v-if="showQuestion" />
              <ArrowDown v-else />
            </el-icon>
          </el-button>
        </div>
      </header>
      <p v-if="showQuestion" class="runner__question-text">{{ session.question.content }}</p>
      <span
        v-if="session.question.mastery !== undefined && session.question.mastery !== null"
        class="runner__mastery"
      >
        本题所属领域当前掌握度 {{ session.question.mastery }}
      </span>
    </section>

    <div class="runner__stream">
      <PracticeTurn
        v-for="(turn, index) in turns"
        :key="index"
        :turn="turn"
        :faces="faces"
        :qtype="session.question.qtype"
        @retry="emit('retry', index)"
      />
    </div>

    <section ref="answerBox" class="runner__card runner__card--answer">
      <el-input
        v-model="answer"
        type="textarea"
        :rows="4"
        :disabled="streaming"
        :placeholder="isCoach ? '作答，卡住了可以点「要提示」' : '写下你的回答'"
      />
      <div class="runner__actions">
        <el-button v-if="isCoach" :disabled="streaming" @click="emit('hint')">要提示</el-button>
        <el-button
          :icon="Back"
          class="runner__quit"
          :disabled="streaming"
          title="退出后本场保留在训练记录里，可随时结算"
          @click="emit('exit')"
        >
          退出
        </el-button>
        <div class="runner__actions-main">
          <el-button :disabled="streaming" @click="emit('end')">结束本场</el-button>
          <!-- 不因空作答禁用（答不上来也是有效作答，后端据此记断点），文案恒定不随之变化 -->
          <el-button type="primary" :disabled="!canSubmit" @click="submit">提交</el-button>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.runner__card {
  background: var(--c-card);
  border: 1px solid var(--c-border);
  border-radius: var(--r-card);
  box-shadow: 0 1px 2px rgba(42, 39, 64, 0.05);
  padding: var(--card-padding);
}

.runner__question-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
}
.runner__meta {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: var(--fs-sm);
  color: var(--c-text-2);
}
.runner__mode {
  padding: 2px 9px;
  font-size: var(--fs-xs);
  color: var(--m-practice);
  background: color-mix(in srgb, var(--m-practice) 12%, var(--c-card));
  border-radius: var(--r-mark);
}
.runner__question-right {
  display: flex;
  align-items: center;
  gap: 10px;
}
/* 倒计时是「事实」不是「评价」，用中性色；只剩 10 秒才转红告警 */
.runner__timer {
  font-size: var(--fs-title);
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  color: var(--c-text);
}
.runner__timer--urgent {
  color: var(--el-color-danger);
}

.runner__question-text {
  margin: 0;
  max-height: 140px;
  overflow-y: auto;
  font-size: var(--fs-body);
  line-height: 1.7;
  color: var(--c-text);
  white-space: pre-wrap;
  word-break: break-word;
}
.runner__mastery {
  display: inline-block;
  margin-top: 6px;
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}

.runner__stream {
  margin: var(--card-gap) 0;
}

.runner__actions {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 10px;
}
/* 「退出」是弱操作，推到最左侧与主操作拉开距离，避免误点 */
.runner__quit {
  margin-right: auto;
}
.runner__actions-main {
  display: flex;
  gap: 8px;
}
</style>
