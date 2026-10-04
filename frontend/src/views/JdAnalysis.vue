<script setup>
/**
 * JD 匹配分析（SRS FR-006 / 接口文档 §3.6）：粘贴 JD → 流式五段报告 → 历史回看。
 *
 * 报告区直接渲染**全文**——接口文档约定「段落标题行随 `delta` 原样下发、report_text 恒等于
 * 全部 delta 拼接」，若按 section 重新拼装会让标题重复；`section` 只用来显示当前生成进度。
 */
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import StreamText from '../components/StreamText.vue'
import { streamSSE } from '../utils/sse'
import { listReports, getReport } from '../api/jdReports'
import { listApplications } from '../api/applications'
import { shortDateTime } from '../utils/datetime'
import AppEmpty from '../components/AppEmpty.vue'

// section 标识 → 中文名（五段固定，接口文档 §3.6）
const SECTION_LABELS = {
  match_score: '综合匹配度评分',
  scores: '分项评分',
  strengths: '优势分析',
  gaps: '差距分析',
  advice: '提升建议'
}

const JD_MAX = 10000
const PAGE_SIZE = 10

// 等待期间的安抚文案（台账 #65）：**首字出现前**按总时长递进，说明「为什么慢」——
// AI 是逐字生成整篇报告的，长报告确实要花时间，不是卡住了。从大到小排，取首个命中的档位。
const WAIT_HINTS = [
  { at: 30000, text: '仍在生成中，可继续等待，或稍后重试' },
  { at: 15000, text: '报告较长时可能需要 20~60 秒，AI 正在逐字生成' },
  { at: 3000, text: '正在逐字生成中，请稍候…' }
]
// 兜底面板阈值：等待超过它就给出口（重试 / 换模型）。
// **前端不主动断流**——后端已负责静默超时（8s 无数据重试 1 次后抛 10010），
// 这里覆盖的是「一直在出字、但整篇太久」那类场景，内容仍在增长时用户可以无视面板继续等。
const TIMEOUT_MS = 60000

const router = useRouter()
const route = useRoute()

const jdText = ref('')
const applicationId = ref(null)
const applications = ref([])
const prefillHint = ref('') // 校招情报带过来的说明（有原文 / 需粘贴）

const streaming = ref(false)
const reportText = ref('')
const startMessage = ref('')
const currentSection = ref('')
const errorMsg = ref('')
const waitHint = ref('')
const timeoutPanel = ref(false)
const runMeta = ref(null) // 本次生成的耗时指标（done.extra：字数 / 首字 / 总耗时）

const reports = ref([])
const total = ref(0)
const page = ref(1)
const detail = ref(null) // 历史详情；非空时右区展示详情而非流式报告
// 详情头部的公司名取自**列表项**：详情接口（JdReportDTO）没有 company 字段，
// 只有列表项（JdReportListItem）带该联表字段（接口文档 §3.6）——直接读详情会恒落兜底文案
const detailCompany = ref('')

let controller = null
let phaseTimer = null
let firstTokenSeen = false

/** 启动等待计时（从点「开始分析」起算）：分档文案 + 兜底面板。 */
function startWaitTimer() {
  stopWaitTimer()
  firstTokenSeen = false
  waitHint.value = ''
  timeoutPanel.value = false
  const startedAt = Date.now()
  phaseTimer = setInterval(() => {
    const elapsed = Date.now() - startedAt
    if (!firstTokenSeen) {
      const hit = WAIT_HINTS.find((h) => elapsed >= h.at)
      waitHint.value = hit ? hit.text : ''
    }
    if (elapsed >= TIMEOUT_MS) timeoutPanel.value = true
  }, 1000)
}

/** 撤掉等待文案与兜底面板（已有内容产出，或流程结束）。 */
function stopWaitTimer() {
  if (phaseTimer !== null) {
    clearInterval(phaseTimer)
    phaseTimer = null
  }
  waitHint.value = ''
  timeoutPanel.value = false
}

