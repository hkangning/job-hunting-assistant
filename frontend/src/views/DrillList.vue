<script setup>
/**
 * 练习模式·我的题目列表（FR-020 / 接口文档 §3.15）。
 *
 * 「一道题 N 遍」的入口页：卡片给练习进度概况（练了几遍 / 最近得分 / 最好得分），
 * 点进详情页继续练并看跨次进步。**归档题默认不出现**，切「已归档」可查、并可在详情页恢复。
 *
 * 与「八股陪练」（`practice`，FR-009）无关：那边是成套随机题，这边是自己的题反复练。
 */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Plus } from '@element-plus/icons-vue'
import { listDrills } from '../api/drill'
import { sourceLabel } from '../utils/drillMeta'
import { shortDateTime } from '../utils/datetime'
import DrillAddDialog from '../components/drill/DrillAddDialog.vue'
import AppEmpty from '../components/AppEmpty.vue'
import AppError from '../components/AppError.vue'

const router = useRouter()

const items = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = 10
const archived = ref(false)
const source = ref('')
const loading = ref(true)
const loadError = ref('')
const addVisible = ref(false)

/** 来源筛选项：六值全给（RESUME 导入暂缓、只会出现在历史数据；其余五值均可建题）。 */
const SOURCE_OPTIONS = [
  { value: 'CUSTOM', label: '手动新建' },
  { value: 'WRONG', label: '错题本' },
  { value: 'EXPERIENCE', label: '面经' },
  { value: 'JD', label: '投递记录' },
  { value: 'RESUME', label: '画像经历' },
  { value: 'INTRO', label: '自我介绍' }
]

const emptyText = computed(() =>
  archived.value
    ? '还没有归档的题目——归档的题目会收在这里，历史记录仍可回看'
    : '还没有练习题——建一道「自我介绍」，练三遍就能看到进步曲线'
)

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    const data = await listDrills({
      archived: archived.value,
      ...(source.value ? { source: source.value } : {}),
      page: page.value,
      page_size: pageSize
    })
    items.value = data?.items || []
    total.value = data?.total || 0
  } catch (error) {
    // 失败 ≠ 空态：错误块由页面渲染（拦截器另有 toast，此处不再重复弹）
    loadError.value = error?.message || '题目列表加载失败'
  } finally {
    loading.value = false
  }
}

function switchArchived(value) {
  archived.value = value
  page.value = 1
  load()
}

function changeSource() {
  page.value = 1
  load()
}

function changePage(value) {
  page.value = value
  load()
}

/** 建题成功后：回到「进行中」并刷新，用户能立刻看到新题。 */
function onCreated(topic) {
  archived.value = false
  page.value = 1
  load()
  if (topic?.id) router.push(`/drill/${topic.id}`)
}

function openDetail(item) {
  router.push(`/drill/${item.id}`)
}

onMounted(load)
</script>

