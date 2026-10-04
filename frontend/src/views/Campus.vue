<script setup>
/**
 * 校招情报（步骤 23，FR-021 / FR-022）：三类信息 Tab（宣讲会 / 双选会 / 岗位）+ 列表·日历视图，
 * 工具栏另有「投喂一条」（人工兜底通道）与「我的订阅」（规则管理）。
 *
 * 界面分离约定（系统设计 §4.8）：招聘信息的家只在本页——投递管理页只接受「从岗位预填」一个入口；
 * 本页用列表 / 日历 + 时间·匹配度，不复用投递看板的状态色。
 *
 * 分工：本页持数据与筛选状态（照 WrongQuestions 的父子分工），列表 / 日历组件纯展示。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Star } from '@element-plus/icons-vue'
import { listCampusEvents, listJobPostings, deleteJobPosting } from '../api/campus'
import { loadIngestText } from '../utils/campusStash'
import CampusEventList from '../components/campus/CampusEventList.vue'
import JobPostingList from '../components/campus/JobPostingList.vue'
import CampusCalendar from '../components/campus/CampusCalendar.vue'
import IngestDialog from '../components/campus/IngestDialog.vue'
import SubscriptionDialog from '../components/campus/SubscriptionDialog.vue'

const router = useRouter()

const TABS = [
  { value: 'talk', label: '宣讲会' },
  { value: 'fair', label: '双选会' },
  { value: 'job', label: '岗位' }
]
const JOB_TYPES = [
  { value: '', label: '全部类型' },
  { value: 'CAMPUS', label: '校招' },
  { value: 'INTERN', label: '实习' },
  { value: 'SOCIAL', label: '社招' }
]
// 进行中 = 不传（后端返回 ACTIVE + CHANGED，与列表默认口径一致）
const JOB_STATUSES = [
  { value: '', label: '进行中' },
  { value: 'CHANGED', label: '已变更' },
  { value: 'EXPIRED', label: '已过期' }
]
const SORTS = [
  { value: 'time', label: '按时间' },
  { value: 'match', label: '按匹配度' }
]

const tab = ref('talk')
const view = ref('list') // list | calendar

const loading = ref(false)
const error = ref('')
const items = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(10)

const keyword = ref('')
const city = ref('')
const company = ref('')
const jobType = ref('')
const jobStatus = ref('')
const includeExpired = ref(false)
const dateRange = ref(null)
const sort = ref('time')

const ingestVisible = ref(false)
const subsVisible = ref(false)

const isJob = computed(() => tab.value === 'job')
const emptyText = computed(() => {
  if (keyword.value || city.value || company.value) return '没有符合筛选条件的信息'
  return isJob.value ? '还没有聚合到岗位——可以「投喂一条」补充' : '还没有聚合到信息'
})

async function load() {
  loading.value = true
  error.value = ''
  try {
    if (isJob.value) {
      const data = await listJobPostings(
        {
          keyword: keyword.value || undefined,
          city: city.value || undefined,
          company: company.value || undefined,
          job_type: jobType.value || undefined,
          status: jobStatus.value || undefined,
          sort: sort.value,
          page: page.value,
          page_size: pageSize.value
        },
        { silent: true }
      )
      items.value = data.items
      total.value = data.total
    } else {
      const [dateFrom, dateTo] = dateRange.value || []
      const data = await listCampusEvents(
        {
          info_type: tab.value === 'talk' ? 'TALK' : 'FAIR',
          keyword: keyword.value || undefined,
          city: city.value || undefined,
          date_from: dateFrom || undefined,
          date_to: dateTo || undefined,
          include_expired: includeExpired.value,
          sort: sort.value,
          page: page.value,
          page_size: pageSize.value
        },
        { silent: true }
      )
      items.value = data.items
      total.value = data.total
    }
  } catch (e) {
    error.value = e?.message || '加载失败'
    items.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

/** 切 Tab / 视图 / 筛选条件：回到第一页再取数。 */
function reload() {
  page.value = 1
  load()
}

/** 文本输入防抖 300ms（设计文档 §4.6，照投递页）。 */
let filterTimer = null
function onFilterInput() {
  clearTimeout(filterTimer)
  filterTimer = setTimeout(reload, 300)
}