const sectionLabel = computed(() => SECTION_LABELS[currentSection.value] || '')
/** 选了投递时 JD 可不填（后端自动取该投递的 jd_text）；未选投递则必填。 */
const canStart = computed(
  () => !streaming.value && (jdText.value.trim().length > 0 || !!applicationId.value)
)
const overLimit = computed(() => jdText.value.length > JD_MAX)

/** 耗时行文案：本次耗时（首字 · 字数）——供使用者横向对比不同模型的响应速度。 */
const runMetaText = computed(() => {
  const m = runMeta.value
  if (!m || m.elapsed_ms == null) return ''
  const sec = (ms) => (ms / 1000).toFixed(1)
  const parts = []
  if (m.first_token_ms != null) parts.push(`首字 ${sec(m.first_token_ms)} 秒`)
  if (m.chars != null) parts.push(`共 ${m.chars} 字`)
  return `本次耗时 ${sec(m.elapsed_ms)} 秒${parts.length ? `（${parts.join(' · ')}）` : ''}`
})

async function loadApplications() {
  // 关联投递下拉：取前 50 条即可（自用场景投递量不大，不做远程搜索）
  const data = await listApplications({ page: 1, page_size: 50 })
  applications.value = data.items || []
}

async function loadReports() {
  const data = await listReports({ page: page.value, page_size: PAGE_SIZE })
  reports.value = data.items || []
  total.value = data.total || 0
}

async function openDetail(item) {
  detailCompany.value = item.company || ''
  detail.value = await getReport(item.id)
  // 详情与流式互斥，避免两块文本叠在一起
  reportText.value = ''
  startMessage.value = ''
  currentSection.value = ''
  errorMsg.value = ''
}

function backToInput() {
  detail.value = null
}

function start() {
  if (!canStart.value) return
  if (overLimit.value) {
    ElMessage.warning(`JD 原文不能超过 ${JD_MAX} 字`)
    return
  }
  streaming.value = true
  detail.value = null
  reportText.value = ''
  startMessage.value = ''
  currentSection.value = ''
  errorMsg.value = ''
  runMeta.value = null
  startWaitTimer()

  controller = streamSSE(
    '/stream/jd-analysis',
    // jd_text 条件必填：选了投递且未手填时不传该字段（后端自动取投递的 JD）；
    // 未选投递时不传 application_id（后端按未关联处理；传 null 会被判成非法值）
    {
      ...(jdText.value.trim() ? { jd_text: jdText.value } : {}),
      ...(applicationId.value ? { application_id: applicationId.value } : {})
    },
    {
      onStart: (d) => {
        startMessage.value = d.message
      },
      onDelta: (d) => {
        // 出字即撤安抚文案（用户已看到内容在长），但计时不停——60 秒兜底看的是总时长
        firstTokenSeen = true
        waitHint.value = ''
        reportText.value += d.text
        if (d.section) currentSection.value = d.section
      },
      onDone: (d) => {
        stopWaitTimer()
        streaming.value = false
        startMessage.value = ''
        currentSection.value = ''
        runMeta.value = d.extra || null // 耗时指标，供横向对比不同模型（接口文档 §3.6）
        loadReports() // 已落库，刷新列表
      },
      onError: (e) => {
        stopWaitTimer()
        streaming.value = false
        errorMsg.value = e.message
      }
    }
  )
}

/** 兜底面板的「重试」：中止本次（已生成内容按断连口径落库）后立即重发。 */
function retry() {
  abort()
  start()
}

function goAiConfig() {
  router.push('/ai-config')
}

function abort() {
  controller?.abort()
  stopWaitTimer()
  streaming.value = false
  startMessage.value = ''
  currentSection.value = ''
  runMeta.value = null
  // 断连会把已生成内容落库（接口文档 §3.6：与完整报告同一口径），刷新即可看到半成品
  loadReports()
}

