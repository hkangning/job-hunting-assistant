<script setup>
/**
 * 错题本（FR-010 / 开发计划步骤 14）：列表 → 复习 的主区切换，同陪练页。
 *
 * 列表排序、到期口径、档位推进都由后端定；本页只负责取数与呈现。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'
import { getPracticeMeta } from '../api/practice'
import { deleteWrongQuestion, listWrongQuestions, reviewWrongQuestion } from '../api/wrongQuestions'
import WrongList from '../components/wrong/WrongList.vue'
import WrongReview from '../components/wrong/WrongReview.vue'
import WrongAddDialog from '../components/wrong/WrongAddDialog.vue'

const meta = ref(null)

// 列表
const items = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(10)
const status = ref('')
const loading = ref(false)
const counts = reactive({ pending: 0, mastered: 0 })

// 复习
const phase = ref('list') // list | review
const current = ref(null)
const reviewResult = ref(null)
const reviewing = ref(false)

const addVisible = ref(false)

const emptyText = computed(() =>
  status.value === 'MASTERED'
    ? '还没有已掌握的错题——答对满四档就会在这里'
    : '错题本还是空的，去八股陪练练一场吧'
)

onMounted(async () => {
  await Promise.allSettled([loadMeta(), load(), loadCounts()])
})

async function loadMeta() {
  meta.value = await getPracticeMeta()
}

async function load() {
  loading.value = true
  try {
    const data = await listWrongQuestions({
      status: status.value || undefined,
      page: page.value,
      page_size: pageSize.value
    })
    items.value = data.items
    total.value = data.total
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

function changePage(value) {
  page.value = value
  load()
}

function openReview(item) {
  current.value = item
  reviewResult.value = null
  phase.value = 'review'
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
    reviewResult.value = await reviewWrongQuestion(current.value.id, value)
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
        @submit="submitReview"
        @back="backToList"
        @remove="removeItem"
      />
      <WrongList
        v-else
        :items="items"
        :total="total"
        :page="page"
        :page-size="pageSize"
        :status="status"
        :loading="loading"
        :meta="meta"
        :empty-text="emptyText"
        @open="openReview"
        @remove="removeItem"
        @page-change="changePage"
        @status-change="changeStatus"
      />
    </main>

    <aside class="wrong-page__side">
      <section class="wrong-page__card">
        <h3 class="wrong-page__card-title">复习进度</h3>
        <div class="wrong-page__stat">
          <span class="wrong-page__stat-value wrong-page__stat-value--due">{{ counts.pending }}</span>
          <span class="wrong-page__stat-label">待复习</span>
        </div>
        <div class="wrong-page__stat">
          <span class="wrong-page__stat-value">{{ counts.mastered }}</span>
          <span class="wrong-page__stat-label">已掌握</span>
        </div>
        <el-button class="wrong-page__add" type="primary" :icon="Plus" @click="addVisible = true">
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

.wrong-page__card {
  background: var(--c-card);
  border: 1px solid var(--c-border);
  border-radius: var(--r-card);
  box-shadow: 0 1px 2px rgba(42, 39, 64, 0.05);
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

.wrong-page__add {
  width: 100%;
  margin-top: var(--card-gap);
}
</style>
