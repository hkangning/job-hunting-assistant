<script setup>
/**
 * 面试进行页（FR-007 / 开发计划步骤 15；接口文档 v1.33 §3.7）。
 *
 * 消息序列由 `utils/interviewStream.js` 构建——刷新恢复（qa_list 展开）与流式
 * （delta 归段）共用同一份渲染。本页负责三件事：加载恢复（tail 分流）、
 * 流式编排、作答区。总结入口属步骤 16，此处只做到「答满题量」完成态。
 */
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Back, CircleCheck } from '@element-plus/icons-vue'
import { getInterviewSession, interviewChatStream } from '../api/interview'
import { getPracticeMeta } from '../api/practice'
import { getSettingsApi } from '../api/settings'
import { useAppStore } from '../stores/app'
import { directionLabelMap } from '../utils/practiceMeta'
import { parseRoundScore } from '../utils/practiceStream'
import { addSegment, toSegmentsPayload } from '../utils/voiceSegments'
import { toSpeakableText } from '../utils/ttsText'
import { ttsPlayer, ttsSpeakingKey, toggleSpeakMessage } from '../utils/ttsPlayer'
import {
  appendAnswer,
  applyDelta,
  buildMessages,
  insertSkipped,
  INTENSITY_LABELS,
  sealStreaming,
  stageProgress
} from '../utils/interviewStream'
import InterviewMessages from '../components/interview/InterviewMessages.vue'
import ResizableTextarea from '../components/ResizableTextarea.vue'
import VoiceInput from '../components/VoiceInput.vue'

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
const errorCode = ref(null)
const meta = ref(null)
const scroller = ref(null)

// 语音（步骤 24）：voice_enabled 控制作答区语音工具条显隐；tts_enabled 控制播报
const appStore = useAppStore()
const voiceEnabled = ref(false)
const ttsEnabled = ref(false)
const voiceRecording = ref(false)
const voiceRef = ref(null)
let segments = [] // 分句时间轴（原始转写）；提交 / 跳过后清空

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

/** 进度（当前题号 / 题量），供页头进度条。 */
const progressPct = computed(() => {
  const total = session.value?.question_count || 0
  return total ? Math.min(100, Math.round((currentSeq.value / total) * 100)) : 0
})

/**
 * 面试阶段（自我介绍 / 技术问答 / 项目深挖）——计划表 `stages` 由后端随会话下发。
 * 后端未落地该字段时 `stageInfo` 为 null，页头降级为「第 N/M 题」（不显示阶段标签）。
 */
const stageInfo = computed(() => stageProgress(session.value?.stages, currentSeq.value))

/** 作答过至少一条（含跳过）——供「结束本场」的确认文案分场景（IS-63 方案 A：未作答也可结束）。 */
const hasAnswer = computed(() => messages.value.some((m) => m.kind === 'answer'))

/** 「结束本场」确认框标题与按钮提示：未作答时不提「总结报告」（后端落固定说明、无总结内容）。 */
const finishTitle = computed(() =>
  hasAnswer.value
    ? '结束本场并生成总结报告？已作答的题目会保留'
    : '结束本场？本场还没有作答，无内容可总结。'
)
const finishHint = computed(() =>
  hasAnswer.value ? '提前结束本场面试，生成总结报告' : '结束本场面试（本场还没有作答）'
)

const canSubmit = computed(
  () =>
    !streaming.value && !isFinished.value && !voiceRecording.value && input.value.trim().length > 0
)

/** 拉一次设置：语音作答 / 播报两个开关（失败降级用 store 旧值，默认关）。 */
async function loadSettings() {
  try {
    const data = await getSettingsApi({ silent: true })
    appStore.setSettings(data)
    ttsEnabled.value = !!data.tts_enabled
    voiceEnabled.value = !!data.voice_enabled
  } catch {
    ttsEnabled.value = !!appStore.settings.tts_enabled
    voiceEnabled.value = !!appStore.settings.voice_enabled
  }
}

