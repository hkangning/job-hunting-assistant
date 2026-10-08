<script setup>
/**
 * 面经整理（FR-008 / 开发计划步骤 17；接口文档 v1.33 §3.10）。
 *
 * 两个 Tab：**面经库**（列表 + 粘贴新增）/ **条目检索**（跨面经按关键词搜问题条目）。
 * 新增成功后跳详情页；「保存并提取」的跳转带 `?extract=1`，提取由详情页自动跑（提取逻辑只有一份）。
 */
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { deleteExperience, listExperiences, searchExperienceItems } from '../api/experiences'
import { shortDateTime } from '../utils/datetime'
import ExperienceCreateDialog from '../components/experience/ExperienceCreateDialog.vue'
import AppEmpty from '../components/AppEmpty.vue'
import AppError from '../components/AppError.vue'

const router = useRouter()

const tab = ref('library') // 'library' | 'search'

// ---------- 面经库 ----------
const page = ref(1)
const pageSize = ref(10)
const items = ref([])
const total = ref(0)
// 首屏初值 true：不闪「粘贴一篇面经」假空态（步骤 27）
const loading = ref(true)
const libraryError = ref('')

// ---------- 条目检索 ----------
const keyword = ref('')
const searchPage = ref(1)
const searchItems = ref([])
const searchTotal = ref(0)
const searching = ref(false)
const searchError = ref('')
let searchTimer = null

const createVisible = ref(false)

function title(item) {
  return `${item.company || '未填公司'} · ${item.position || '未填岗位'}`
}

async function loadLibrary() {
  loading.value = true
  libraryError.value = ''
  try {
    const data = await listExperiences({ page: page.value, page_size: pageSize.value })
    items.value = data.items || []
    total.value = data.total || 0
  } catch (error) {
    // 失败 ≠ 空态：错误块由页面渲染（拦截器另有 toast，此处不再重复弹）
    libraryError.value = error?.message || '面经列表加载失败'
  } finally {
    loading.value = false
  }
}

function changePage(value) {
  page.value = value
  loadLibrary()
}

/** 检索输入防抖 300ms（与投递页 / 错题本同一形态） */
function onKeywordInput() {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    searchPage.value = 1
    loadSearch()
  }, 300)
}

async function loadSearch() {
  const kw = keyword.value.trim()
  if (!kw) {
    searchItems.value = []
    searchTotal.value = 0
    searchError.value = ''
    return
  }
  searching.value = true
  searchError.value = ''
  try {
    const data = await searchExperienceItems({
      keyword: kw,
      page: searchPage.value,
      page_size: pageSize.value
    })
    searchItems.value = data.items || []
    searchTotal.value = data.total || 0
  } catch (error) {
    searchError.value = error?.message || '条目检索失败'
  } finally {
    searching.value = false
  }
}

function changeSearchPage(value) {
  searchPage.value = value
  loadSearch()
}

function openDetail(item) {
  router.push(`/experiences/${item.id}`)
}

/** 检索结果 → 详情页并定位到该条目（`?item=` 由详情页消费） */
function openItem(item) {
  router.push({ path: `/experiences/${item.experience_id}`, query: { item: item.id } })
}

