<script setup>
/**
 * 练习模式·题目详情（FR-020 / 接口文档 §3.15）。
 *
 * 一页承担三件事：**继续练**（作答区，语音 / 文字两态，提交走 `/stream/drill-review`）、
 * **看进步**（`ProgressPanel`：最近 vs 上一次 + 趋势折线）、**看历史**（时间线 → 抽屉看单次完整点评）。
 *
 * 作答区与面试页同款件同口径（VoiceInput + ResizableTextarea + segments 上报），差别在提交后：
 * 本地先乐观插一条「第 N 遍」（`streaming` 态），`done` 回填记录 id / 遍次 / 表达力指标，
 * 再拉一次服务端数据对齐。
 *
 * 表达力指标**先于点评**到（`done` 一次性下发）——指标卡与流式点评并排出现，与面试页一致。
 * 归档题：作答区换成提示，历史与对比照常看。
 */
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Back, Edit, Files } from '@element-plus/icons-vue'
import { drillReviewStream, getDrill, getDrillProgress, updateDrill } from '../api/drill'
import { getSettingsApi } from '../api/settings'
import { useAppStore } from '../stores/app'
import { sourceLabel } from '../utils/drillMeta'
import { applyDelta, applyDone, createAttempt, reviewBody } from '../utils/drillStream'
import { addSegment, toSegmentsPayload } from '../utils/voiceSegments'
import MetricsCard from '../components/interview/MetricsCard.vue'
import StreamText from '../components/StreamText.vue'
import ResizableTextarea from '../components/ResizableTextarea.vue'
import VoiceInput from '../components/VoiceInput.vue'
import ProgressPanel from '../components/drill/ProgressPanel.vue'
import AttemptTimeline from '../components/drill/AttemptTimeline.vue'
import AttemptDrawer from '../components/drill/AttemptDrawer.vue'

const route = useRoute()
const router = useRouter()
const topicId = Number(route.params.topicId)

const topic = ref(null)
const progress = ref(null)
const loading = ref(true)
const errorMsg = ref('')

/** 正在流式的这一遍（本地乐观插入的视图模型；未在流式时为 null）。 */
const live = ref(null)
const streaming = ref(false)
let stream = null
let lastPayload = null

const input = ref('')
const voiceEnabled = ref(false)
const voiceRecording = ref(false)
const voiceRef = ref(null)
const appStore = useAppStore()
let segments = []
/** 首次交互时刻（首次输入 / 开麦）——`duration_ms` 的计时起点。 */
let startedAt = null

const drawerVisible = ref(false)
const drawerAttemptId = ref(null)

const editVisible = ref(false)
const editForm = ref({ title: '', question: '' })
const savingEdit = ref(false)

const archived = computed(() => !!topic.value?.archived)
const attempts = computed(() => topic.value?.attempts || [])

const canSubmit = computed(
  () => !streaming.value && !archived.value && !voiceRecording.value && input.value.trim().length > 0
)

async function load() {
  loading.value = true
  errorMsg.value = ''
  try {
    const [detail, prog] = await Promise.all([getDrill(topicId), getDrillProgress(topicId)])
    topic.value = detail
    progress.value = prog
  } catch (error) {
    errorMsg.value = error?.message || '题目加载失败，请返回列表重试'
  } finally {
    loading.value = false
  }
}

async function loadSettings() {
  try {
    const data = await getSettingsApi({ silent: true })
    appStore.setSettings(data)
    voiceEnabled.value = !!data.voice_enabled
  } catch {
    voiceEnabled.value = !!appStore.settings.voice_enabled
  }
}

/** 首次交互记账（计时起点，只记第一次）。 */
function markStart() {
  if (startedAt == null) startedAt = Date.now()
}

function onVoiceAppend({ text, startMs, endMs }) {
  const t = String(text ?? '').trim()
  if (!t) return
  input.value = input.value ? `${input.value}${t}` : t
  addSegment(segments, { text: t, startMs, endMs })
}

function onVoiceRecording(v) {
  voiceRecording.value = v
  if (v) markStart()
}

// 计时起点：作答框一有内容（手打第一字 / 语音回填第一句）就算开始；
// 提交后清空输入不会误触发（空串不记）
watch(input, (value) => {
  if (value) markStart()
})

function submitAnswer() {
  if (!canSubmit.value) return
  const text = input.value.trim()
  const isVoice = segments.length > 0
  const payload = { topic_id: topicId, answer: text, is_voice: isVoice }
  const segs = toSegmentsPayload(segments)
  if (segs) payload.segments = segs
  if (startedAt != null) payload.duration_ms = Date.now() - startedAt
  input.value = ''
  segments = []
  startedAt = null
  voiceRef.value?.reset()
  requestReview(payload, text, isVoice)
}