function changePage(delta) {
  const next = page.value + delta
  if (next < 1 || (next - 1) * PAGE_SIZE >= total.value) return
  page.value = next
  loadReports()
}

/**
 * 校招情报「分析匹配度」带 query 跳转过来（Campus.vue 的 onAnalyze）：
 * 有暂存的投喂原文就直接填进 JD 输入框；自动抓取的岗位没有正文（NFR-016 只存元数据），
 * 提示用户粘贴后再分析。消费完清掉 query，避免刷新时重复带入。
 */
function consumeQueryPrefill() {
  const query = route.query
  const jd = typeof query.jd_text === 'string' ? query.jd_text.trim() : ''
  const position = typeof query.position === 'string' ? query.position.trim() : ''
  const company = typeof query.company === 'string' ? query.company.trim() : ''
  if (!jd && !position && !company) return
  if (jd) {
    jdText.value = jd.slice(0, JD_MAX)
    prefillHint.value = `已从校招情报带入「${company}${company && position ? ' · ' : ''}${position}」的 JD 原文`
  } else {
    prefillHint.value = `${company}${company && position ? ' · ' : ''}${position} 没有可带入的 JD 原文（自动抓取只存元数据），请粘贴 JD 后再分析`
  }
  router.replace({ path: '/jd-analysis' })
}

onMounted(() => {
  consumeQueryPrefill()
  loadApplications()
  loadReports()
})

onUnmounted(() => {
  stopWaitTimer() // 切页时定时器不能留
})
</script>

