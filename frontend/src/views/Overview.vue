<script setup>
/**
 * 今日概览（SRS §3.1 / 接口文档 §3.4）：打开就知道今天该干什么。
 * 分区纵列：状态统计卡 → 待面试/笔试 → 跟进提醒 → 三栏（错题 / 校招情报 / 快捷入口）。
 * 错题与校招情报的内容分别随步骤 14/20 与 21/23 填充，此步留占位。
 */
import { computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useOverviewStore } from '../stores/overview'
import { APPLICATION_STATUSES, STATUS_LABELS, STATUS_COLORS } from '../constants/application'

// 轮询间隔（系统设计 §4.2）；**仅本页挂载期间生效**——做成 store 内全局轮询的话，
// 用户在投递页 / 分析页操作时也会持续请求一个没人看的接口
const POLL_MS = 30000

const router = useRouter()
const store = useOverviewStore()

const stats = computed(() => store.data?.application_stats || null)
const wrongCount = computed(() => store.data?.wrong_question_count ?? 0)
const campusEvents = computed(() => store.data?.campus_events || [])
const lastCrawlAt = computed(() => store.data?.last_crawl_at || null)

const p2 = (n) => String(n).padStart(2, '0')
const tomorrowStr = (() => {
  const d = new Date()
  d.setDate(d.getDate() + 1)
  return `${d.getFullYear()}-${p2(d.getMonth() + 1)}-${p2(d.getDate())}`
})()

const isTomorrow = (e) => String(e.event_at || '').slice(0, 10) === tomorrowStr

// 明日项置顶（SRS「明日有面试/笔试的记录置顶展示」），其余保持后端返回的 7 日内升序
const upcoming = computed(() => {
  const list = store.data?.upcoming_events || []
  return [...list.filter(isTomorrow), ...list.filter((e) => !isTomorrow(e))]
})

// 拖得越久越该跟进，故按天数降序
const followUps = computed(() =>
  [...(store.data?.follow_ups || [])].sort((a, b) => (b.days || 0) - (a.days || 0))
)

function goApplications() {
  router.push('/applications')
}

let timer = null
onMounted(async () => {
  await store.fetch()
  timer = setInterval(() => store.fetch(true), POLL_MS) // silent：轮询不闪 loading
})
onUnmounted(() => clearInterval(timer))
</script>

<template>
  <div v-loading="store.loading && !store.data" class="overview">
    <!-- 加载失败：可重试（概览是首页，失败必须给出明确出口） -->
    <div v-if="store.error && !store.data" class="overview__error">
      <span>{{ store.error }}</span>
      <el-button size="small" @click="store.fetch()">重试</el-button>
    </div>

    <template v-else-if="store.data">
      <!-- ① 状态统计卡：点击进投递管理，看板的列即按状态分列 -->
      <div class="stat-row">
        <div
          v-for="s in APPLICATION_STATUSES"
          :key="s.value"
          class="stat-card"
          @click="goApplications"
        >
          <i class="stat-card__bar" :style="{ background: s.color }"></i>
          <span class="stat-card__num">{{ stats ? stats[s.value] ?? 0 : '—' }}</span>
          <span class="stat-card__label">{{ s.label }}</span>
        </div>
      </div>

      <!-- ② 待面试 / 笔试 -->
      <el-card shadow="never" class="overview__card">
        <h3 class="overview__title">待面试 / 笔试</h3>
        <div v-if="upcoming.length" class="evlist">
          <div
            v-for="e in upcoming"
            :key="e.application_id"
            class="evlist__item"
            :class="{ 'evlist__item--soon': isTomorrow(e) }"
            @click="goApplications"
          >
            <i class="evlist__dot" :style="{ background: STATUS_COLORS[e.status] }"></i>
            <span class="evlist__time">{{ e.event_at }}</span>
            <span class="evlist__main">{{ e.company }} · {{ e.position }}</span>
            <el-tag v-if="isTomorrow(e)" size="small" type="warning" effect="plain">明天</el-tag>
            <span class="evlist__status">{{ STATUS_LABELS[e.status] }}</span>
          </div>
        </div>
        <p v-else class="overview__empty">近期没有面试或笔试安排</p>
      </el-card>

      <!-- ③ 跟进提醒 -->
      <el-card shadow="never" class="overview__card">
        <h3 class="overview__title">该跟进一下了</h3>
        <div v-if="followUps.length" class="evlist">
          <div
            v-for="f in followUps"
            :key="f.application_id"
            class="evlist__item"
            @click="goApplications"
          >
            <i class="evlist__dot" :style="{ background: STATUS_COLORS.APPLIED }"></i>
            <span class="evlist__main">{{ f.company }} · {{ f.position }}</span>
            <span class="evlist__days">已投递 {{ f.days }} 天</span>
          </div>
        </div>
        <p v-else class="overview__empty">暂无需要跟进的投递</p>
      </el-card>

      <!-- ④ 三栏：错题 / 校招情报 / 快捷入口 -->
      <div class="overview__grid">
        <el-card shadow="never" class="overview__card">
          <h3 class="overview__title">错题复习</h3>
          <template v-if="wrongCount > 0">
            <p class="overview__metric">{{ wrongCount }}<span> 道到期</span></p>
            <el-button link type="primary" @click="router.push('/wrong-questions')">去复习</el-button>
          </template>
          <p v-else class="overview__empty">暂无到期错题</p>
        </el-card>

        <el-card shadow="never" class="overview__card">
          <h3 class="overview__title">校招情报</h3>
          <p v-if="campusEvents.length" class="overview__metric">
            {{ campusEvents.length }}<span> 场近期宣讲会</span>
          </p>
          <p v-else class="overview__empty">校招情报将在后续步骤上线</p>
          <p v-if="lastCrawlAt" class="overview__meta">上次抓取 {{ lastCrawlAt }}</p>
        </el-card>

        <el-card shadow="never" class="overview__card">
          <h3 class="overview__title">快捷入口</h3>
          <div class="shortcuts">
            <el-button @click="router.push('/applications?action=new')">新增投递</el-button>
            <el-button @click="router.push('/jd-analysis')">JD 分析</el-button>
            <el-button @click="router.push('/interview')">模拟面试</el-button>
            <el-button @click="router.push('/practice')">八股陪练</el-button>
            <el-button @click="router.push('/wrong-questions')">错题抽问</el-button>
          </div>
        </el-card>
      </div>
    </template>
  </div>