/** 发一次点评流：先插一条乐观记录，再按 delta 累进。 */
function requestReview(payload, answer, isVoice) {
  lastPayload = payload
  streaming.value = true
  const attempt = createAttempt()
  live.value = {
    ...attempt,
    seq: attempts.value.length + 1,
    answer,
    is_voice: isVoice ? 1 : 0,
    duration_ms: payload.duration_ms ?? null,
    created_at: new Date().toISOString(),
    streaming: true
  }
  stream = drillReviewStream(payload, {
    onDelta: (d) => {
      applyDelta(live.value, d)
      // 响应式：`live` 是 ref 包的对象，字段原地变更即可触发渲染（Vue 3 深度响应）
    },
    onDone: (d) => {
      applyDone(live.value, d)
      live.value.streaming = false
      streaming.value = false
      live.value = null
      load() // 服务端数据为准（记录已落库，进度与列表一并刷新）
    },
    onError: (e) => {
      streaming.value = false
      errorMsg.value =
        e?.code === 40003
          ? '该题目已归档，恢复后可继续练习'
          : e?.message || '点评生成中断，请重试'
      if (e?.code === 40003) load()
    }
  })
}

function retry() {
  if (lastPayload) requestReview(lastPayload, lastPayload.answer, !!lastPayload.is_voice)
}

/** 归档 / 恢复：二次确认后部分更新，并刷新列表数据。 */
async function toggleArchive() {
  const going = !archived.value
  try {
    await ElMessageBox.confirm(
      going
        ? '归档后默认列表不再展示，也不能再作答；历史记录与进步对比仍可查看。'
        : '恢复后可以继续练习这道题。',
      going ? '归档这道题？' : '恢复这道题？',
      { confirmButtonText: going ? '归档' : '恢复', cancelButtonText: '取消', width: '300px' }
    )
  } catch {
    return
  }
  try {
    await updateDrill(topicId, { archived: going })
    ElMessage.success(going ? '已归档' : '已恢复')
    load()
  } catch (error) {
    ElMessage.error(error?.message || '操作失败，请稍后重试')
  }
}

function openEdit() {
  editForm.value = { title: topic.value.title, question: topic.value.question }
  editVisible.value = true
}

async function saveEdit() {
  const title = editForm.value.title.trim()
  if (!title) {
    ElMessage.warning('标题不能为空')
    return
  }
  if (title.length > 50) {
    ElMessage.warning('标题不超过 50 字')
    return
  }
  savingEdit.value = true
  try {
    await updateDrill(topicId, { title, question: editForm.value.question.trim() })
    ElMessage.success('已保存')
    editVisible.value = false
    load()
  } catch (error) {
    ElMessage.error(error?.message || '保存失败，请稍后重试')
  } finally {
    savingEdit.value = false
  }
}

function openAttempt(attempt) {
  drawerAttemptId.value = attempt.id
  drawerVisible.value = true
}

onMounted(() => {
  load()
  loadSettings()
})

onUnmounted(() => {
  stream?.abort()
})
</script>

<template>
  <section v-loading="loading" class="detail">
    <header class="detail__head">
      <el-button link :icon="Back" @click="router.push('/drill')">返回列表</el-button>
      <span class="detail__title">{{ topic?.title || '加载中…' }}</span>
      <span v-if="topic" class="detail__source">{{ sourceLabel(topic.source) }}</span>
      <span v-if="archived" class="detail__archived">已归档</span>
      <div v-if="topic" class="detail__tools">
        <el-button link :icon="Edit" @click="openEdit">编辑</el-button>
        <el-button link :icon="Files" @click="toggleArchive">{{ archived ? '恢复' : '归档' }}</el-button>
      </div>
    </header>

    <p v-if="errorMsg" class="detail__error">
      <span>{{ errorMsg }}</span>
      <el-button v-if="lastPayload && !streaming" size="small" @click="retry">重试</el-button>
    </p>

    <div v-if="topic" class="detail__question">
      <span class="detail__question-label">题面</span>
      <p class="detail__question-text">{{ topic.question }}</p>
    </div>

    <div v-if="topic" class="detail__practice">
      <template v-if="archived">
        <p class="detail__archived-hint">这道题已归档——恢复后可以继续练习，历史记录与对比不受影响。</p>
      </template>
      <template v-else>
        <p class="detail__practice-title">继续练 · 第 {{ attempts.length + 1 }} 遍</p>
        <VoiceInput
          v-if="voiceEnabled"
          ref="voiceRef"
          :disabled="streaming"
          @append="onVoiceAppend"
          @recording="onVoiceRecording"
        />
        <ResizableTextarea
          v-model="input"
          :disabled="streaming"
          :readonly="voiceRecording"
          maxlength="5000"
          placeholder="把这一遍讲出来（Ctrl + Enter 提交）"
          @submit="submitAnswer"
        />
        <div class="detail__actions">
          <span class="detail__hint">语音作答会额外给出语速 / 填充词 / 停顿等表达指标</span>
          <el-button type="primary" :disabled="!canSubmit" :loading="streaming" @click="submitAnswer">
            提交这一遍
          </el-button>
        </div>
      </template>
    </div>

    <div v-if="live" class="detail__live">
      <div class="detail__live-head">
        <span class="detail__live-title">第 {{ live.seq }} 遍</span>
        <span v-if="live.score != null" class="detail__live-score">{{ live.score }}<i>分</i></span>
      </div>
      <MetricsCard v-if="live.voiceMetrics" :metrics="live.voiceMetrics" />
      <div class="detail__live-review">
        <span class="detail__live-label">点评</span>
        <StreamText v-if="live.streaming" :text="reviewBody(live)" :streaming="true" />
        <span v-else class="detail__live-static">{{ reviewBody(live) }}</span>
      </div>
    </div>

    <ProgressPanel v-if="topic" :progress="progress" />

    <AttemptTimeline
      v-if="topic"
      :attempts="attempts"
      :live-seq="live?.seq ?? null"
      @open="openAttempt"
    />

    <AttemptDrawer v-model="drawerVisible" :topic-id="topicId" :attempt-id="drawerAttemptId" />

    <el-dialog v-model="editVisible" title="编辑题目" width="560px">
      <el-form label-width="60px">
        <el-form-item label="标题">
          <el-input v-model="editForm.title" maxlength="50" show-word-limit />
        </el-form-item>
        <el-form-item label="题面">
          <el-input v-model="editForm.question" type="textarea" :rows="5" maxlength="2000" show-word-limit />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button :disabled="savingEdit" @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="savingEdit" @click="saveEdit">保存</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<style scoped>