<template>
  <section class="drill">
    <header class="drill__head">
      <div>
        <h1 class="drill__title">练习模式</h1>
        <p class="drill__sub">一道题反复练——每遍都给点评，练满两遍看跨次进步</p>
      </div>
      <el-button type="primary" :icon="Plus" @click="addVisible = true">新建题目</el-button>
    </header>

    <div class="drill__filters">
      <el-radio-group
        :model-value="archived"
        @update:model-value="switchArchived"
      >
        <el-radio-button :value="false">进行中</el-radio-button>
        <el-radio-button :value="true">已归档</el-radio-button>
      </el-radio-group>
      <el-select
        v-model="source"
        class="drill__source"
        placeholder="全部来源"
        clearable
        @change="changeSource"
      >
        <el-option v-for="opt in SOURCE_OPTIONS" :key="opt.value" :label="opt.label" :value="opt.value" />
      </el-select>
    </div>

    <div v-loading="loading" class="drill__body">
      <AppError v-if="loadError" :message="loadError" @retry="load" />

      <AppEmpty
        v-else-if="!loading && !items.length"
        type="practice"
        :description="emptyText"
        style="--empty-color: var(--m-drill)"
      >
        <el-button type="primary" :icon="Plus" @click="addVisible = true">新建题目</el-button>
      </AppEmpty>

      <template v-else>
        <ul class="drill__cards">
          <li v-for="item in items" :key="item.id" class="card" @click="openDetail(item)">
            <div class="card__head">
              <span class="card__title">{{ item.title }}</span>
              <span class="card__source">{{ sourceLabel(item.source) }}</span>
              <span v-if="item.archived" class="card__archived">已归档</span>
            </div>
            <p class="card__stats">
              <span>练了 <b>{{ item.attempt_count }}</b> 遍</span>
              <span v-if="item.last_score != null">最近 <b>{{ item.last_score }}</b> 分</span>
              <span v-if="item.best_score != null">最好 <b>{{ item.best_score }}</b> 分</span>
              <span v-if="!item.attempt_count" class="card__untouched">还没练过</span>
            </p>
            <p class="card__time">更新于 {{ shortDateTime(item.updated_at) }}</p>
            <span class="card__arrow">›</span>
          </li>
        </ul>

        <el-pagination
          v-if="total > pageSize"
          class="drill__pager"
          layout="prev, pager, next"
          :current-page="page"
          :page-size="pageSize"
          :total="total"
          @current-change="changePage"
        />
      </template>
    </div>

    <DrillAddDialog v-model="addVisible" @created="onCreated" />
  </section>
</template>

<style scoped>
.drill__head {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  margin-bottom: 14px;
}
.drill__title {
  margin: 0;
  font-size: var(--fs-page);
  font-weight: 700;
  color: var(--c-text);
}
.drill__sub {
  margin: 6px 0 0;
  font-size: var(--fs-sm);
  color: var(--c-text-2);
}
.drill__head .el-button {
  margin-left: auto;
}

.drill__filters {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: var(--card-gap);
}
.drill__source {
  width: 150px;
}

.drill__body {
  min-height: 200px;
}
.drill__empty {
  padding: 36px 0;
  text-align: center;
  font-size: var(--fs-sm);
  color: var(--c-text-3);
}

.drill__cards {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin: 0;
  padding: 0;
  list-style: none;
}
.card {
  position: relative;
  padding: 14px var(--card-padding);
  background: var(--c-card);
  border: 1px solid var(--c-border);
  border-left: 3px solid var(--m-drill);
  border-radius: var(--r-card);
  cursor: pointer;
  transition: box-shadow 0.15s ease, transform 0.15s ease;
}
.card:hover {
  box-shadow: 0 2px 10px rgba(42, 39, 64, 0.08);
  transform: translateY(-1px);
}
.card__head {
  display: flex;
  align-items: center;
  gap: 8px;
}
.card__title {
  font-size: var(--fs-title);
  font-weight: 600;
  color: var(--c-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.card__source,
.card__archived {
  flex: 0 0 auto;
  padding: 1px 8px;
  font-size: var(--fs-xs);
  border-radius: var(--r-mark);
}
.card__source {
  color: var(--m-drill);
  background: color-mix(in srgb, var(--m-drill) 12%, var(--c-card));
}
.card__archived {
  color: var(--c-text-3);
  background: var(--c-bg);
}
.card__stats {
  display: flex;
  gap: 14px;
  margin: 8px 0 0;
  font-size: var(--fs-sm);
  color: var(--c-text-2);
}
.card__stats b {
  font-weight: 600;
  color: var(--c-text);
  font-variant-numeric: tabular-nums;
}
.card__untouched {
  color: var(--c-text-3);
}
.card__time {
  margin: 6px 0 0;
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}
.card__arrow {
  position: absolute;
  right: 14px;
  top: 50%;
  transform: translateY(-50%);
  font-size: 20px;
  color: var(--c-text-3);
}
.drill__pager {
  justify-content: center;
  margin-top: var(--card-gap);
}
</style>
