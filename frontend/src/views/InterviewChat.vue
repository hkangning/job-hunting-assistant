<script setup>
/**
 * 面试进行页（FR-007 / 开发计划步骤 15；接口文档 v1.31 §3.7）。
 *
 * 消息序列由 `utils/interviewStream.js` 构建——刷新恢复（qa_list 展开）与流式
 * （delta 归段）共用同一份渲染。本页负责三件事：加载恢复（tail 分流）、
 * 流式编排、作答区。总结入口属步骤 16，此处只做到「答满题量」完成态。
 */
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Back } from '@element-plus/icons-vue'
import { getInterviewSession, interviewChatStream } from '../api/interview'
import { getPracticeMeta } from '../api/practice'
import { directionLabelMap } from '../utils/practiceMeta'
import { parseRoundScore } from '../utils/practiceStream'
import {
  appendAnswer,
  applyDelta,
  buildMessages,
  insertSkipped,
  sealStreaming
} from '../utils/interviewStream'
import InterviewMessages from '../components/interview/InterviewMessages.vue'

const route = useRoute()
const router = useRouter()
const sessionId = route.params.sessionId

const session = ref(null)
const messages = ref([])
/** 'empty'（待请首题）| 'awaiting-answer' | 'midway'（可继续）| 'finished' */
const tail = ref('')
const input = ref('')
const loading = ref(true)
const streaming = ref(false)
const thinking = ref('')
const errorMsg = ref('')
const meta = ref(null)
const scroller = ref(null)

let stream = null // 当前 SSE 句柄
let lastPayload = null // 失败重试的原参数

/** 方向中文名（同列表页口径；GENERAL 单独补）。 */
const directionText = computed(() => {
  if (!session.value) return ''
  const map = { GENERAL: '通用', ...directionLabelMap(meta.value) }
  return map[session.value.direction] || session.value.direction
})

/** 当前题号：已出现过的最大 seq。 */
const currentSeq = computed(() => {
  let max = 0
  for (const m of messages.value) if (m.kind === 'question' && m.seq > max) max = m.seq
  return max
})

const isFinished = computed(() => tail.value === 'finished' || session.value?.status === 'FINISHED')

const canSubmit = computed(
  () => !streaming.value && !isFinished.value && input.value.trim().length > 0
)

async function load() {
  loading.value = true
  try {
    const data = await getInterviewSession(sessionId)
    session.value = data
    const built = buildMessages(data, data.qa_list || [])
    messages.value = built.messages
    tail.value = built.tail
    scrollToBottom()
    // 新会话：自动请首题；FINISHED 会话只读展示，不请求
    if (tail.value === 'empty' && data.status === 'ACTIVE') requestNext({ answer: '' })
  } catch (error) {
    errorMsg.value = error?.message || '加载失败，请返回列表重试'
  } finally {
    loading.value = false
  }
}

/** 发一轮流式请求。payload: `{ answer }` / `{ skip: true }`（midway 继续发 `{ answer: '' }`）。 */
function requestNext(payload) {
  lastPayload = payload
  streaming.value = true
  errorMsg.value = ''
  thinking.value = ''
  stream = interviewChatStream(
    { session_id: Number(sessionId), ...payload },
    {
      onStart: (d) => {
        thinking.value = d?.message || '面试官思考中…'
        scrollToBottom()
      },
      onDelta: (d) => {
        applyDelta(messages.value, d)
        scrollToBottom()
      },
      onDone: (d) => {
        sealStreaming(messages.value)
        streaming.value = false
        thinking.value = ''
        // 后端 done 携带新题 seq：校准本地估算的题号
        const last = messages.value[messages.value.length - 1]
        if (d.seq != null && last?.kind === 'question') last.seq = d.seq
        attachScore()
        tail.value = d.extra?.session_finished ? 'finished' : 'awaiting-answer'
        scrollToBottom()
      },
      onError: (e) => {
        sealStreaming(messages.value)
        streaming.value = false
        thinking.value = ''
        errorMsg.value =
          e?.code === 10012
            ? '未配置 AI 密钥，请前往 AI 配置页配置后重试'
            : e?.message || '生成中断，请重试'
      }
    }
  )
}

/** 点评分数：契约的 done 不带分数，从点评正文解析（与陪练同一解析器）。 */
function attachScore() {
  for (let i = messages.value.length - 1; i >= 0; i--) {
    const m = messages.value[i]
    if (m.kind !== 'review') continue
    if (m.score == null) {
      const { score } = parseRoundScore(m.text)
      if (score != null) m.score = score
    }
    break
  }
}

function submitAnswer() {
  if (!canSubmit.value) return
  const text = input.value.trim()
  input.value = ''
  appendAnswer(messages.value, text)
  scrollToBottom()
  requestNext({ answer: text })
}

function skip() {
  insertSkipped(messages.value)
  scrollToBottom()
  requestNext({ skip: true })
}