.detail__head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;
}
.detail__title {
  font-size: var(--fs-page);
  font-weight: 700;
  color: var(--c-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.detail__source,
.detail__archived {
  flex: 0 0 auto;
  padding: 1px 8px;
  font-size: var(--fs-xs);
  border-radius: var(--r-mark);
}
.detail__source {
  color: var(--m-drill);
  background: color-mix(in srgb, var(--m-drill) 12%, var(--c-card));
}
.detail__archived {
  color: var(--c-text-3);
  background: var(--c-bg);
}
.detail__tools {
  margin-left: auto;
  display: flex;
  gap: 4px;
}

.detail__error {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 0 0 12px;
  padding: 8px 12px;
  font-size: var(--fs-sm);
  color: var(--el-color-danger);
  background: var(--el-color-danger-light-9);
  border-radius: var(--r-card);
}

.detail__question {
  padding: 14px var(--card-padding);
  background: var(--c-card);
  border: 1px solid var(--c-border);
  border-left: 3px solid var(--m-drill);
  border-radius: var(--r-card);
}
.detail__question-label {
  font-size: var(--fs-xs);
  font-weight: 600;
  color: var(--m-drill);
}
.detail__question-text {
  margin: 6px 0 0;
  font-size: var(--fs-body);
  line-height: 1.8;
  color: var(--c-text);
  white-space: pre-wrap;
  word-break: break-word;
}

.detail__practice {
  margin-top: var(--card-gap);
  padding: 14px var(--card-padding);
  background: var(--c-card);
  border: 1px solid var(--c-border);
  border-radius: var(--r-card);
}
.detail__practice-title {
  margin: 0 0 10px;
  font-size: var(--fs-sm);
  font-weight: 600;
  color: var(--c-text);
}
.detail__archived-hint {
  margin: 0;
  font-size: var(--fs-sm);
  color: var(--c-text-2);
}
.detail__actions {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 10px;
}
.detail__hint {
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}
.detail__actions .el-button {
  margin-left: auto;
}

.detail__live {
  margin-top: var(--card-gap);
  padding: 14px var(--card-padding);
  border: 1px dashed color-mix(in srgb, var(--m-drill) 45%, var(--c-card));
  border-radius: var(--r-card);
  background: color-mix(in srgb, var(--m-drill) 4%, var(--c-card));
}
.detail__live-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}
.detail__live-title {
  font-size: var(--fs-sm);
  font-weight: 600;
  color: var(--m-drill);
}
.detail__live-score {
  margin-left: auto;
  font-size: 20px;
  font-weight: 700;
  color: var(--m-drill);
}
.detail__live-score i {
  font-size: var(--fs-xs);
  font-style: normal;
  font-weight: 400;
  margin-left: 2px;
}
.detail__live-review {
  margin-top: 8px;
  font-size: var(--fs-body);
  line-height: 1.8;
  color: var(--c-text);
}
.detail__live-label {
  display: block;
  margin-bottom: 4px;
  font-size: var(--fs-xs);
  font-weight: 600;
  color: var(--c-text-3);
}
.detail__live-static {
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
