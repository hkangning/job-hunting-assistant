<script setup>
/**
 * 八股陪练（FR-009）：单路由 + 页内阶段状态机 setup → training → result。
 * 回看（detail）与三个阶段正交：详情打开时主区替换为只读会话。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Close } from '@element-plus/icons-vue'
import {
  getPracticeMeta, drawQuestions, createSession, finishSession,
  listSessions, getSession, getMastery, practiceTurnStream
} from '../api/practice'
import { createTurn, applyDelta, toPlainText } from '../utils/practiceStream'
import PracticeSetup from '../components/practice/PracticeSetup.vue'
import PracticeRunner from '../components/practice/PracticeRunner.vue'
import PracticeResult from '../components/practice/PracticeResult.vue'
import PracticeHistory from '../components/practice/PracticeHistory.vue'
import MasteryPanel from '../components/practice/MasteryPanel.vue'
import PracticeTurn from '../components/practice/PracticeTurn.vue'

const router = useRouter()

const meta = ref(null)
const phase = ref('setup')            // setup | training | result
const starting = ref(false)

// 训练
const session = ref(null)             // { id, mode, time_limit, status, question:{...} }
const turns = ref([])                 // 轮次数组（含流式中的那一轮）
const streaming = ref(false)
const result = ref(null)

// 历史与掌握度
const history = reactive({ items: [], total: 0, page: 1, pageSize: 10, mode: '' })
const mastery = ref([])

// 回看
const detail = ref(null)

/** 上一场的配置——「再练一场」据此同配置直接抽新题，不必回准备台重选。 */
const lastConfig = ref(null)

onMounted(async () => {
  await Promise.allSettled([loadMeta(), loadHistory(), loadMastery()])
})

async function loadMeta() {
  meta.value = await getPracticeMeta()
}

async function loadHistory() {
  const data = await listSessions({
    mode: history.mode || undefined,
    page: history.page,
    page_size: history.pageSize
  })
  history.items = data.items
  history.total = data.total
}

async function loadMastery() {
  mastery.value = (await getMastery({})).groups
}

async function handleStart(payload) {
  lastConfig.value = { ...payload }  // 存副本：准备台的表单后续变动不该影响「再练一场」
  starting.value = true
  try {
    const drawn = await drawQuestions({
      stacks: payload.stacks.length ? payload.stacks : undefined,
      directions: payload.directions.length ? payload.directions : undefined,
      qtypes: payload.qtypes.length ? payload.qtypes : undefined,
      count: 1,
      strategy: payload.strategy
    })
    const question = drawn.items?.[0]
    if (!question) {
      ElMessage.warning('当前筛选条件下没有题目，换个范围再试')
      return
    }
    const created = await createSession({
      question_id: question.id,
      mode: payload.mode,
      time_limit: payload.timeLimit || undefined
    })
    session.value = { ...created, question }
    turns.value = []
    result.value = null
    detail.value = null
    phase.value = 'training'
    // DEBUG 模式的第一轮是「取材料」：用户无需作答，进训练后自动发起
    if (payload.mode === 'DEBUG') runTurn({ userInput: '' })
  } finally {
    starting.value = false
  }
}

function runTurn(payload) {
  const turn = reactive({
    kind: inferKind(payload.action),
    // 选择题提交的是选项标识（契约推荐），展示用展开后的文本——与回看接口返回的形态一致
    userAnswer: payload.action === 'HINT' ? null : payload.displayText || payload.userInput,
    streaming: true,
    error: '',
    next: {},
    retryPayload: payload,   // 失败时照原参数重发
    ...createTurn()
  })
  turns.value.push(turn)
  streaming.value = true

  practiceTurnStream(
    {
      session_id: session.value.session_id,
      user_input: payload.userInput || undefined,
      action: payload.action || undefined,
      elapsed_ms: payload.elapsedMs || undefined,
      timed_out: payload.timedOut || undefined
    },
    {
      onDelta: (d) => applyDelta(turn, d),
      onDone: async (d) => {
        turn.streaming = false
        turn.next = d.extra || {}
        streaming.value = false
        if (d.extra?.should_finish) await settle()
      },
      onError: (e) => {
        turn.streaming = false
        turn.error = e.message || '本轮点评失败，可重试'
        streaming.value = false
      }
    }
  )
}

/** 轮次类型只用于显示标签；回看时由后端给出同一组值。 */
function inferKind(action) {
  if (action === 'HINT') return 'HINT'
  if (turns.value.length === 0) return 'OPENING'
  if (session.value.mode === 'DEBUG') return 'REBUTTAL'
  if (session.value.mode === 'FEYNMAN') return 'RETELL'
  return 'FOLLOW_UP'
}

