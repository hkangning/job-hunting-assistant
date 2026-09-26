<script setup>
/**
 * JD 匹配分析（SRS FR-006 / 接口文档 §3.6）：粘贴 JD → 流式五段报告 → 历史回看。
 *
 * 报告区直接渲染**全文**——接口文档约定「段落标题行随 `delta` 原样下发、report_text 恒等于
 * 全部 delta 拼接」，若按 section 重新拼装会让标题重复；`section` 只用来显示当前生成进度。
 */
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import StreamText from '../components/StreamText.vue'
import { streamSSE } from '../utils/sse'
import { listReports, getReport } from '../api/jdReports'
import { listApplications } from '../api/applications'
import { shortDateTime } from '../utils/datetime'

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

const jdText = ref('')
const applicationId = ref(null)
const applications = ref([])

const streaming = ref(false)
const reportText = ref('')
const startMessage = ref('')
const currentSection = ref('')
const errorMsg = ref('')
const slowHint = ref(false) // 首字迟迟不来时的安抚提示（IS-31：实测 2.4~8s）

const reports = ref([])
const total = ref(0)
const page = ref(1)
const detail = ref(null) // 历史详情；非空时右区展示详情而非流式报告

let controller = null
let slowTimer = null

/** 撤掉「请耐心等待」提示（已有内容产出，或流程结束）。 */
function clearSlowHint() {
  if (slowTimer !== null) {
    clearTimeout(slowTimer)
    slowTimer = null
  }
  slowHint.value = false
}

const sectionLabel = computed(() => SECTION_LABELS[currentSection.value] || '')
const canStart = computed(() => !streaming.value && jdText.value.trim().length > 0)
const overLimit = computed(() => jdText.value.length > JD_MAX)

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

async function openDetail(id) {
  detail.value = await getReport(id)
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
  clearSlowHint()
  streaming.value = true
  detail.value = null
  reportText.value = ''
  startMessage.value = ''
  currentSection.value = ''
  errorMsg.value = ''

  controller = streamSSE(
    '/stream/jd-analysis',
    // 未选投递时不传该字段（后端按未关联处理；传 null 会被判成非法值）
    { jd_text: jdText.value, ...(applicationId.value ? { application_id: applicationId.value } : {}) },
    {
      onStart: (d) => {
        startMessage.value = d.message
        // 首字延迟实测 2.4~8s（IS-31）：等久了补一句安抚，出字即撤
        slowTimer = setTimeout(() => {
          slowHint.value = true
        }, 3000)
      },
      onDelta: (d) => {
        clearSlowHint()
        reportText.value += d.text
        if (d.section) currentSection.value = d.section
      },
      onDone: (d) => {
        clearSlowHint()
        streaming.value = false
        startMessage.value = ''
        currentSection.value = ''
        loadReports() // 已落库，刷新列表
      },
      onError: (e) => {
        clearSlowHint()
        streaming.value = false
        errorMsg.value = e.message
      }
    }
  )
}

function abort() {
  controller?.abort()
  clearSlowHint()
  streaming.value = false
  startMessage.value = ''
  currentSection.value = ''
  // 断连会把已生成内容落库（接口文档 §3.6：与完整报告同一口径），刷新即可看到半成品
  loadReports()
}

function changePage(delta) {
  const next = page.value + delta
  if (next < 1 || (next - 1) * PAGE_SIZE >= total.value) return
  page.value = next
  loadReports()
}

onMounted(() => {
  loadApplications()
  loadReports()
})

onUnmounted(() => {
  clearSlowHint() // 切页时定时器不能留
})
</script>

<template>
  <div class="jd">
    <!-- 左栏：输入 + 历史 -->
    <aside class="jd__side">
      <section class="jd__card">
        <h3 class="jd__card-title">粘贴 JD</h3>
        <el-input
          v-model="jdText"
          type="textarea"
          :rows="8"
          :maxlength="JD_MAX"
          show-word-limit
          :disabled="streaming"
          placeholder="把岗位描述整段粘进来，AI 会给出五段匹配分析"
        />
        <el-select
          v-model="applicationId"
          class="jd__select"
          clearable
          filterable
          :disabled="streaming"
          placeholder="关联投递（可选）"
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
        <h3 class="jd__card-title">历史报告</h3>
        <el-empty v-if="!reports.length" description="还没有分析记录" :image-size="60" />
        <ul v-else class="jd__list">
          <li
            v-for="item in reports"
            :key="item.id"
            class="jd__list-item"
            :class="{ 'jd__list-item--active': detail && detail.id === item.id }"
            @click="openDetail(item.id)"
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
            {{ detail.company || '未关联投递' }} · {{ detail.score ?? '—' }} 分
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
        <div v-if="startMessage || sectionLabel" class="jd__progress">
          <span>{{ startMessage }}</span>
          <span v-if="slowHint" class="jd__progress-hint">正在分析，请耐心等待…</span>
          <span v-if="sectionLabel" class="jd__progress-section">正在生成：{{ sectionLabel }}</span>
        </div>
        <el-alert v-if="errorMsg" :title="errorMsg" type="error" :closable="false" />
        <div v-if="reportText || streaming" class="jd__report-body">
          <StreamText :text="reportText" :streaming="streaming" />
        </div>
        <el-empty
          v-else
          description="粘贴一份 JD 开始分析，或从左侧选择历史报告"
          :image-size="80"
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
</style>
