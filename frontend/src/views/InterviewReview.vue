<script setup>
/**
 * 面试回看页（FR-007 / 开发计划步骤 16 前端部分；接口文档 v1.33 §3.7）。
 *
 * 两段内容：**总结报告**（`/stream/interview-summary`，契约已冻结、后端实现中）+
 * **完整对话回顾**（`GET /interview-sessions/{id}`，后端已就绪）。
 *
 * 本页是总结生成的**唯一入口**：进入时若 `summary` 为空且有已完成问答，自动发起
 * 一次流式生成（done 时会话置 FINISHED——「提前结束」也走这条路径，进行页只负责
 * 跳转）；重复进入读到已落库的 summary 直接展示，不重复计费。
 */
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Back } from '@element-plus/icons-vue'
import { getInterviewSession, interviewSummaryStream } from '../api/interview'
import { getPracticeMeta } from '../api/practice'
import { directionLabelMap } from '../utils/practiceMeta'
import { toPlainText } from '../utils/practiceStream'
import { buildMessages } from '../utils/interviewStream'
import { shortDateTime } from '../utils/datetime'
import InterviewMessages from '../components/interview/InterviewMessages.vue'
import ReviewBody from '../components/interview/ReviewBody.vue'
import StreamText from '../components/StreamText.vue'

const route = useRoute()
const router = useRouter()
const sessionId = route.params.sessionId

const session = ref(null)
const messages = ref([])
const loading = ref(true)
const errorMsg = ref('')
const meta = ref(null)

/** 总结：流式累积或落库原文；空 + 有已完成问答时自动生成。 */
const summary = ref('')
const summaryStreaming = ref(false)
const summaryError = ref('')
let summaryStream = null

const directionText = computed(() => {
  if (!session.value) return ''
  const map = { GENERAL: '通用', ...directionLabelMap(meta.value) }
  return map[session.value.direction] || session.value.direction
})

/** 有可总结的内容：至少一条已完成问答（答过或跳过）——契约要求 summary 的会话须含 ≥1 条。 */
const canSummarize = computed(() =>
  messages.value.some((m) => m.kind === 'answer')
)

async function load() {
  loading.value = true
  errorMsg.value = ''
  try {
    const data = await getInterviewSession(sessionId)
    session.value = data
    messages.value = buildMessages(data, data.qa_list || []).messages
    summary.value = data.summary || ''
    // 无总结且有可总结内容 → 自动生成一次（进行中会话从这里「结束本场」）
    if (!summary.value && canSummarize.value) startSummary()
  } catch (error) {
    errorMsg.value = error?.message || '加载失败，请返回列表重试'
  } finally {
    loading.value = false
  }
}

function startSummary() {
  summaryStreaming.value = true
  summaryError.value = ''
  summary.value = ''
  summaryStream = interviewSummaryStream(
    { session_id: Number(sessionId) },
    {
      onDelta: (d) => {
        if (!d?.section || d.section === 'summary') summary.value += d.text || ''
      },
      onDone: () => {
        summaryStreaming.value = false
        // 总结生成即会话结束（契约行为）——本地状态同步，页头徽章即时变化
        if (session.value) session.value.status = 'FINISHED'
      },
      onError: (e) => {
        summaryStreaming.value = false
        // 只透出可操作的两种：未配 Key 与通用失败——后端 message 在此场景可能误导
        // （端点未就绪时统一异常处理器会把它包成「会话不存在」）
        summaryError.value =
          e?.code === 10012
            ? '未配置 AI 密钥，请前往 AI 配置页配置后重试'
            : '总结生成失败，请稍后重试'
      }
    }
  )
}

function retrySummary() {
  if (!summaryStreaming.value) startSummary()
}

function backToList() {
  router.push('/interview')
}

onMounted(() => {
  load()
  getPracticeMeta()
    .then((data) => (meta.value = data))
    .catch(() => {}) // 拉不到就显示枚举值兜底
})

onUnmounted(() => {
  summaryStream?.abort() // 离开页面断流：避免后台跑完却没人消费（内容仍会由后端落库）
})
</script>