/** 本轮点评失败后重试：丢弃失败的那一轮，照原参数重发——已答轮次不受影响。 */
function retryTurn(index) {
  const turn = turns.value[index]
  if (!turn?.retryPayload) return
  turns.value.splice(index, 1)
  runTurn(turn.retryPayload)
}

/** 结算：finish 幂等（重复调用结果一致且不重复入本）；结算后刷新历史与掌握度。 */
async function settle(sessionId = session.value?.session_id) {
  result.value = await finishSession(sessionId)
  phase.value = 'result'
  await Promise.allSettled([loadHistory(), loadMastery()])
}

const handleSubmit = ({ userInput, displayText, timedOut, elapsedMs }) =>
  runTurn({ userInput, displayText, timedOut, elapsedMs })
const handleHint = () => runTurn({ userInput: '', action: 'HINT' })
const handleEnd = () => runTurn({ userInput: '', action: 'END' })
const handleTimeout = ({ elapsedMs }) => runTurn({ userInput: '', timedOut: true, elapsedMs })

/**
 * 退出训练：纯前端动作——契约的 8 个端点里没有「中止会话」，
 * 按 SRS 的口径「中途退出 → 会话保留」，这场会以 RUNNING 留在训练记录里，可事后结算。
 */
function handleExit() {
  backToSetup()
  loadHistory()
  ElMessage.info('已退出，本场保留在训练记录里，可随时结算')
}

async function openDetail(item) {
  detail.value = await getSession(item.id)
}

/**
 * 继续一场未完成的训练：把已落库的轮次重建成视图模型，接着作答。
 *
 * 不猜后端状态机的下一步——直接发 `action=SUBMIT`，由后端按自己的进度处理
 * （该追问就追问、该收尾就收尾），前端只负责把历史轮次摆出来。
 * 限时档位由回看接口的 `time_limit` 恢复（接口文档 v1.27 补，IS-38）。
 */
async function resumeSession(item) {
  const data = await getSession(item.id)
  detail.value = null
  result.value = null
  session.value = {
    session_id: data.id,
    mode: data.mode,
    status: data.status,
    time_limit: data.time_limit ?? null,
    question: data.question
  }
  turns.value = (data.rounds || []).map((round) => toTurnModel(round, data.mode))
  phase.value = 'training'
}

function changeHistoryPage(page) {
  history.page = page
  loadHistory()
}

function changeHistoryMode(mode) {
  history.mode = mode
  history.page = 1
  loadHistory()
}

function backToSetup() {
  phase.value = 'setup'
  session.value = null
  turns.value = []
  result.value = null
  detail.value = null
}

/**
 * 再练一场：沿用上一场的筛选与模式**直接抽新题开新的一场**。
 * 与「回到准备台」分工不同——那个是回去改配置（两者此前都回准备台，功能重复）。
 */
function playAgain() {
  if (lastConfig.value) handleStart(lastConfig.value)
  else backToSetup()
}

/**
 * 后端存的轮次 → PracticeTurn 的视图模型（回看与「继续作答」共用）。
 *
 * 后端把每轮点评存成整段文本（无 section 分流），这里按轮次类型还原成块。
 * 注意**材料轮的 `round_kind` 也是 `HINT`**（与教练模式的提示轮同一个值，接口文档
 * v1.26 实现口径），只能靠会话模式区分，故要把 `sessionMode` 一并传进来；
 * 其 `review` 存的是材料全文，按 material 渲染。
 */
function toTurnModel(round, sessionMode) {
  const blocks = []
  if (round.score !== null && round.score !== undefined) {
    blocks.push({ section: 'round_score', text: `${round.score} 分` })
  }
  const isMaterial = sessionMode === 'DEBUG' && round.kind === 'HINT'
  const section = isMaterial ? 'material' : round.kind === 'HINT' ? 'hint' : 'review'
  if (round.review) blocks.push({ section, text: round.review })
  return {
    kind: round.kind,
    // 提示轮 / 材料轮的作答是空串，转 null 走「不渲染作答区」的分支
    userAnswer: round.user_answer || null,
    streaming: false,
    error: '',
    next: {},
    dimensions: null,
    dimensionsRaw: '',
    blocks
  }
}

const detailRounds = computed(() =>
  detail.value ? detail.value.rounds.map((round) => toTurnModel(round, detail.value.mode)) : []
)

