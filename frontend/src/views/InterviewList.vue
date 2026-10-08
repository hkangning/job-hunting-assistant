<script setup>
/**
 * 模拟面试列表（FR-007 / 开发计划步骤 15；接口文档 v1.33 §3.7）。
 *
 * 两种状态的出口：**进行中** → 进行页继续作答；**已结束** → 回看页（总结报告 + 完整回顾，
 * 步骤 16 前端部分）。整卡可点击，右侧按钮跟随状态。
 *
 * 进行中的会话显示 `qa_count/question_count` 进度（接口文档 v1.32 列表项字段，
 * 含尚未作答的当前题——即「问到第几题」，与进行页页头同一口径）。
 */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { getPracticeMeta } from '../api/practice'
import { listInterviewSessions } from '../api/interview'
import { directionLabelMap } from '../utils/practiceMeta'
import { INTENSITY_LABELS } from '../utils/interviewStream'
import { shortDateTime } from '../utils/datetime'
import InterviewCreateDialog from '../components/interview/InterviewCreateDialog.vue'
import AppEmpty from '../components/AppEmpty.vue'
import AppError from '../components/AppError.vue'

const router = useRouter()

const status = ref('') // '' | 'ACTIVE' | 'FINISHED'
const page = ref(1)
const pageSize = ref(10)
const items = ref([])
const total = ref(0)
// 首屏初值 true：不闪「还没有面试记录」假空态（步骤 27）
const loading = ref(true)
const loadError = ref('')
const meta = ref(null)
const createVisible = ref(false)
const stats = ref({ active: 0, finished: 0 })

/** 概览条数据：两次轻量查询只取 total（page_size=1 不带回列表）。 */
async function loadStats() {
  try {
    const [active, finished] = await Promise.all([
      listInterviewSessions({ status: 'ACTIVE', page: 1, page_size: 1 }),
      listInterviewSessions({ status: 'FINISHED', page: 1, page_size: 1 })
    ])
    stats.value = { active: active.total || 0, finished: finished.total || 0 }
  } catch {
    stats.value = { active: 0, finished: 0 } // 拉不到不显示概览条，不阻塞列表
  }
}

const STATUS_OPTIONS = [
  { value: '', label: '全部' },
  { value: 'ACTIVE', label: '进行中' },
  { value: 'FINISHED', label: '已结束' }
]

/** 方向中文名：`GENERAL` 不在 meta 的领域枚举里（它不参与题库分类），单独补。 */
const directionLabels = computed(() => ({ GENERAL: '通用', ...directionLabelMap(meta.value) }))

function directionLabel(item) {
  return directionLabels.value[item.direction] || item.direction
}

/** 进行中显示进度（`qa_count` 含尚未作答的当前题 → 即当前题号）；其余显示总题量。 */
function countText(item) {
  return item.status === 'ACTIVE' && item.qa_count
    ? `第 ${item.qa_count}/${item.question_count} 题`
    : `共 ${item.question_count} 题`
}

const emptyText = computed(() =>
  status.value === 'FINISHED'
    ? '还没有已结束的面试'
    : status.value === 'ACTIVE'
      ? '当前没有进行中的面试'
      : '还没有面试记录，从一条投递记录发起第一场吧'
)

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    const data = await listInterviewSessions({
      status: status.value || undefined,
      page: page.value,
      page_size: pageSize.value
    })
    items.value = data.items || []
    total.value = data.total || 0
  } catch (error) {
    // 失败 ≠ 空态：错误块由页面渲染（拦截器另有 toast，此处不再重复弹）
    loadError.value = error?.message || '加载失败，请重试'
  } finally {
    loading.value = false
  }
}

function changeStatus(value) {
  status.value = value
  page.value = 1
  load()
}

function changePage(value) {
  page.value = value
  load()
}

/** 进行中 → 进行页；已结束 → 回看页（两种状态都有出口）。 */
function openSession(item) {
  if (item.status === 'ACTIVE') router.push(`/interview/${item.id}`)
  else router.push(`/interview/${item.id}/review`)
}

function onCreated(session) {
  router.push(`/interview/${session.id}`)
}

onMounted(() => {
  load()
  loadStats()
  // 方向中文名用同一份元数据；拉不到就显示枚举值兜底
  getPracticeMeta()
    .then((data) => (meta.value = data))
    .catch(() => {})
})
</script>

