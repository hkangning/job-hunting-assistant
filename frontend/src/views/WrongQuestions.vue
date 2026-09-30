<script setup>
/**
 * 错题本（FR-010 / 开发计划步骤 14）：列表 → 复习 的主区切换，同陪练页。
 *
 * 列表排序、到期口径、档位推进都由后端定；本页只负责取数与呈现。
 * 列表筛选（状态 / 关键字 / 领域）随请求下发、count 与列表同条件过滤（接口文档 v1.32 §3.9）。
 */
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'
import { getPracticeMeta } from '../api/practice'
import { deleteWrongQuestion, listWrongQuestions, reviewWrongQuestion } from '../api/wrongQuestions'
import WrongList from '../components/wrong/WrongList.vue'
import WrongReview from '../components/wrong/WrongReview.vue'
import WrongAddDialog from '../components/wrong/WrongAddDialog.vue'

const meta = ref(null)

// 列表（keyword / direction 为列表筛选，与 status 可叠加；接口文档 §3.9）
const items = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(10)
const status = ref('')
const keyword = ref('')
const direction = ref('')
const loading = ref(false)
const counts = reactive({ pending: 0, mastered: 0 })
let keywordTimer = null

// 复习
const phase = ref('list') // list | review
const current = ref(null)
const reviewResult = ref(null)
const reviewing = ref(false)

const addVisible = ref(false)

const emptyText = computed(() => {
  if (keyword.value || direction.value) return '没有匹配的错题——换个关键字或领域试试'
  if (status.value === 'MASTERED') return '还没有已掌握的错题——答对满四档就会在这里'
  return '错题本还是空的，去八股陪练练一场吧'
})

onMounted(async () => {
  await Promise.allSettled([loadMeta(), load(), loadCounts()])
})

onUnmounted(() => clearTimeout(keywordTimer)) // 防抖定时器不能留到组件外

async function loadMeta() {
  meta.value = await getPracticeMeta()
}

async function load({ append = false } = {}) {
  // append 模式只给连续复习用：翻页拉取并追加；列表自身的翻页与筛选仍为替换
  const targetPage = append ? page.value + 1 : page.value
  loading.value = true
  try {
    const data = await listWrongQuestions({
      status: status.value || undefined,
      keyword: keyword.value || undefined,
      direction: direction.value || undefined,
      page: targetPage,
      page_size: pageSize.value
    })
    items.value = append ? [...items.value, ...data.items] : data.items
    total.value = data.total
    if (append) page.value = targetPage
  } finally {
    loading.value = false
  }
}

/** 侧栏计数：后端无聚合端点，用两个 `page_size=1` 的轻请求取 `total`。 */
async function loadCounts() {
  const [pending, mastered] = await Promise.all([
    listWrongQuestions({ status: 'PENDING', page: 1, page_size: 1 }),
    listWrongQuestions({ status: 'MASTERED', page: 1, page_size: 1 })
  ])
  counts.pending = pending.total
  counts.mastered = mastered.total
}

async function refresh() {
  await Promise.allSettled([load(), loadCounts()])
}

function changeStatus(value) {
  status.value = value
  page.value = 1
  load()
}

/** 关键字输入防抖 300ms（同投递页），回车不清空——输入即筛。 */
function onKeywordInput(value) {
  keyword.value = value || ''
  page.value = 1
  clearTimeout(keywordTimer)
  keywordTimer = setTimeout(load, 300)
}

/** 领域筛选（下拉即时生效）。 */
function onDirectionChange(value) {
  direction.value = value || ''
  page.value = 1
  load()
}

function changePage(value) {
  page.value = value
  load()
}

// ---------- 连续复习（轻量串联，经讨论确定） ----------

const reviewFinished = ref(false)
const nextCandidate = ref(null)

/** 当前条目之后的第一条未掌握——答错回档的条目在当前位置之前，不会被重复串到。 */
function refreshNextCandidate() {
  const idx = items.value.findIndex((i) => i.id === current.value?.id)
  nextCandidate.value =
    idx === -1 ? null : items.value.slice(idx + 1).find((i) => !i.mastered_at) || null
}

const hasNext = computed(
  () => !reviewFinished.value && (!!nextCandidate.value || page.value * pageSize.value < total.value)
)

function openReview(item) {
  current.value = item
  reviewResult.value = null
  reviewFinished.value = false
  phase.value = 'review'
  refreshNextCandidate()
}

/** 「下一条待复习」：已加载部分找完仍有下一页时，静默拉取后继续；都没有则进入完成态。 */
async function goNextReview() {
  if (nextCandidate.value) {
    openReview(nextCandidate.value)
    return
  }
  if (page.value * pageSize.value < total.value) {
    const anchorId = current.value.id
    await load({ append: true })
    const idx = items.value.findIndex((i) => i.id === anchorId)
    const found = items.value.slice(idx + 1).find((i) => !i.mastered_at)
    if (found) {
      openReview(found)
      return
    }
  }
  reviewFinished.value = true
}

/**
 * 侧栏「开始复习」：切到待复习筛选后打开第一条（后端排序：未掌握优先 → 到期先后）。
 *
 * 一并清掉浏览用的搜索 / 领域筛选——这个按钮是**全局复习队列**的入口，
 * 语义是「按到期顺序过一遍」，不该被列表上停留的筛选条件缩窄。
 */