<template>
  <section class="review-page">
    <header class="review-page__head">
      <el-button link :icon="Back" @click="backToList">返回列表</el-button>
      <span class="review-page__title">
        {{ session ? `${session.company} · ${session.position}` : '加载中…' }}
      </span>
      <span v-if="session" class="review-page__dir">{{ directionText }}</span>
      <span v-if="session" class="review-page__meta">
        共 {{ session.question_count }} 题 · {{ shortDateTime(session.created_at) }}
      </span>
      <span
        v-if="session"
        class="review-page__badge"
        :class="{ 'review-page__badge--done': session.status === 'FINISHED' }"
      >
        {{ session.status === 'FINISHED' ? '已结束' : '进行中' }}
      </span>
    </header>

    <div v-if="errorMsg" class="review-page__error">
      <span>{{ errorMsg }}</span>
      <el-button size="small" @click="load">重试</el-button>
    </div>

    <div v-else v-loading="loading" class="review-page__body">
      <!-- 总结报告 -->
      <section class="review-page__summary">
        <h3 class="review-page__section-title">总结报告</h3>

        <div v-if="summaryStreaming" class="review-page__summary-text">
          <StreamText :text="toPlainText(summary)" :streaming="true" />
        </div>

        <!-- 分段着色与进行页的点评卡共用 ReviewBody（同一份解析与配色） -->
        <ReviewBody v-else-if="summary" :text="toPlainText(summary)" />

        <template v-else-if="summaryError">
          <p class="review-page__summary-hint review-page__summary-hint--error">{{ summaryError }}</p>
          <el-button type="primary" plain @click="retrySummary">重新生成</el-button>
        </template>

        <template v-else-if="canSummarize">
          <p class="review-page__summary-hint">本场尚未生成总结报告</p>
          <el-button type="primary" @click="startSummary">生成总结报告</el-button>
        </template>

        <p v-else class="review-page__summary-hint">本场还没有已作答的题目，暂无总结。</p>
      </section>

      <!-- 完整回顾 -->
      <section class="review-page__history">
        <h3 class="review-page__section-title">完整回顾</h3>
        <InterviewMessages :messages="messages" />
      </section>
    </div>
  </section>
</template>

<style scoped>
.review-page {
  background: var(--c-card);
  border: 1px solid var(--c-border);
  border-radius: var(--r-card);
  box-shadow: 0 1px 2px rgba(42, 39, 64, 0.05);
  padding: var(--card-padding);
}

.review-page__head {
  display: flex;
  align-items: center;
  gap: 12px;
  padding-bottom: 12px;
  margin-bottom: var(--card-gap);
  border-bottom: 1px solid var(--c-divider);
}
.review-page__title {
  font-size: var(--fs-title);
  font-weight: 600;
  color: var(--c-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.review-page__dir {
  flex: 0 0 auto;
  padding: 1px 8px;
  font-size: var(--fs-xs);
  color: var(--m-interview);
  background: color-mix(in srgb, var(--m-interview) 12%, var(--c-card));
  border-radius: var(--r-mark);
}
.review-page__meta {
  margin-left: auto;
  flex: 0 0 auto;
  font-size: var(--fs-sm);
  color: var(--c-text-3);
  font-variant-numeric: tabular-nums;
}
.review-page__badge {
  flex: 0 0 auto;
  padding: 1px 8px;
  font-size: var(--fs-xs);
  color: var(--c-text-2);
  background: var(--c-bg);
  border-radius: var(--r-mark);
}
.review-page__badge--done {
  color: var(--c-text-3);
}

.review-page__error {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 0;
  font-size: var(--fs-sm);
  color: var(--el-color-danger);
}

.review-page__body {
  display: flex;
  flex-direction: column;
  gap: var(--card-gap);
  min-height: 120px;
}

/* 总结报告：模块色浅底卡，与做题页的点评卡同一视觉语言 */
.review-page__summary {
  border: 1px solid color-mix(in srgb, var(--m-interview) 30%, var(--c-card));
  border-radius: var(--r-card);
  background: color-mix(in srgb, var(--m-interview) 6%, var(--c-card));
  padding: 14px 18px;
}
.review-page__section-title {
  margin: 0 0 10px;
  font-size: var(--fs-title);
  font-weight: 700;
  color: var(--c-text);
}
.review-page__summary .review-page__section-title {
  margin-bottom: 8px;
  color: var(--m-interview);
}
.review-page__summary-text {
  font-size: var(--fs-body);
  line-height: 1.85;
  color: var(--c-text);
  white-space: pre-wrap;
  word-break: break-word;
}
.review-page__summary-hint {
  margin: 0 0 10px;
  font-size: var(--fs-sm);
  color: var(--c-text-2);
}
.review-page__summary-hint--error {
  color: var(--el-color-danger);
}

.review-page__history {
  padding-top: 4px;
}
</style>