</template>

<style scoped>
/* 页面不渲染标题：标题职责归顶栏（系统设计 §4.4） */
.overview__error {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 18px;
  background: var(--c-card);
  border: 1px solid var(--c-border);
  border-radius: var(--r-card);
  font-size: 13px;
  color: var(--c-text);
}

/* ---------- ① 状态统计卡 ---------- */
.stat-row {
  display: flex;
  gap: var(--card-gap);
  margin-bottom: var(--card-gap);
}
.stat-card {
  flex: 1 1 0;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: var(--card-padding);
  background: var(--c-card);
  border: 1px solid var(--c-border);
  border-radius: var(--r-card);
  cursor: pointer;
  transition: border-color 0.15s;
}
.stat-card:hover {
  border-color: var(--brand);
}
.stat-card__bar {
  width: 3px;
  height: 18px;
  border-radius: var(--r-bar);
  flex: none;
}
.stat-card__num {
  font-size: 15px;
  font-weight: 700;
  color: var(--c-text);
}
.stat-card__label {
  font-size: 12px;
  color: var(--c-text-2);
  white-space: nowrap;
  flex: none;
}

/* ---------- 区块通用 ---------- */
.overview__card {
  border-radius: var(--r-card);
  margin-bottom: var(--card-gap);
}
.overview__title {
  font-size: 13px;
  font-weight: 700;
  color: var(--c-text);
  margin: 0 0 12px;
}
.overview__empty {
  font-size: 12px;
  color: var(--c-text-3);
  margin: 0;
}
.overview__meta {
  font-size: 11.5px;
  color: var(--c-text-3);
  margin: 8px 0 0;
}
.overview__metric {
  font-size: 15px;
  font-weight: 700;
  color: var(--c-text);
  margin: 0 0 6px;
}
.overview__metric span {
  font-size: 12px;
  font-weight: 400;
  color: var(--c-text-2);
}

/* ---------- 列表（下边框分隔，不逐项做成卡片：系统设计 §4.5.4） ---------- */
.evlist__item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 6px;
  border-bottom: 1px solid var(--c-divider);
  cursor: pointer;
}
.evlist__item:last-child {
  border-bottom: 0;
}
.evlist__item:hover {
  background: var(--c-bg);
}
.evlist__item--soon {
  background: var(--el-color-warning-light-9);
}
.evlist__dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex: none;
}
.evlist__time {
  font-size: 12px;
  color: var(--c-text-2);
  white-space: nowrap;
  flex: none;
}
.evlist__main {
  font-size: 13px;
  color: var(--c-text);
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.evlist__status,
.evlist__days {
  font-size: 12px;
  color: var(--c-text-2);
  white-space: nowrap;
  flex: none;
}

/* ---------- ④ 三栏 ---------- */
.overview__grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--card-gap);
  align-items: start;
}
.overview__grid .overview__card {
  margin-bottom: 0;
}
.shortcuts {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
</style>
