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
import { shortDateTime, datePart } from '../utils/datetime'

// 轮询间隔（系统设计 §4.2）；**仅本页挂载期间生效**——做成 store 内全局轮询的话，
// 用户在投递页 / 分析页操作时也会持续请求一个没人看的接口
const POLL_MS = 30000

const router = useRouter()
const store = useOverviewStore()

const stats = computed(() => store.data?.application_stats || null)

// 空态判定：该账号**一件投递都没有**（而非「统计卡恰好全 0」——那可能只是各状态暂无记录）。
// 此时统计卡与两个列表都没有信息量，首屏应改为「开始使用」的引导，而不是满屏 0 与空态文案。
const isEmpty = computed(() => store.data?.stats?.application_count === 0)
const wrongCount = computed(() => store.data?.wrong_question_count ?? 0)
const campusEvents = computed(() => store.data?.campus_events || [])
// 匹配度最高的岗位（步骤 22 落地后才有数据）；与宣讲会一并构成「校招情报」区块
const jobPostings = computed(() => store.data?.top_job_postings || [])

const p2 = (n) => String(n).padStart(2, '0')
const tomorrowStr = (() => {
  const d = new Date()
  d.setDate(d.getDate() + 1)
  return `${d.getFullYear()}-${p2(d.getMonth() + 1)}-${p2(d.getDate())}`
})()

const isTomorrow = (e) => datePart(e.event_at) === tomorrowStr

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
      <!-- 空态：还没有任何投递 —— 统计卡与列表都无信息量，改为「开始使用」的引导 -->
      <div v-if="isEmpty" class="starter">
        <h2 class="starter__title">开始你的求职管理</h2>
        <p class="starter__desc">
          还没有投递记录。先看看有什么岗位机会，或者直接记下已经投过的。
        </p>
        <div class="starter__actions">
          <!-- 「先找机会」排在「记记录」之前：真实的求职顺序就是先看到岗位再投，
               只给记录入口会让新用户卡在「我投什么呢」 -->
          <el-button type="primary" size="large" @click="router.push('/campus')">
            查看校招情报
          </el-button>
          <el-button size="large" @click="router.push('/applications?action=new')">
            ＋ 新增投递
          </el-button>
          <el-button size="large" @click="router.push('/jd-analysis')">JD 匹配分析</el-button>
        </div>
        <p class="starter__hint">
          校招情报聚合多所高校就业网的宣讲会 / 双选会 / 岗位，可从岗位一键加入投递；
          已有一批投递记录时，也可在「投递管理」页用「批量导入」。
        </p>
      </div>

      <template v-else>
      <!-- ① 待面试 / 笔试：最紧急，排最前 -->

      <el-card v-if="upcoming.length" shadow="never" class="overview__card">
        <h3 class="overview__title">待面试 / 笔试</h3>
        <div class="evlist">
          <div
            v-for="e in upcoming"
            :key="e.application_id"
            class="evlist__item"
            :class="{ 'evlist__item--soon': isTomorrow(e) }"
            @click="goApplications"
          >
            <i class="evlist__dot" :style="{ background: STATUS_COLORS[e.status] }"></i>
            <span class="evlist__time">{{ shortDateTime(e.event_at) }}</span>
            <span class="evlist__main">{{ e.company }} · {{ e.position }}</span>
            <el-tag v-if="isTomorrow(e)" size="small" type="warning" effect="plain">明天</el-tag>
            <span class="evlist__status">{{ STATUS_LABELS[e.status] }}</span>
          </div>
        </div>
      </el-card>

      <!-- ② 跟进提醒 -->

      <el-card v-if="followUps.length" shadow="never" class="overview__card">
        <h3 class="overview__title">该跟进一下了</h3>
        <div class="evlist">
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
      </el-card>

      <!-- ③ 校招情报（一手招聘信息）：**始终显示**，与上面两块（待办类）不同 ——
           待办没内容时该收起，而**入口本身就是内容**：它是本页唯一的「信息获取」来源，
           把它也藏起来，整页就只剩投递相关内容，与投递管理看不出区别了。
           内容随步骤 21~23 填充。见问题记录 IS-29（招聘信息与投递管理是候选池 → 进度追踪的
           两段式，靠视觉语言区分、不合并，故这里的岗位状态不借用投递状态色）与 IS-30。 -->

      <el-card shadow="never" class="overview__card">
        <h3 class="overview__title">校招情报</h3>
        <div v-if="campusEvents.length || jobPostings.length" class="evlist">
          <div
            v-for="e in campusEvents"
            :key="`c-${e.id}`"
            class="evlist__item"
            @click="router.push('/campus')"
          >
            <i class="evlist__dot" :style="{ background: 'var(--m-campus)' }"></i>
            <span class="evlist__time">{{ e.event_date }}</span>
            <span class="evlist__main">{{ e.company }} · {{ e.title }}</span>
            <span class="evlist__status">{{ e.location }}</span>
          </div>
          <div
            v-for="p in jobPostings"
            :key="`j-${p.id}`"
            class="evlist__item"
            @click="router.push('/campus')"
          >
            <i class="evlist__dot" :style="{ background: 'var(--m-campus)' }"></i>
            <span class="evlist__main">{{ p.company }} · {{ p.title }}</span>
            <span class="evlist__days">匹配度 {{ p.match_score }}</span>
          </div>
        </div>
        <p v-else class="overview__hint">
          聚合多所高校就业网的宣讲会 / 双选会 / 岗位，按画像匹配度排序。
        </p>
        <el-button link type="primary" class="overview__more" @click="router.push('/campus')">
          {{ campusEvents.length || jobPostings.length ? '查看全部' : '去发现机会' }} →
        </el-button>
      </el-card>

      <!-- ④ 今天无事可做时的说明：**待办类**区块（待面试 / 跟进 / 错题）都收起后才出现。
           校招情报不参与该判定——它是常驻入口，不算「待办」。 -->
      <p
        v-if="!upcoming.length && !followUps.length && !wrongCount"
        class="overview__quiet"
      >
        今天没有需要处理的事，安心准备下一场面试吧——也可以去校招情报看看新机会。
      </p>

      <!-- ⑤ 底部状态条：紧凑一行 —— 它们是「现状」而非「待办」，不该占首屏
           （「快捷入口」已移除：其中 4/5 与侧栏重复，且导航不回答「今天干什么」） -->
      <div class="overview__strip">
        <div v-if="wrongCount > 0" class="strip-item" @click="router.push('/wrong-questions')">
          <i class="strip-item__dot" :style="{ background: 'var(--m-wrong)' }"></i>
          错题复习 <b>{{ wrongCount }}</b> 道到期
          <span class="strip-item__link">去复习 →</span>
        </div>

        <div class="strip-item strip-item--grow" @click="goApplications">
          <span v-for="s in APPLICATION_STATUSES" :key="s.value" class="strip-item__stat">
            <i class="strip-item__dot" :style="{ background: s.color }"></i>
            {{ s.label }} <b>{{ stats ? stats[s.value] ?? 0 : '—' }}</b>
          </span>
          <span class="strip-item__link">投递管理 →</span>
        </div>
      </div>
      </template>
      <!-- 常规布局结束（空态与常规布局互斥） -->
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
  font-size: var(--fs-body);
  color: var(--c-text);
}