async function onDelete(item) {
  try {
    await ElMessageBox.confirm(
      item.item_count
        ? `删除「${title(item)}」？原文与 ${item.item_count} 条结构化条目将一并删除。`
        : `删除「${title(item)}」？原文将一并删除。`,
      '删除确认',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  try {
    await deleteExperience(item.id)
  } catch {
    return // 拦截器已提示失败原因
  }
  ElMessage.success('已删除')
  loadLibrary()
}

/** 新增成功：跳详情页；「保存并提取」带 extract=1 由详情页自动跑提取。 */
function onCreated({ experience, withExtract }) {
  router.push({
    path: `/experiences/${experience.id}`,
    query: withExtract ? { extract: '1' } : {}
  })
}

onMounted(loadLibrary)
</script>

<template>
  <section class="exp">
    <header class="exp__head">
      <div class="seg">
        <button
          type="button"
          class="seg__item"
          :class="{ 'seg__item--on': tab === 'library' }"
          @click="tab = 'library'"
        >
          面经库
        </button>
        <button
          type="button"
          class="seg__item"
          :class="{ 'seg__item--on': tab === 'search' }"
          @click="tab = 'search'"
        >
          条目检索
        </button>
      </div>
      <el-button type="primary" @click="createVisible = true">粘贴面经</el-button>
    </header>

    <!-- 面经库 -->
    <template v-if="tab === 'library'">
      <AppError v-if="libraryError" :message="libraryError" @retry="loadLibrary" />
      <AppEmpty
        v-else-if="!loading && !items.length"
        type="experience"
        description="粘贴一篇面经，AI 自动拆成结构化条目，关键词一搜就命中"
        style="--empty-color: var(--m-experience)"
      >
        <el-button type="primary" @click="createVisible = true">粘贴面经</el-button>
      </AppEmpty>

      <template v-else>
        <ul v-loading="loading" class="exp__list">
          <li v-for="item in items" :key="item.id" class="exp__item" @click="openDetail(item)">
            <div class="exp__main">
              <span class="exp__title">{{ title(item) }}</span>
              <div class="exp__meta">
                <span v-if="item.source" class="exp__source">{{ item.source }}</span>
                <span :class="item.item_count ? 'exp__count' : 'exp__none'">
                  {{ item.item_count ? `${item.item_count} 条问题` : '未提取' }}
                </span>
                <span>{{ shortDateTime(item.created_at) }}</span>
              </div>
            </div>
            <el-button link type="danger" @click.stop="onDelete(item)">删除</el-button>
          </li>
        </ul>

        <el-pagination
          v-if="total > pageSize"
          class="exp__pager"
          layout="prev, pager, next"
          :current-page="page"
          :page-size="pageSize"
          :total="total"
          @current-change="changePage"
        />
      </template>
    </template>

    <!-- 条目检索 -->
    <template v-else>
      <el-input
        v-model="keyword"
        class="exp__search"
        maxlength="50"
        clearable
        placeholder="输入关键词，跨全部面经搜索面试问题（如：JVM、索引、自我介绍）"
        @input="onKeywordInput"
      />

      <p v-if="!keyword.trim()" class="exp__search-hint">
        输入关键词后自动搜索；命中结果可跳转到所属面经并定位到该条目。
      </p>

      <AppError v-else-if="searchError" :message="searchError" @retry="loadSearch" />

      <AppEmpty
        v-else-if="!searching && !searchItems.length"
        type="experience"
        :description="`没有找到含「${keyword.trim()}」的条目`"
        style="--empty-color: var(--m-experience)"
      />

      <template v-else>
        <ul v-loading="searching" class="exp__list">
          <li v-for="item in searchItems" :key="item.id" class="exp__item" @click="openItem(item)">
            <div class="exp__main">
              <span class="exp__company">{{ item.company || '未填公司' }}</span>
              <p class="exp__q">{{ item.question }}</p>
              <p v-if="item.answer_points" class="exp__a">{{ item.answer_points }}</p>
            </div>
          </li>
        </ul>

        <el-pagination
          v-if="searchTotal > pageSize"
          class="exp__pager"
          layout="prev, pager, next"
          :current-page="searchPage"
          :page-size="pageSize"
          :total="searchTotal"
          @current-change="changeSearchPage"
        />
      </template>
    </template>

    <ExperienceCreateDialog v-model="createVisible" @created="onCreated" />
  </section>
</template>

<style scoped>
.exp {
  background: var(--c-card);
  border: 1px solid var(--c-border);
  border-radius: var(--r-card);
  box-shadow: 0 1px 2px rgba(42, 39, 64, 0.05);
  padding: var(--card-padding);
}

.exp__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: var(--card-gap);
}

/* 分段控件：与面试列表 / 错题本同一形态（选中态实底） */
.seg {
  display: flex;
  gap: 4px;
  padding: 3px;
  background: var(--c-bg);
  border-radius: var(--r-control);
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

.exp__list {
  display: grid;
  gap: 8px;
  margin: 0;
  padding: 0;
  list-style: none;
  min-height: 60px;
}
.exp__item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 14px;
  border: 1px solid var(--c-border);
  border-radius: var(--r-control);
  cursor: pointer;
  transition: border-color 0.15s;
}
.exp__item:hover {
  border-color: var(--m-experience);
}
.exp__main {
  flex: 1;
  min-width: 0;
}
.exp__title {
  display: block;
  font-size: var(--fs-body);
  color: var(--c-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.exp__meta {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 6px;
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}
.exp__source {
  padding: 1px 6px;
  color: var(--c-text-2);
  background: var(--c-bg);
  border-radius: var(--r-mark);
}
.exp__count {
  color: var(--m-experience);
}
.exp__none {
  padding: 1px 6px;
  color: var(--c-text-3);
  background: var(--c-bg);
  border-radius: var(--r-mark);
}

/* 检索：结果项以问题为主，要点两行截断 */
.exp__search {
  margin-bottom: 12px;
}
.exp__search-hint {
  margin: 24px 0;
  text-align: center;
  font-size: var(--fs-sm);
  color: var(--c-text-3);
}
.exp__company {
  display: inline-block;
  margin-bottom: 4px;
  padding: 1px 8px;
  font-size: var(--fs-xs);
  color: var(--m-experience);
  background: color-mix(in srgb, var(--m-experience) 12%, var(--c-card));
  border-radius: var(--r-mark);
}
.exp__q {
  margin: 0;
  font-size: var(--fs-body);
  color: var(--c-text);
  line-height: 1.7;
}
.exp__a {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  margin: 4px 0 0;
  font-size: var(--fs-sm);
  color: var(--c-text-2);
  line-height: 1.7;
}

.exp__pager {
  justify-content: flex-end;
  margin-top: var(--card-gap);
}
</style>
