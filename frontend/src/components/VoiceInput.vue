<script setup>
/**
 * 语音作答组件（步骤 24，SRS §3.11 FR-014）。
 *
 * 交互：点「语音作答」开麦 → 连续说话、停顿自动断句（阈值按语速自适应）→ 逐句转写
 * 累积回填（由父组件在 `append` 事件里拼进作答框）→ 可随时停止、编辑后提交。
 *
 * 组件只负责「录音 + 转写结果通知」：文本与 segments 的累积归父组件管；
 * 转写失败不阻塞流程——保留失败句音频，状态行提供「重试」。
 * `reset()` 供父组件在提交 / 跳过作答后清空计数与失败音频（避免跨题残留）。
 */
import { computed, onUnmounted, ref } from 'vue'
import { Microphone, VideoPause } from '@element-plus/icons-vue'
import { createVoiceRecorder } from '../utils/voiceRecorder.js'

defineProps({
  /** 父级流式生成中时禁用开麦 */
  disabled: { type: Boolean, default: false }
})
const emit = defineEmits(['append', 'recording'])

const recording = ref(false)
const elapsed = ref(0)
const level = ref(0)
const pending = ref(0)
const doneCount = ref(0)
const failedCount = ref(0)
const micError = ref('')

let recorder = null
let timer = null
let startedAt = 0

const elapsedText = computed(() => {
  const s = Math.floor(elapsed.value / 1000)
  return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`
})

// 音量竖条（5 根，错峰系数让波形有起伏感）
const bars = computed(() => {
  const base = Math.round(level.value * 12)
  return [0.5, 0.8, 1, 0.85, 0.6].map((f) => 4 + Math.round(base * f))
})

function ensureRecorder() {
  if (recorder) return recorder
  recorder = createVoiceRecorder({
    onLevel: (v) => {
      level.value = v
    },
    onSentence: ({ text, startMs, endMs }) => {
      doneCount.value += 1
      emit('append', { text, startMs, endMs })
    },
    onError: () => {
      failedCount.value = recorder?.failedCount() ?? 0
    },
    onPendingChange: (n) => {
      pending.value = n
    }
  })
  return recorder
}

async function start() {
  micError.value = ''
  try {
    await ensureRecorder().start()
  } catch (err) {
    micError.value = `无法访问麦克风：${err?.message || '请检查浏览器权限'}`
    return
  }
  recording.value = true
  emit('recording', true)
  startedAt = Date.now()
  elapsed.value = 0
  timer = setInterval(() => {
    elapsed.value = Date.now() - startedAt
  }, 200)
}

async function stop() {
  if (!recording.value) return
  recording.value = false
  emit('recording', false)
  clearInterval(timer)
  timer = null
  level.value = 0
  await recorder?.stop()
  failedCount.value = recorder?.failedCount() ?? 0
}

function retry() {
  recorder?.retryFailed()
  failedCount.value = recorder?.failedCount() ?? 0
}

/** 提交 / 跳过作答后由父组件调用：清计数与失败音频（下次开麦重建）。 */
function reset() {
  void stop()
  recorder?.dispose()
  recorder = null
  doneCount.value = 0
  failedCount.value = 0
  pending.value = 0
  micError.value = ''
}

onUnmounted(() => {
  clearInterval(timer)
  recorder?.dispose()
})

defineExpose({ reset })
</script>

<template>
  <div class="voice">
    <el-button v-if="!recording" :icon="Microphone" :disabled="disabled" @click="start">
      语音作答
    </el-button>
    <el-button v-else type="danger" :icon="VideoPause" @click="stop">停止</el-button>

    <template v-if="recording">
      <span class="voice__dot" />
      <span class="voice__state">聆听中 {{ elapsedText }}</span>
      <span class="voice__level">
        <i v-for="(h, i) in bars" :key="i" :style="{ height: `${h}px` }" />
      </span>
      <span v-if="doneCount" class="voice__meta">已转写 {{ doneCount }} 句</span>
      <span v-if="pending" class="voice__meta voice__meta--working">正在转写…</span>
    </template>
    <template v-else>
      <span class="voice__hint">连续说话，停顿自动断句</span>
      <span v-if="doneCount" class="voice__meta">已转写 {{ doneCount }} 句</span>
    </template>

    <span v-if="!recording && failedCount" class="voice__fail">
      {{ failedCount }} 句转写失败
      <el-button link size="small" @click="retry">重试</el-button>
    </span>
    <span v-if="micError" class="voice__error">{{ micError }}</span>
  </div>
</template>

<style scoped>
.voice {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 32px;
  margin-bottom: 8px;
}
.voice__dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--el-color-danger);
  animation: voice-pulse 1.2s ease-in-out infinite;
}
@keyframes voice-pulse {
  0%,
  100% {
    opacity: 1;
    transform: scale(1);
  }
  50% {
    opacity: 0.4;
    transform: scale(0.8);
  }
}
.voice__state {
  font-size: var(--fs-sm);
  color: var(--c-text);
  font-variant-numeric: tabular-nums;
}
.voice__level {
  display: inline-flex;
  align-items: flex-end;
  gap: 2px;
  height: 18px;
}
.voice__level i {
  width: 3px;
  border-radius: var(--r-bar);
  background: var(--brand);
  transition: height 0.15s ease;
}
.voice__hint {
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}
.voice__meta {
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}
.voice__meta--working {
  color: var(--brand);
}
.voice__fail {
  font-size: var(--fs-xs);
  color: var(--el-color-danger);
}
.voice__error {
  font-size: var(--fs-xs);
  color: var(--el-color-danger);
}
</style>