const detailAnswerTitle = computed(() =>
  detail.value?.question?.qtype === 'SCENARIO' ? '参考框架' : '参考答案'
)

const detailModeLabel = computed(() =>
  (meta.value?.modes || []).find((m) => m.value === detail.value?.mode)?.label ||
  detail.value?.mode ||
  ''
)
</script>

<template>
  <div class="practice" :class="{ 'practice--wide': phase !== 'setup' || detail }">
    <main class="practice__main">
      <!-- 回看：只读会话，与三个阶段正交 -->
      <div v-if="detail" class="practice__detail">
        <header class="practice__detail-head">
          <span class="practice__detail-mode">{{ detailModeLabel }}</span>
          <span class="practice__detail-title">{{ detail.question.content }}</span>
          <el-button class="practice__detail-close" :icon="Close" @click="detail = null">
            关闭
          </el-button>
        </header>
        <PracticeTurn
          v-for="(round, index) in detailRounds"
          :key="index"
          :turn="round"
          :faces="meta?.faces || []"
          :qtype="detail.question.qtype"
        />
        <section v-if="detail.reference_answer" class="practice__card">
          <h3 class="practice__card-title">{{ detailAnswerTitle }}</h3>
          <p class="practice__answer">{{ toPlainText(detail.reference_answer) }}</p>
        </section>
      </div>

      <!-- 训练中 -->
      <PracticeRunner
        v-else-if="phase === 'training'"
        :session="session"
        :turns="turns"
        :meta="meta"
        :streaming="streaming"
        @submit="handleSubmit"
        @hint="handleHint"
        @end="handleEnd"
        @exit="handleExit"
        @timeout="handleTimeout"
        @retry="retryTurn"
      />

      <!-- 结算 -->
      <PracticeResult
        v-else-if="phase === 'result'"
        :result="result"
        :meta="meta"
        :qtype="session?.question?.qtype || 'SUBJECTIVE'"
        @again="playAgain"
        @close="backToSetup"
        @open-wrong="router.push('/wrong-questions')"
      />

      <!-- 准备台：占宽主区（筛选与模式都需要横向空间） -->
      <PracticeSetup v-else :meta="meta" :busy="starting" @start="handleStart" />
    </main>

    <!-- 右栏：开练前的参考信息（掌握度决定练什么、记录决定还要不要练） -->
    <aside v-if="phase === 'setup' && !detail" class="practice__side">
      <MasteryPanel :groups="mastery" />
      <PracticeHistory
        :items="history.items"
        :total="history.total"
        :page="history.page"
        :page-size="history.pageSize"
        :mode-filter="history.mode"
        :meta="meta"
        @open="openDetail"
        @resume="resumeSession"
        @page-change="changeHistoryPage"
        @mode-change="changeHistoryMode"
      />
    </aside>
  </div>
</template>

<style scoped>
.practice {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 320px;
  gap: var(--card-gap);
  align-items: start;
}
.practice--wide {
  grid-template-columns: 1fr;
}

.practice__side > * + * {
  margin-top: var(--card-gap);
}

.practice__detail-head {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: var(--card-gap);
}
.practice__detail-mode {
  flex: 0 0 auto;
  padding: 2px 9px;
  font-size: var(--fs-xs);
  color: var(--m-practice);
  background: color-mix(in srgb, var(--m-practice) 12%, var(--c-card));
  border-radius: var(--r-mark);
}
.practice__detail-title {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  font-size: var(--fs-title);
  font-weight: 700;
  color: var(--c-text);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.practice__detail-head .el-button {
  flex: 0 0 auto;
}
/* 回看的关闭：默认的白底按钮压在白色卡片上边界不清（试用反馈「太不明显」）。
   改中性浅底 + 边框 + 更深的字色，仍是次要动作的克制观感，但一眼能找到。 */
.practice__detail-close {
  color: var(--c-text);
  background: var(--c-bg);
  border-color: var(--c-border);
}
.practice__detail-close:hover,
.practice__detail-close:focus {
  color: var(--c-text);
  background: var(--c-divider);
  border-color: var(--c-text-3);
}

.practice__card {
  background: var(--c-card);
  border: 1px solid var(--c-border);
  border-radius: var(--r-card);
  padding: var(--card-padding);
  margin-top: var(--card-gap);
}
.practice__card-title {
  margin: 0 0 10px;
  font-size: var(--fs-title);
  font-weight: 700;
  color: var(--c-text);
}
.practice__answer {
  margin: 0;
  font-size: var(--fs-body);
  line-height: 1.8;
  color: var(--c-text);
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