/* ---------- 空态引导卡（还没有任何投递时替代统计卡与列表） ---------- */
/* 撑满内容区并让内容居中：无数据时首屏只有这一张卡，撑满才不会留下大片空白 */
.starter {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  /* border-box：否则 min-height 只管内容区，加上 padding 后总高超出视口（会导致整页滚动） */
  box-sizing: border-box;
  min-height: calc(100vh - 100px); /* 视口 − 顶栏 56 − 内容区上下 padding 40，留 4px 余量 */
  padding: 40px 24px;
  background: var(--c-card);
  border: 1px solid var(--c-border);
  border-radius: var(--r-card);
  text-align: center;
}
.starter__title {
  margin: 0 0 12px;
  font-size: 20px;
  font-weight: 700;
  color: var(--c-text);
}
.starter__desc {
  max-width: 460px;
  margin: 0 auto 30px;
  font-size: var(--fs-title);
  line-height: 1.8;
  color: var(--c-text-2);
}
.starter__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  justify-content: center;
  margin-bottom: 22px;
}
.starter__hint {
  margin: 0;
  font-size: var(--fs-sm);
  color: var(--c-text-3);
}

/* ---------- 区块通用 ---------- */
.overview__card {
  border-radius: var(--r-card);
  margin-bottom: var(--card-gap);
}
.overview__title {
  font-size: var(--fs-title);
  font-weight: 700;
  color: var(--c-text);
  margin: 0 0 12px;
}
/* 「今天无事可做」的一句说明（各区块按「有内容才显示」收起后的兜底文案） */
.overview__quiet {
  margin: 0 0 var(--card-gap);
  font-size: var(--fs-body);
  color: var(--c-text-2);
}
/* 校招情报无数据时的说明（该区块始终显示，无数据时它承担「讲清这是什么」的职责） */
.overview__hint {
  margin: 0;
  font-size: var(--fs-sm);
  line-height: 1.7;
  color: var(--c-text-2);
}
/* 校招情报区块的入口按钮 */
.overview__more {
  margin-top: 8px;
}

/* ---------- 列表（下边框分隔，不逐项做成卡片：系统设计 §4.5.4） ---------- */
.evlist__item {
  display: flex;
  align-items: center;
  gap: 10px;
  /* 字号提档后原 9px 6px 显紧：行高变大，纵向留白需同步放宽 */
  padding: 10px 8px;
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
  font-size: var(--fs-sm);
  color: var(--c-text-2);
  white-space: nowrap;
  flex: none;
}
.evlist__main {
  font-size: var(--fs-body);
  color: var(--c-text);
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.evlist__status,
.evlist__days {
  font-size: var(--fs-sm);
  color: var(--c-text-2);
  white-space: nowrap;
  flex: none;
}

/* ---------- 底部状态条：紧凑一行，「现状」而非「待办」，不占首屏 ---------- */
.overview__strip {
  display: flex;
  flex-wrap: wrap;
  gap: var(--card-gap);
}
.strip-item {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 11px 18px;
  background: var(--c-card);
  border: 1px solid var(--c-border);
  border-radius: var(--r-card);
  font-size: var(--fs-sm);
  color: var(--c-text-2);
  cursor: pointer;
  transition: border-color 0.15s;
}
.strip-item:hover {
  border-color: var(--brand);
}
/* 投递进度占剩余宽度（它承载 5 个状态的计数，比「错题复习」宽） */
.strip-item--grow {
  flex: 1 1 auto;
}
.strip-item__stat {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  white-space: nowrap;
}
.strip-item__dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex: none;
}
.strip-item b {
  font-size: var(--fs-body);
  color: var(--c-text);
}
.strip-item__link {
  margin-left: auto;
  color: var(--brand);
  white-space: nowrap;
}
</style>