/** 切 Tab：清筛选、回第一页——显式函数而非 watch，避免与日历定位（切 Tab 后还要设 keyword）抢时序。 */
function switchTab(value) {
  if (tab.value === value) return
  tab.value = value
  keyword.value = ''
  city.value = ''
  company.value = ''
  page.value = 1
  load()
}

watch([sort, jobType, jobStatus, includeExpired], reload)
watch(dateRange, reload)

function openUrl(url) {
  if (url) window.open(url, '_blank', 'noopener')
}

/** 加入投递：跳投递新建表单并预填（渠道 = 来源学校，备注 = 原文链接；有投喂暂存原文一并带上）。 */
function onApply(item) {
  const query = {
    action: 'new',
    company: item.company,
    position: item.title,
    city: item.city || undefined,
    channel: item.source_site || '校招情报',
    remark: item.source_url || undefined
  }
  const stashed = loadIngestText(item.id)
  if (stashed) query.jd_text = stashed
  router.push({ path: '/applications', query })
}

/** 分析匹配度：带暂存的 JD 原文预填；自动抓取条目无正文（NFR-016），到分析页提示粘贴。 */
function onAnalyze(item) {
  const query = { company: item.company, position: item.title }
  const stashed = loadIngestText(item.id)
  if (stashed) query.jd_text = stashed
  router.push({ path: '/jd-analysis', query })
}

async function onRemove(item) {
  try {
    await ElMessageBox.confirm(`确定删除投喂的「${item.company} · ${item.title}」吗？`, '删除确认', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消'
    })
  } catch {
    return
  }
  await deleteJobPosting(item.id)
  ElMessage.success('已删除')
  load()
}

/**
 * 日历事件点击（契约只给 ref_type / ref_id，没有原文链接）：
 * 活动 → 切到对应 Tab 的列表并用标题定位该条（列表项即详情入口，原文链接在卡片上）；
 * 笔试 / 面试 → 跳投递页并按 focus 打开该条详情。
 */
function onCalendarEvent(event) {
  if (event.ref_type === 'application') {
    router.push({ path: '/applications', query: { focus: event.ref_id } })
    return
  }
  tab.value = event.event_type === 'FAIR' ? 'fair' : 'talk'
  keyword.value = event.title || ''
  city.value = ''
  company.value = ''
  view.value = 'list'
  page.value = 1
  load()
}

/** 投喂成功：切到岗位 Tab 并刷新（若已在岗位 Tab 则只刷新——不动用户的筛选）。 */
function onIngestSaved() {
  if (isJob.value) {
    reload()
    return
  }
  tab.value = 'job'
  keyword.value = ''
  city.value = ''
  company.value = ''
  page.value = 1
  load()
}

onMounted(load)
</script>