<template>
  <div class="jd">
    <!-- 左栏：输入 + 历史 -->
    <aside class="jd__side">
      <section class="jd__card">
        <h3 class="jd__card-title dot-title">粘贴 JD</h3>
        <p v-if="prefillHint" class="jd__prefill">{{ prefillHint }}</p>
        <el-input
          v-model="jdText"
          type="textarea"
          :rows="8"
          :maxlength="JD_MAX"
          show-word-limit
          :disabled="streaming"
          placeholder="把岗位描述整段粘进来；关联投递后可留空（自动取该投递的 JD）"
        />
        <el-select
          v-model="applicationId"
          class="jd__select"
          clearable
          filterable
          :disabled="streaming"
          placeholder="关联投递（可选；选了可不填 JD）"
        >
          <el-option
            v-for="item in applications"
            :key="item.id"
            :label="`${item.company} · ${item.position}`"
            :value="item.id"
          />
        </el-select>
        <div class="jd__actions">
          <el-button type="primary" :disabled="!canStart" @click="start">开始分析</el-button>
          <el-button v-if="streaming" @click="abort">中止</el-button>
        </div>
      </section>

      <section class="jd__card">
        <h3 class="jd__card-title dot-title">历史报告</h3>
        <AppEmpty
          v-if="!reports.length"
          type="jd"
          size="sm"
          title="还没有分析记录"
          description="粘贴 JD 生成第一份报告"
          style="--empty-color: var(--m-jd)"
        />
        <ul v-else class="jd__list">
          <li
            v-for="item in reports"
            :key="item.id"
            class="jd__list-item"
            :class="{ 'jd__list-item--active': detail && detail.id === item.id }"
            @click="openDetail(item)"
          >
            <div class="jd__list-main">
              <span class="jd__list-company">{{ item.company || '未关联投递' }}</span>
              <span v-if="item.is_finished === false" class="jd__tag">未完成</span>
              <span v-else class="jd__list-score">{{ item.score }} 分</span>
            </div>
            <span class="jd__list-time">{{ shortDateTime(item.created_at) }}</span>
          </li>
        </ul>
        <div v-if="total > PAGE_SIZE" class="jd__pager">
          <el-button size="small" :disabled="page === 1" @click="changePage(-1)">上一页</el-button>
          <span class="jd__pager-text">{{ page }} / {{ Math.ceil(total / PAGE_SIZE) }}</span>
          <el-button size="small" :disabled="page * PAGE_SIZE >= total" @click="changePage(1)">
            下一页
          </el-button>
        </div>
      </section>
    </aside>

    <!-- 右区：流式报告 / 历史详情 -->
    <main class="jd__main">
      <div v-if="detail" class="jd__report">
        <header class="jd__report-head">
          <span class="jd__report-title">
            {{ detailCompany || '未关联投递' }} · {{ detail.score ?? '—' }} 分
          </span>
          <div class="jd__report-head-right">
            <span class="jd__report-time">{{ shortDateTime(detail.created_at) }}</span>
            <el-button size="small" @click="backToInput">返回</el-button>
          </div>
        </header>
        <el-collapse class="jd__jd-snapshot">
          <el-collapse-item title="查看当时的 JD 原文" name="jd">
            <pre class="jd__jd-text">{{ detail.jd_text }}</pre>
          </el-collapse-item>
        </el-collapse>
        <div class="jd__report-body">{{ detail.report_text }}</div>
      </div>

      <div v-else class="jd__report">
        <div v-if="startMessage || sectionLabel || waitHint" class="jd__progress">
          <span>{{ startMessage }}</span>
          <span v-if="waitHint" class="jd__progress-hint">{{ waitHint }}</span>
          <span v-if="sectionLabel" class="jd__progress-section">正在生成：{{ sectionLabel }}</span>
        </div>
        <el-alert v-if="errorMsg" :title="errorMsg" type="error" :closable="false" />
        <!-- 等待超 60 秒的兜底出口（台账 #65）：流仍在继续，故不撤内容、不主动断流——
             内容仍在增长时可无视面板继续等，也可重试或去换更快的模型 -->
        <div v-if="timeoutPanel && streaming" class="jd__timeout">
          <p class="jd__timeout-title">生成时间较长</p>
          <p class="jd__timeout-desc">
            已等待超过 60 秒。AI 是逐字生成整篇报告的，长报告确实要花些时间——若下方内容仍在增长，
            可以继续等待。
          </p>
          <div class="jd__timeout-actions">
            <el-button size="small" type="primary" @click="retry">重试</el-button>
            <el-button size="small" @click="goAiConfig">前往 AI 配置页</el-button>
          </div>
          <p class="jd__timeout-reasons">
            可能原因：模型生成速度慢 / 网络不稳定 / 密钥额度不足 / 供应商限流
          </p>
        </div>
        <div v-if="reportText || streaming" class="jd__report-body">
          <StreamText :text="reportText" :streaming="streaming" />
        </div>
        <p v-if="runMetaText" class="jd__report-meta">{{ runMetaText }}</p>
        <!-- 空态的条件**显式写出**、不用 v-else：上面的耗时行是新增的兄弟节点，
             若沿用 v-else，它会在生成中（有内容、尚无耗时）与内容并显 -->
        <AppEmpty
          v-if="!reportText && !streaming"
          type="jd"
          description="粘贴一份 JD 开始分析，或从左侧选择历史报告"
          style="--empty-color: var(--m-jd)"
        />
      </div>
    </main>
  </div>
</template>