async function startReview() {
  const hadFilter = !!keyword.value || !!direction.value
  keyword.value = ''
  direction.value = ''
  if (status.value !== 'PENDING' || hadFilter) {
    status.value = 'PENDING'
    page.value = 1
    await load()
  }
  const first = items.value.find((i) => !i.mastered_at)
  if (first) openReview(first)
}

/** 返回列表：档位可能已推进，回来重新取数。 */
function backToList() {
  phase.value = 'list'
  current.value = null
  reviewResult.value = null
  refresh()
}

/** 复习提交——选择题传选项标识（服务端零 AI 判定），其余题型传作答文本（走 LLM 判定）。 */
async function submitReview(value) {
  if (!value) {
    ElMessage.warning('请先作答')
    return
  }
  reviewing.value = true
  try {
    const result = await reviewWrongQuestion(current.value.id, value)
    reviewResult.value = result
    // 同步本地条目（档位 / 到期 / 掌握）——队列据此跳过刚走完四档的条目
    const idx = items.value.findIndex((i) => i.id === current.value.id)
    if (idx !== -1) {
      items.value[idx] = {
        ...items.value[idx],
        review_stage: result.review_stage,
        next_review_at: result.next_review_at,
        mastered_at: result.mastered ? new Date().toISOString().slice(0, 19) : null
      }
      current.value = items.value[idx]
      refreshNextCandidate()
    }
    await loadCounts()
  } catch (error) {
    ElMessage.error(error?.message || '判定失败，请稍后重试')
  } finally {
    reviewing.value = false
  }
}

async function removeItem(item) {
  try {
    await ElMessageBox.confirm(`确定把「${item.content.slice(0, 20)}…」从错题本移除吗？`, '移除错题', {
      type: 'warning',
      confirmButtonText: '移除',
      cancelButtonText: '取消'
    })
  } catch {
    return // 用户取消
  }
  try {
    await deleteWrongQuestion(item.id)
    ElMessage.success('已移除')
    if (phase.value === 'review') backToList()
    else await refresh()
  } catch (error) {
    ElMessage.error(error?.message || '移除失败，请稍后重试')
  }
}
</script>

<template>
  <div class="wrong-page">
    <main class="wrong-page__main">
      <WrongReview
        v-if="phase === 'review'"
        :item="current"
        :meta="meta"
        :result="reviewResult"
        :busy="reviewing"
        :has-next="hasNext"
        @submit="submitReview"
        @back="backToList"
        @remove="removeItem"
        @next="goNextReview"
      />
      <WrongList
        v-else
        :items="items"
        :total="total"
        :page="page"
        :page-size="pageSize"
        :status="status"
        :keyword="keyword"
        :direction="direction"
        :loading="loading"
        :meta="meta"
        :empty-text="emptyText"
        @open="openReview"
        @remove="removeItem"
        @page-change="changePage"
        @status-change="changeStatus"
        @keyword-change="onKeywordInput"
        @direction-change="onDirectionChange"
      />
    </main>

    <aside class="wrong-page__side">
      <section class="wrong-page__card">
        <h3 class="wrong-page__card-title dot-title">复习进度</h3>
        <div class="wrong-page__stat">
          <span class="wrong-page__stat-value wrong-page__stat-value--due">{{ counts.pending }}</span>
          <span class="wrong-page__stat-label">待复习</span>
        </div>
        <div class="wrong-page__stat">
          <span class="wrong-page__stat-value">{{ counts.mastered }}</span>
          <span class="wrong-page__stat-label">已掌握</span>
        </div>
        <el-button
          class="wrong-page__start"
          type="primary"
          :disabled="!counts.pending"
          @click="startReview"
        >
          {{ counts.pending ? '开始复习' : '暂无待复习' }}
        </el-button>
        <el-button class="wrong-page__add" :icon="Plus" @click="addVisible = true">
          添加知识点
        </el-button>
      </section>
    </aside>

    <WrongAddDialog v-model="addVisible" :meta="meta" @added="refresh" />
  </div>
</template>

<style scoped>
.wrong-page {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 300px;
  gap: var(--card-gap);
  align-items: start;
}

/* 辅助卡＝线框卡（透明底、无阴影）：与白色主卡形成「虚 / 实」两层，卡片不再一样重 */
.wrong-page__card {
  background: transparent;
  border: 1px solid var(--c-border);
  border-radius: var(--r-card);
  padding: var(--card-padding);
}
.wrong-page__card-title {
  margin: 0 0 var(--card-gap);
  font-size: var(--fs-title);
  font-weight: 700;
  color: var(--c-text);
}

.wrong-page__stat {
  display: flex;
  align-items: baseline;
  gap: 8px;
}
.wrong-page__stat + .wrong-page__stat {
  margin-top: 10px;
}
.wrong-page__stat-value {
  font-size: 28px;
  font-weight: 700;
  line-height: 1;
  color: var(--c-text);
  font-variant-numeric: tabular-nums;
}
/* 待复习是「今天该干什么」的信号，用错题本的模块色点出来；已掌握保持中性 */
.wrong-page__stat-value--due {
  color: var(--m-wrong);
}
.wrong-page__stat-label {
  font-size: var(--fs-sm);
  color: var(--c-text-2);
}

/* 「开始复习」是本页主任务；添加知识点是低频动作，降为次按钮 */
.wrong-page__start {
  width: 100%;
  margin-top: var(--card-gap);
}
.wrong-page__add {
  width: 100%;
  margin-top: 8px;
  margin-left: 0;
}
</style>