<template>
  <div class="campus">
    <div class="campus__toolbar">
      <div class="seg">
        <button
          v-for="opt in TABS"
          :key="opt.value"
          type="button"
          class="seg__item"
          :class="{ 'seg__item--on': tab === opt.value }"
          @click="switchTab(opt.value)"
        >
          {{ opt.label }}
        </button>
      </div>

      <div class="campus__tools">
        <el-button :icon="Plus" @click="ingestVisible = true">投喂一条</el-button>
        <el-button :icon="Star" @click="subsVisible = true">我的订阅</el-button>
        <div class="seg seg--view">
          <button
            type="button"
            class="seg__item"
            :class="{ 'seg__item--on': view === 'list' }"
            @click="view = 'list'"
          >
            列表
          </button>
          <button
            type="button"
            class="seg__item"
            :class="{ 'seg__item--on': view === 'calendar' }"
            @click="view = 'calendar'"
          >
            日历
          </button>
        </div>
      </div>
    </div>

    <div v-if="view === 'list'" class="campus__filters">
      <el-input
        class="campus__input"
        :model-value="keyword"
        :placeholder="isJob ? '搜索岗位 / 公司' : '搜索标题 / 公司'"
        clearable
        @update:model-value="
          (v) => {
            keyword = v
            onFilterInput()
          }
        "
      />
      <el-input
        class="campus__input campus__input--sm"
        :model-value="city"
        :placeholder="isJob ? '城市（精确）' : '地点关键词'"
        clearable
        @update:model-value="
          (v) => {
            city = v
            onFilterInput()
          }
        "
      />
      <el-input
        v-if="isJob"
        class="campus__input campus__input--sm"
        :model-value="company"
        placeholder="公司"
        clearable
        @update:model-value="
          (v) => {
            company = v
            onFilterInput()
          }
        "
      />
      <el-select v-if="isJob" v-model="jobType" class="campus__select">
        <el-option v-for="opt in JOB_TYPES" :key="opt.value" :label="opt.label" :value="opt.value" />
      </el-select>
      <el-select v-if="isJob" v-model="jobStatus" class="campus__select">
        <el-option v-for="opt in JOB_STATUSES" :key="opt.value" :label="opt.label" :value="opt.value" />
      </el-select>
      <el-date-picker
        v-else
        v-model="dateRange"
        class="campus__date"
        type="daterange"
        value-format="YYYY-MM-DD"
        start-placeholder="开始日期"
        end-placeholder="结束日期"
        unlink-panels
      />
      <label v-if="!isJob" class="campus__check">
        <el-switch v-model="includeExpired" size="small" />
        <span>含已过期</span>
      </label>
      <el-select v-model="sort" class="campus__select campus__select--sort">
        <el-option v-for="opt in SORTS" :key="opt.value" :label="opt.label" :value="opt.value" />
      </el-select>
    </div>

    <div v-if="error" class="campus__error">
      <span>{{ error }}</span>
      <el-button size="small" @click="load">重试</el-button>
    </div>

    <template v-if="view === 'list'">
      <CampusEventList
        v-if="!isJob"
        :items="items"
        :loading="loading"
        :empty-text="emptyText"
        @open-url="openUrl"
      />
      <JobPostingList
        v-else
        :items="items"
        :loading="loading"
        :empty-text="emptyText"
        @open-url="openUrl"
        @apply="onApply"
        @analyze="onAnalyze"
        @remove="onRemove"
      />

      <el-pagination
        v-if="total > pageSize"
        class="campus__pager"
        layout="prev, pager, next"
        :current-page="page"
        :page-size="pageSize"
        :total="total"
        @current-change="
          (p) => {
            page = p
            load()
          }
        "
      />
    </template>

    <CampusCalendar v-else @open-event="onCalendarEvent" />

    <IngestDialog v-model="ingestVisible" @saved="onIngestSaved" />
    <SubscriptionDialog v-model="subsVisible" />
  </div>
</template>

<style scoped>
.campus {
  background: var(--c-card);
  border: 1px solid var(--c-border);
  border-radius: var(--r-card);
  box-shadow: 0 1px 2px rgba(42, 39, 64, 0.05);
  padding: var(--card-padding);
}

.campus__toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: var(--card-gap);
}
.campus__tools {
  display: flex;
  align-items: center;
  gap: 8px;
}

/* 分段控件：与错题本 / 准备台同一形态（选中态实底） */
.seg {
  display: flex;
  gap: 4px;
  padding: 3px;
  background: var(--c-bg);
  border-radius: var(--r-control);
}
.seg--view {
  margin-left: 4px;
}
.seg__item {
  padding: 7px 14px;
  font: inherit;
  font-size: var(--fs-sm);
  color: var(--c-text-2);
  background: transparent;
  border: 0;
  border-radius: var(--r-mark);
  cursor: pointer;
}
.seg__item--on {
  color: var(--c-text);
  background: var(--c-card);
  font-weight: 600;
}

.campus__filters {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: var(--card-gap);
}
.campus__input {
  width: 220px;
}
.campus__input--sm {
  width: 150px;
}
.campus__select {
  width: 130px;
}
.campus__select--sort {
  margin-left: auto;
}
.campus__date {
  max-width: 260px;
}
.campus__check {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: var(--fs-sm);
  color: var(--c-text-2);
  cursor: pointer;
}

.campus__error {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 14px;
  margin-bottom: var(--card-gap);
  font-size: var(--fs-body);
  color: var(--c-text);
  background: var(--c-bg);
  border-radius: var(--r-control);
}

.campus__pager {
  justify-content: flex-end;
  margin-top: var(--card-gap);
}
</style>