<style scoped>
.jd {
  display: grid;
  grid-template-columns: 320px minmax(0, 1fr);
  gap: 16px;
  align-items: start;
}
.jd__side {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.jd__card {
  padding: 14px;
  border: 1px solid var(--c-border);
  border-radius: var(--r-card);
  background: var(--c-card);
}
.jd__card-title {
  margin: 0 0 10px;
  font-size: var(--fs-title);
  font-weight: 600;
  color: var(--c-text);
}
.jd__prefill {
  margin: 0 0 8px;
  padding: 6px 10px;
  font-size: var(--fs-sm);
  color: var(--c-text-2);
  background: color-mix(in srgb, var(--m-campus) 10%, var(--c-card));
  border-radius: var(--r-mark);
}
.jd__select {
  width: 100%;
  margin-top: 10px;
}
.jd__actions {
  display: flex;
  gap: 8px;
  margin-top: 10px;
}
.jd__list {
  margin: 0;
  padding: 0;
  list-style: none;
  max-height: 420px;
  overflow-y: auto;
}
.jd__list-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 8px 10px;
  border-radius: var(--r-menu);
  cursor: pointer;
  transition: background 0.15s ease;
}
.jd__list-item:hover {
  background: var(--c-bg);
}
.jd__list-item--active {
  background: var(--c-bg);
  box-shadow: inset 2px 0 0 var(--m-jd);
}
.jd__list-main {
  display: flex;
  align-items: center;
  gap: 6px;
}
.jd__list-company {
  flex: 1;
  overflow: hidden;
  font-size: var(--fs-body);
  color: var(--c-text);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.jd__list-score {
  font-size: var(--fs-body);
  font-weight: 600;
  color: var(--m-jd);
}
.jd__tag {
  padding: 0 6px;
  border-radius: var(--r-mark);
  background: var(--c-bg);
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}
.jd__list-time {
  font-size: var(--fs-sm);
  color: var(--c-text-3);
}
.jd__pager {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 10px;
}
.jd__pager-text {
  font-size: var(--fs-sm);
  color: var(--c-text-3);
}
.jd__main {
  min-width: 0;
}
.jd__report {
  padding: 16px 18px;
  border: 1px solid var(--c-border);
  border-radius: var(--r-card);
  background: var(--c-card);
  min-height: 420px;
}
.jd__report-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}
.jd__report-title {
  font-size: var(--fs-title);
  font-weight: 600;
  color: var(--c-text);
}
.jd__report-head-right {
  display: flex;
  align-items: center;
  gap: 10px;
}
.jd__report-time {
  font-size: var(--fs-sm);
  color: var(--c-text-3);
}
.jd__jd-snapshot {
  margin-bottom: 10px;
}
.jd__jd-text {
  margin: 0;
  max-height: 220px;
  overflow: auto;
  font-family: inherit;
  font-size: var(--fs-sm);
  line-height: 1.6;
  color: var(--c-text-2);
  white-space: pre-wrap;
}
.jd__progress {
  display: flex;
  gap: 12px;
  margin-bottom: 10px;
  font-size: var(--fs-body);
  color: var(--c-text-2);
}
.jd__progress-hint {
  color: var(--c-text-3);
}
.jd__progress-section {
  color: var(--m-jd);
}
.jd__report-body {
  font-size: var(--fs-title);
  line-height: 1.8;
  color: var(--c-text);
  white-space: pre-wrap;
  word-break: break-word;
}
/* 生成耗时（本次耗时 / 首字 / 字数）：生成结束后的一行小字，供横向对比模型 */
.jd__report-meta {
  margin: 12px 0 0;
  font-size: var(--fs-sm);
  color: var(--c-text-3);
}
/* 等待超时的兜底面板：内容仍在渲染，故用「提示」而非「错误」的视觉 */
.jd__timeout {
  margin-bottom: 10px;
  padding: 12px 14px;
  border: 1px solid var(--el-color-warning-light-5);
  border-radius: var(--r-control);
  background: var(--el-color-warning-light-9);
}
.jd__timeout-title {
  margin: 0 0 6px;
  font-size: var(--fs-body);
  font-weight: 600;
  color: var(--c-text);
}
.jd__timeout-desc {
  margin: 0 0 10px;
  font-size: var(--fs-sm);
  line-height: 1.7;
  color: var(--c-text-2);
}
.jd__timeout-actions {
  display: flex;
  gap: 8px;
  margin-bottom: 8px;
}
.jd__timeout-reasons {
  margin: 0;
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}
</style>