<template>
  <section class="interview">
    <header class="interview__head">
      <div class="seg">
        <button
          v-for="opt in STATUS_OPTIONS"
          :key="opt.value"
          type="button"
          class="seg__item"
          :class="{ 'seg__item--on': status === opt.value }"
          @click="changeStatus(opt.value)"
        >
          {{ opt.label }}
        </button>
      </div>
      <el-button type="primary" @click="createVisible = true">发起面试</el-button>
    </header>

    <!-- 概览带：有记录时显示——统计数字 + 完整流程，让主页不至于只有一条列表 -->
    <div v-if="stats.active + stats.finished > 0" class="interview__overview">
      <div class="interview__stats">
        <span class="interview__stat"><b>{{ stats.active }}</b>场进行中</span>
        <span class="interview__stat"><b>{{ stats.finished }}</b>场已结束</span>
        <span class="interview__stat interview__stat--total">共 {{ stats.active + stats.finished }} 场</span>
      </div>
      <div class="interview__flow">
        <span class="interview__flow-label">完整流程</span>
        <span class="interview__flow-step">自我介绍</span>
        <span class="interview__flow-arrow">→</span>
        <span class="interview__flow-step">技术问答</span>
        <span class="interview__flow-arrow">→</span>
        <span class="interview__flow-step">项目深挖</span>
        <span class="interview__flow-arrow">→</span>
        <span class="interview__flow-step">总结报告</span>
        <span class="interview__flow-hint">关联投递发起会自动带入 JD 与岗位背景；画像填写经历后出现「项目深挖」</span>
      </div>
    </div>

    <AppError v-if="loadError" :message="loadError" @retry="load" />

    <AppEmpty
      v-else-if="!loading && !items.length"
      type="interview"
      :description="emptyText"
      style="--empty-color: var(--m-interview)"
    >
      <el-button v-if="status" @click="changeStatus('')">查看全部</el-button>
      <el-button v-else type="primary" @click="createVisible = true">发起面试</el-button>
    </AppEmpty>

    <template v-else>
      <ul v-loading="loading" class="interview__list">
        <li
          v-for="item in items"
          :key="item.id"
          class="interview__item"
          @click="openSession(item)"
        >
          <div class="interview__main">
            <span class="interview__title">{{ item.company }} · {{ item.position }}</span>
            <div class="interview__meta">
              <span class="interview__dir">{{ directionLabel(item) }}</span>
              <span class="interview__intensity">{{ INTENSITY_LABELS[item.intensity] || '中厂' }}</span>
              <span>{{ countText(item) }}</span>
              <span v-if="item.summary" class="interview__summary-mark">已生成总结</span>
              <span>{{ shortDateTime(item.created_at) }}</span>
            </div>
          </div>

          <span
            class="interview__badge"
            :class="{ 'interview__badge--done': item.status !== 'ACTIVE' }"
          >
            {{ item.status === 'ACTIVE' ? '进行中' : '已结束' }}
          </span>
          <el-button
            v-if="item.status === 'ACTIVE'"
            type="primary"
            plain
            @click.stop="openSession(item)"
          >
            继续面试
          </el-button>
          <el-button v-else plain @click.stop="openSession(item)">查看回顾</el-button>
        </li>
      </ul>

      <el-pagination
        v-if="total > pageSize"
        class="interview__pager"
        layout="prev, pager, next"
        :current-page="page"
        :page-size="pageSize"
        :total="total"
        @current-change="changePage"
      />
    </template>

    <InterviewCreateDialog v-model="createVisible" :meta="meta" @created="onCreated" />
  </section>
</template>

<style scoped>
.interview {
  background: var(--c-card);
  border: 1px solid var(--c-border);
  border-radius: var(--r-card);
  box-shadow: 0 1px 2px rgba(42, 39, 64, 0.05);
  padding: var(--card-padding);
}

.interview__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: var(--card-gap);
}

/* 概览带：左统计右流程——记录少时补足信息密度 */
.interview__overview {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  padding: 10px 14px;
  margin-bottom: var(--card-gap);
  background: var(--c-bg);
  border-radius: var(--r-control);
}
.interview__stats {
  display: flex;
  align-items: baseline;
  gap: 16px;
}
.interview__stat {
  font-size: var(--fs-sm);
  color: var(--c-text-2);
}
.interview__stat b {
  margin-right: 3px;
  font-size: 18px;
  color: var(--m-interview);
}
.interview__stat--total {
  color: var(--c-text-3);
}
.interview__flow {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}
.interview__flow-label {
  margin-right: 2px;
  color: var(--c-text-2);
}
.interview__flow-step {
  padding: 1px 6px;
  background: var(--c-card);
  border: 1px solid var(--c-border);
  border-radius: var(--r-mark);
}
.interview__flow-arrow {
  color: var(--c-text-3);
}
.interview__flow-hint {
  margin-left: 8px;
}

/* 分段控件：与错题本 / 准备台同一形态（选中态实底） */
.seg {
  display: flex;
  gap: 4px;
  padding: 3px;
  background: var(--c-bg);
  border-radius: var(--r-control);
}
.seg__item {
  /* 32px 高：点击热区达惯例下限（原 28px） */
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

.interview__list {
  display: grid;
  gap: 8px;
  margin: 0;
  padding: 0;
  list-style: none;
  min-height: 60px;
}
.interview__item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 14px;
  border: 1px solid var(--c-border);
  border-radius: var(--r-control);
  cursor: pointer;
  transition: border-color 0.15s;
}
.interview__item:hover {
  border-color: var(--m-interview);
}
.interview__main {
  flex: 1;
  min-width: 0;
}
.interview__title {
  display: block;
  font-size: var(--fs-body);
  color: var(--c-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.interview__meta {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 6px;
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}
.interview__dir {
  padding: 1px 6px;
  color: var(--m-interview);
  background: color-mix(in srgb, var(--m-interview) 12%, var(--c-card));
  border-radius: var(--r-mark);
}
/* 强度：中性标签——与方向（模块色）区分，不抢注意力 */
.interview__intensity {
  padding: 1px 6px;
  background: var(--c-bg);
  border-radius: var(--r-mark);
}
.interview__badge {
  flex: 0 0 auto;
  padding: 1px 8px;
  font-size: var(--fs-xs);
  color: var(--m-interview);
  background: color-mix(in srgb, var(--m-interview) 12%, var(--c-card));
  border-radius: var(--r-mark);
}
.interview__badge--done {
  color: var(--c-text-3);
  background: var(--c-bg);
}
.interview__summary-mark {
  color: var(--m-interview);
}

.interview__pager {
  justify-content: flex-end;
  margin-top: var(--card-gap);
}
</style>