async function load() {
  loading.value = true
  try {
    const data = await getInterviewSession(sessionId)
    session.value = data
    const built = buildMessages(data, data.qa_list || [])
    messages.value = built.messages
    tail.value = built.tail
    scrollToBottom(true)
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
  errorCode.value = null
  thinking.value = ''
  stream = interviewChatStream(
    { session_id: Number(sessionId), ...payload },
    {
      onStart: (d) => {
        thinking.value = d?.message || '面试官思考中…'
      },
      onDelta: (d) => {
        applyDelta(messages.value, d)
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
        // 自动播报：本轮点评 + 下一题（开关开时；手动按钮共用同一组装口径）
        if (ttsEnabled.value) {
          for (let i = messages.value.length - 1; i >= 0; i--) {
            if (messages.value[i].kind === 'review') {
              speakRound(i)
              break
            }
          }
        }
      },
      onError: (e) => {
        sealStreaming(messages.value)
        streaming.value = false
        thinking.value = ''
        errorCode.value = e?.code ?? null
        // 会话状态已变（已结束 / 题量答满 / 被其他端消费）：本地已过时，
        // 直接重新拉取回到真实状态，而不是让用户对着重试按钮反复撞 409
        if (e?.code === 40001) {
          errorMsg.value = ''
          ElMessage.warning('会话状态已更新，已为你重新加载')
          load()
          return
        }
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

/** 转写结果回填：拼到作答框末尾并记入 segments（空文本由 addSegment 过滤）。 */
function onVoiceAppend({ text, startMs, endMs }) {
  const t = String(text ?? '').trim()
  if (!t) return
  input.value = input.value ? `${input.value}${t}` : t
  addSegment(segments, { text: t, startMs, endMs })
}

function onVoiceRecording(v) {
  voiceRecording.value = v
}

/** 消息卡「朗读 / 停止」：所见即所播（点评播点评、提问播题干），同一条再点即停。 */
function onSpeak(index) {
  toggleSpeakMessage(messages.value[index])
}

/** 自动播报（每轮 done 后）：整轮「点评 + 下一题」两段；播到哪段、哪段的图标亮起。 */
function speakRound(reviewIndex) {
  const review = messages.value[reviewIndex]
  if (!review) return
  const segs = []
  const reviewText = toSpeakableText('review', review.text)
  if (reviewText) segs.push({ text: reviewText, key: review })
  for (let j = reviewIndex + 1; j < messages.value.length; j++) {
    if (messages.value[j].kind === 'question') {
      const q = messages.value[j]
      const qText = toSpeakableText('question', q.text)
      if (qText) segs.push({ text: qText, key: q })
      break
    }
  }
  if (segs.length) ttsPlayer.play(segs)
}

function submitAnswer() {
  if (!canSubmit.value) return
  const text = input.value.trim()
  input.value = ''
  appendAnswer(messages.value, text)
  scrollToBottom(true)
  const payload = { answer: text }
  const segs = toSegmentsPayload(segments)
  if (segs) payload.segments = segs
  segments = []
  voiceRef.value?.reset()
  ttsPlayer.stop() // 切换题目即停（正在播报上一轮时）
  requestNext(payload)
}

function skip() {
  segments = []
  voiceRef.value?.reset()
  ttsPlayer.stop()
  insertSkipped(messages.value)
  scrollToBottom(true)
  requestNext({ skip: true })
}

function continueNext() {
  ttsPlayer.stop()
  requestNext({ answer: '' })
}

function retry() {
  if (lastPayload) requestNext(lastPayload)
}

function backToList() {
  router.push('/interview')
}

/**
 * 去回看页。总结的生成与会话置 FINISHED 都在回看页完成（单一入口）：
 * 「结束本场」与完成态的「查看总结报告」都只是跳转，不在本页发起请求。
 */
function goReview() {
  router.push(`/interview/${sessionId}/review`)
}

/**
 * 粘性底部：只跟随、不拉扯。
 *
 * `stick` = 用户是否处在底部附近——内容变化（流式 delta、**打字机逐字增长**）时
 * 若吸附则滚到底；用户上翻则解除吸附，回到底部附近再恢复。
 * 用 MutationObserver 而非在事件回调里滚：打字机在流式结束后还要追 1~2 秒，
 * 只在 onDelta/onDone 时刻滚会让底部在这段期间"长出去"（走查实测发现）。
 * `force` 用于用户自己的动作（提交 / 跳过 / 进入页面），那些场景本来就期望看到最新。
 */
let stick = true

function scrollToBottom(force = false) {
  nextTick(() => {
    const el = scroller.value
    if (!el) return
    if (force) stick = true
    if (stick) el.scrollTop = el.scrollHeight
  })
}

function onStreamScroll() {
  const el = scroller.value
  if (!el) return
  stick = el.scrollHeight - el.scrollTop - el.clientHeight < 80
}

let observer = null

onMounted(() => {
  load()
  loadSettings()
  getPracticeMeta()
    .then((data) => (meta.value = data))
    .catch(() => {}) // 拉不到就显示枚举值兜底
  // 内容变化（含打字机逐字增长）时若吸附底部则跟随
  observer = new MutationObserver(() => {
    if (stick) scrollToBottom()
  })
  observer.observe(scroller.value, { childList: true, subtree: true, characterData: true })
})

// 离开页面时断流：避免后台跑完却没人消费（内容仍会由后端落库）；播报同停
onUnmounted(() => {
  stream?.abort()
  observer?.disconnect()
  ttsPlayer.stop()
})
</script>

<template>
  <section class="chat">
    <header class="chat__head">
      <el-button link :icon="Back" class="chat__back" @click="backToList">返回列表</el-button>
      <span class="chat__title">
        {{ session ? `${session.company} · ${session.position}` : '加载中…' }}
      </span>
      <span v-if="session" class="chat__dir">{{ directionText }}</span>
      <span v-if="session" class="chat__intensity">{{ INTENSITY_LABELS[session.intensity] || '中厂' }}</span>
      <span v-if="stageInfo" class="chat__stage">{{ stageInfo.label }}</span>
      <div v-if="session" class="chat__progress">
        <span class="chat__progress-text">
          {{
            stageInfo
              ? `第 ${stageInfo.index}/${stageInfo.count} 题`
              : `第 ${currentSeq}/${session.question_count} 题`
          }}
        </span>
        <span class="chat__progress-bar"><i :style="{ width: progressPct + '%' }" /></span>
      </div>
    </header>

    <div ref="scroller" v-loading="loading" class="chat__stream" @scroll.passive="onStreamScroll">
      <InterviewMessages
        :messages="messages"
        :speak-enabled="ttsEnabled"
        :speaking-key="ttsSpeakingKey"
        @speak="onSpeak"
      />
      <p v-if="thinking" class="chat__thinking">{{ thinking }}</p>
    </div>

    <div v-if="errorMsg" class="chat__error">
      <span>{{ errorMsg }}</span>
      <el-button
        v-if="errorCode === 10012"
        size="small"
        type="primary"
        plain
        @click="router.push('/ai-config')"
      >
        前往配置
      </el-button>
      <el-button v-if="lastPayload" size="small" @click="retry">重试</el-button>
    </div>

    <footer v-if="!isFinished" class="chat__composer">
      <p v-if="tail === 'empty'" class="chat__preparing">面试官正在准备第一个问题…</p>

      <template v-else-if="tail === 'midway'">
        <div class="chat__resume">
          <span class="chat__resume-text">上次作答已提交，下一题还没生成</span>
          <el-button type="primary" :loading="streaming" @click="continueNext">
            继续本场面试
          </el-button>
        </div>
      </template>

      <template v-else>
        <!-- 语音作答（voice_enabled 开时显示）：连续说话、停顿自动断句、逐句回填 -->
        <VoiceInput
          v-if="voiceEnabled"
          ref="voiceRef"
          :disabled="streaming"
          @append="onVoiceAppend"
          @recording="onVoiceRecording"
        />
        <!-- 固定高度 + 顶部拖拽条手动调整（ResizableTextarea）：高度由用户自己拖出，
             输入不改变高度（与 autosize 互斥）；拖拽条整条宽、命中面积大。
             录音中只读：转写回填与手动编辑同时发生会抢光标，停止后立即可编辑 -->
        <ResizableTextarea
          v-model="input"
          :disabled="streaming"
          :readonly="voiceRecording"
          maxlength="5000"
          placeholder="输入你的作答（Ctrl + Enter 提交）"
          @submit="submitAnswer"
        />
        <div class="chat__actions">
          <el-popconfirm
            :title="finishTitle"
            confirm-button-text="确认结束"
            cancel-button-text="继续作答"
            width="260"
            @confirm="goReview"
          >
            <template #reference>
              <el-button
                link
                class="chat__finish"
                :disabled="streaming || voiceRecording"
                :title="finishHint"
              >
                结束本场
              </el-button>
            </template>
          </el-popconfirm>
          <el-popconfirm
            title="跳过本题？不计分，直接进入下一题"
            confirm-button-text="跳过"
            cancel-button-text="取消"
            width="240"
            @confirm="skip"
          >
            <template #reference>
              <el-button :disabled="streaming || voiceRecording">跳过</el-button>
            </template>
          </el-popconfirm>
          <el-button type="primary" :disabled="!canSubmit" :loading="streaming" @click="submitAnswer">
            提交
          </el-button>
        </div>
      </template>
    </footer>

    <div v-else class="chat__done">
      <el-icon class="chat__done-icon"><CircleCheck /></el-icon>
      <div class="chat__done-text">
        <p class="chat__done-title">本场面试已完成</p>
        <p class="chat__done-sub">共 {{ session?.question_count }} 题 · 本场记录已保存</p>
      </div>
      <el-button type="primary" @click="goReview">查看总结报告</el-button>
      <el-button @click="backToList">返回列表</el-button>
    </div>
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
  padding: 13px var(--card-padding);
  border-bottom: 1px solid var(--c-divider);
  /* 页头一层模块色微渐变：和「面试进行中」的状态呼应，不做其他装饰 */
  background: linear-gradient(
    180deg,
    color-mix(in srgb, var(--m-interview) 6%, var(--c-card)),
    var(--c-card) 90%
  );
}
.chat__title {
  font-size: var(--fs-title);
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
/* 强度标签：中性色——与方向（模块色）、阶段（主色）都不抢位 */
.chat__intensity {
  flex: 0 0 auto;
  padding: 1px 8px;
  font-size: var(--fs-xs);
  color: var(--c-text-2);
  background: var(--c-bg);
  border-radius: var(--r-mark);
}
/* 阶段标签：与方向标签区分——阶段是「流程位置」，用主色；方向是「面试范围」，用模块色 */
.chat__stage {
  flex: 0 0 auto;
  padding: 1px 8px;
  font-size: var(--fs-xs);
  font-weight: 600;
  color: var(--brand);
  background: color-mix(in srgb, var(--brand) 10%, var(--c-card));
  border-radius: var(--r-mark);
}
.chat__progress {
  margin-left: auto;
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: 10px;
}
.chat__progress-text {
  font-size: var(--fs-sm);
  color: var(--c-text-2);
  font-variant-numeric: tabular-nums;
}
/* 进度条：一眼知道「还有几题」，比纯数字更有推进感 */
.chat__progress-bar {
  width: 110px;
  height: 4px;
  border-radius: var(--r-bar);
  background: var(--c-divider);
  overflow: hidden;
}
.chat__progress-bar i {
  display: block;
  height: 100%;
  border-radius: var(--r-bar);
  background: var(--m-interview);
  transition: width 0.3s ease;
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
  align-items: center;
  gap: 8px;
  margin-top: 8px;
  /* 给右下角的 AI 助手悬浮球让位（球固定占 right 24~82px，实测按钮组右端恒压住球左侧约 28px） */
  padding-right: 48px;
}
/* 「结束本场」推到最左并弱化：低频且有代价的动作，别和「提交」抢注意力 */
.chat__finish.el-button {
  margin-right: auto;
  color: var(--c-text-3);
  font-size: var(--fs-sm);
}
.chat__finish.el-button:hover:not(.is-disabled) {
  color: var(--c-text-2);
}
.chat__preparing {
  margin: 0;
  padding: 4px 0;
  font-size: var(--fs-sm);
  color: var(--c-text-2);
}
/* 完成卡：答满后的落点——完成感 + 明确的下一步（总结报告），而不只是一行灰字 */
.chat__done {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 18px var(--card-padding);
  border-top: 1px solid var(--c-divider);
  background: linear-gradient(
    180deg,
    var(--c-card),
    color-mix(in srgb, var(--m-interview) 7%, var(--c-card))
  );
}
.chat__done-icon {
  font-size: 30px;
  color: var(--m-interview);
}
.chat__done-text {
  flex: 1;
  min-width: 0;
}
.chat__done-title {
  margin: 0;
  font-size: var(--fs-title);
  font-weight: 600;
  color: var(--c-text);
}
.chat__done-sub {
  margin: 4px 0 0;
  font-size: var(--fs-sm);
  color: var(--c-text-3);
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
