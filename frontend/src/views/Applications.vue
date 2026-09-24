<script setup>
// 投递管理页（FR-002~FR-005）：页面是唯一的数据持有者，子组件均为受控展示层
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Upload } from '@element-plus/icons-vue'
import { changeStatus, deleteApplication, getTrend, listApplications } from '../api/applications'
import { STATUS_LABELS } from '../constants/application'
import ApplicationStats from '../components/ApplicationStats.vue'
import StatusKanban from '../components/StatusKanban.vue'
import ApplicationFormDialog from '../components/ApplicationFormDialog.vue'
import ApplicationImportDialog from '../components/ApplicationImportDialog.vue'
import TrendChart from '../components/TrendChart.vue'

const PAGE_SIZE = 50 // 接口上限（接口文档 §1.1）
const MAX_PAGES = 10 // 一次拉全的封顶：50 × 10 = 500 条

const route = useRoute()
const router = useRouter()

const loading = ref(false)
const items = ref([])
const totalCount = ref(0)
const filters = reactive({ company: '', city: '' })

const formVisible = ref(false)
const editingId = ref(null)
const importVisible = ref(false)

const trendVisible = ref(false)
const trendLoading = ref(false)
const trendDays = ref(30)
const trendItems = ref([])

const isEmpty = computed(() => !loading.value && items.value.length === 0)
const isFiltered = computed(() => Boolean(filters.company || filters.city))
const truncated = computed(() => totalCount.value > items.value.length)

let filterTimer = null

/** 循环翻页拉全（接口 page_size 上限 50），封顶 500 条并由统计条提示，不静默截断 */
async function load() {
  loading.value = true
  try {
    const base = { page_size: PAGE_SIZE }
    if (filters.company) base.company = filters.company
    if (filters.city) base.city = filters.city

    const all = []
    let total = 0
    for (let page = 1; page <= MAX_PAGES; page++) {
      const data = await listApplications({ ...base, page })
      total = data.total
      all.push(...data.items)
      if (all.length >= total || data.items.length < PAGE_SIZE) break
    }
    items.value = all
    totalCount.value = total
  } finally {
    loading.value = false
  }
}

/** 筛选输入防抖 300ms（设计文档 §4.6） */
function onFilterInput() {
  clearTimeout(filterTimer)
  filterTimer = setTimeout(load, 300)
}

function openCreate() {
  editingId.value = null
  formVisible.value = true
}

function openEdit(item) {
  editingId.value = item.id
  formVisible.value = true
}

async function onDelete(item) {
  try {
    await ElMessageBox.confirm(
      `确定删除「${item.company} · ${item.position}」这条投递记录吗？`,
      '删除确认',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    )
  } catch {
    return // 用户取消
  }
  await deleteApplication(item.id)
  ElMessage.success('已删除')
  load()
}

/** 拖拽流转：先确认再落库。
 *  拖拽是瞬时动作，而状态流转不可逆（状态机单向），误拖一次就得重建数据才能挽回，
 *  故落库前给一次确认；取消时本地还原卡片位置，不发任何请求。 */
async function onTransit({ item, status }) {
  try {
    await ElMessageBox.confirm(
      `将「${item.company} · ${item.position}」从「${STATUS_LABELS[item.status]}」流转到「${STATUS_LABELS[status]}」？`,
      '流转确认',
      { type: 'info', confirmButtonText: '确认流转', cancelButtonText: '取消' }
    )
  } catch {
    items.value = [...items.value] // 触发看板重建分组，卡片回到原列
    return
  }
  try {
    await changeStatus(item.id, { status })
    const target = items.value.find((it) => it.id === item.id)
    if (target) target.status = status
    ElMessage.success(`已流转至「${STATUS_LABELS[status]}」`)
  } catch {
    load()
  }
}

function onSaved() {
  load()
}

function onImported() {
  load()
}

async function loadTrend(days = trendDays.value) {
  trendDays.value = days
  trendLoading.value = true
  try {
    const data = await getTrend(days)
    trendItems.value = data.items
  } finally {
    trendLoading.value = false
  }
}

function toggleTrend() {
  trendVisible.value = !trendVisible.value
  if (trendVisible.value && trendItems.value.length === 0) loadTrend()
}

// 顶栏「＋ 新增投递」带 query 跳转过来；消费后清掉 query，保证再次点击仍能触发
watch(
  () => route.query.action,
  (action) => {
    if (action !== 'new') return
    openCreate()
    router.replace({ path: '/applications' })
  },
  { immediate: true }
)

onMounted(load)
</script>

<template>
  <div class="apps">
    <Teleport to="#app-header-actions-slot">
      <el-button size="small" :icon="Upload" @click="importVisible = true">批量导入</el-button>
    </Teleport>

    <ApplicationStats :items="items" :truncated="truncated" />

    <div class="apps__toolbar">
      <el-input
        v-model="filters.company"
        class="apps__filter"
        placeholder="公司关键字"
        clearable
        @input="onFilterInput"
      />
      <el-input
        v-model="filters.city"
        class="apps__filter"
        placeholder="城市"
        clearable
        @input="onFilterInput"
      />
      <el-button text type="primary" @click="toggleTrend">
        {{ trendVisible ? '收起趋势' : '查看趋势' }}
      </el-button>
    </div>

    <div v-loading="loading" class="apps__board">
      <StatusKanban
        v-show="!isEmpty"
        :items="items"
        @edit="openEdit"
        @delete="onDelete"
        @transit="onTransit"
      />
      <div v-if="isEmpty" class="apps__empty">
        <el-empty
          :description="isFiltered ? '没有符合条件的记录' : '还没有投递记录，点击右上角「＋ 新增投递」或「批量导入」开始'"
        />
      </div>
    </div>

    <TrendChart
      v-if="trendVisible"
      :items="trendItems"
      :loading="trendLoading"
      :days="trendDays"
      @change-days="loadTrend"
    />

    <ApplicationFormDialog v-model="formVisible" :application-id="editingId" @saved="onSaved" />
    <ApplicationImportDialog v-model="importVisible" @imported="onImported" />
  </div>
</template>

<style scoped>
.apps {
  display: flex;
  flex-direction: column;
  gap: var(--card-gap);
  height: 100%;
}
.apps__toolbar {
  flex: none;
  display: flex;
  align-items: center;
  gap: 10px;
}
.apps__filter {
  width: 180px;
}
.apps__toolbar .el-button {
  margin-left: auto;
}
.apps__board {
  flex: 1;
  min-height: 0;
}
.apps__empty {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
}
</style>