function continueNext() {
  requestNext({ answer: '' })
}

function retry() {
  if (lastPayload) requestNext(lastPayload)
}

function backToList() {
  router.push('/interview')
}

function scrollToBottom() {
  nextTick(() => {
    const el = scroller.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

onMounted(() => {
  load()
  getPracticeMeta()
    .then((data) => (meta.value = data))
    .catch(() => {}) // 拉不到就显示枚举值兜底
})

// 离开页面时断流：避免后台跑完却没人消费（内容仍会由后端落库）
onUnmounted(() => stream?.abort())
</script>

<template>
  <section class="chat">
    <header class="chat__head">
      <el-button link :icon="Back" @click="backToList">返回列表</el-button>
      <span class="chat__title">
        {{ session ? `${session.company} · ${session.position}` : '加载中…' }}
      </span>
      <span v-if="session" class="chat__dir">{{ directionText }}</span>
      <span v-if="session" class="chat__progress">
        第 {{ currentSeq }}/{{ session.question_count }} 题
      </span>
    </header>

    <div ref="scroller" v-loading="loading" class="chat__stream">
      <InterviewMessages :messages="messages" />
      <p v-if="thinking" class="chat__thinking">{{ thinking }}</p>
    </div>

    <div v-if="errorMsg" class="chat__error">
      <span>{{ errorMsg }}</span>
      <el-button v-if="lastPayload" size="small" @click="retry">重试</el-button>
    </div>

    <footer v-if="!isFinished" class="chat__composer">
      <p v-if="tail === 'empty'" class="chat__preparing">面试官正在准备第一个问题…</p>

      <template v-else-if="tail === 'midway'">
        <div class="chat__resume">
          <span class="chat__resume-text">上一轮已提交，面试尚未结束。</span>
          <el-button type="primary" :loading="streaming" @click="continueNext">
            继续下一题
          </el-button>
        </div>
      </template>

      <template v-else>
        <el-input
          v-model="input"
          type="textarea"
          :rows="3"
          :disabled="streaming"
          maxlength="5000"
          placeholder="输入你的作答（Ctrl + Enter 提交）"
          @keydown.ctrl.enter="submitAnswer"
        />
        <div class="chat__actions">
          <el-popconfirm
            title="跳过本题？不计分，直接进入下一题"
            confirm-button-text="跳过"
            cancel-button-text="取消"
            width="240"
            @confirm="skip"
          >
            <template #reference>
              <el-button :disabled="streaming">跳过</el-button>
            </template>
          </el-popconfirm>
          <el-button type="primary" :disabled="!canSubmit" :loading="streaming" @click="submitAnswer">
            提交
          </el-button>
        </div>
      </template>
    </footer>

    <p v-else class="chat__done">本场面试已完成 · 共 {{ session?.question_count }} 题</p>
  </section>
</template>

<style scoped>
.chat {
  display: flex;
  flex-direction: column;
  /* 撑满内容区：用 100% 而非 viewport 计算——--content-padding 是简写值（`20px 22px`），
     参与 calc 乘法会整条声明失效；el-main 为 flex 拉伸出的确定高度，百分比可解析 */
  height: 100%;
  background: var(--c-card);
  border: 1px solid var(--c-border);
  border-radius: var(--r-card);
  box-shadow: 0 1px 2px rgba(42, 39, 64, 0.05);
  overflow: hidden;
}

.chat__head {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px var(--card-padding);
  border-bottom: 1px solid var(--c-divider);
}
.chat__title {
  font-size: var(--fs-body);
  font-weight: 600;
  color: var(--c-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.chat__dir {
  flex: 0 0 auto;
  padding: 1px 8px;
  font-size: var(--fs-xs);
  color: var(--m-interview);
  background: color-mix(in srgb, var(--m-interview) 12%, var(--c-card));
  border-radius: var(--r-mark);
}
.chat__progress {
  margin-left: auto;
  flex: 0 0 auto;
  font-size: var(--fs-sm);
  color: var(--c-text-2);
  font-variant-numeric: tabular-nums;
}

.chat__stream {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: var(--card-padding);
}
.chat__thinking {
  margin: 10px 0 0;
  font-size: var(--fs-sm);
  color: var(--c-text-3);
}

.chat__error {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px var(--card-padding);
  font-size: var(--fs-sm);
  color: var(--el-color-danger);
  background: var(--el-color-danger-light-9);
}

.chat__composer {
  padding: 12px var(--card-padding);
  border-top: 1px solid var(--c-divider);
}
.chat__actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 8px;
}
.chat__preparing,
.chat__done {
  margin: 0;
  padding: 4px 0;
  font-size: var(--fs-sm);
  color: var(--c-text-2);
}
.chat__done {
  padding: 14px var(--card-padding);
  border-top: 1px solid var(--c-divider);
}
.chat__resume {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.chat__resume-text {
  font-size: var(--fs-sm);
  color: var(--c-text-2);
}
</style>
