<script setup>
/**
 * 面经详情（开发计划步骤 17；接口文档 v1.39 §3.10）。
 *
 * 三块内容：**提取状态区**（无条目时常驻：入口 / 进度 / 失败重试，逻辑在 ExperienceExtract）、
 * **结构化条目**、**原文折叠块**（有条目默认收起；无条目时展开——提取失败 / 未提取时原文是主角）。
 *
 * `?item=<id>`：从检索结果跳来，滚动定位到该条目并短暂高亮；
 * `?extract=1`：新增时点「保存并提取」跳来，进入即自动发起提取。
 */
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Back, Refresh } from '@element-plus/icons-vue'
import { deleteExperience, getExperience } from '../api/experiences'
import { textLength } from '../utils/text'
import { shortDateTime } from '../utils/datetime'
import ExperienceExtract from '../components/experience/ExperienceExtract.vue'
import AppError from '../components/AppError.vue'

const route = useRoute()
const router = useRouter()
const experienceId = Number(route.params.id)

const detail = ref(null)
const loading = ref(true)
const errorMsg = ref('')
const showOriginal = ref(false)
const highlightItemId = ref(null)
const reExtracting = ref(false) // 「重新提取」流程开启（提取区此时也常驻显示）
const extracting = ref(false) // 提取进行中（提取区 status=running，据此禁用删除）

const items = computed(() => detail.value?.items || [])
const hasItems = computed(() => items.value.length > 0)
const title = computed(() =>
  detail.value
    ? `${detail.value.company || '未填公司'} · ${detail.value.position || '未填岗位'}`
    : '加载中…'
)

// 有条目 → 原文收起（主角是条目）；无条目 → 展开（提取失败 / 未提取时原文是主角）
watch(hasItems, (has) => (showOriginal.value = !has), { immediate: true })

async function load() {
  loading.value = true
  errorMsg.value = ''
  try {
    detail.value = await getExperience(experienceId)
    locateFromQuery()
  } catch (error) {
    errorMsg.value = error?.message || '加载失败'
  } finally {
    loading.value = false
  }
}

/** 提取完成：重拉详情拿含 id 的完整条目；重拉失败以 done 事件里的 items 兜底渲染。
 * 识别出的公司名先用 `extra.company` 即时回填（仅原值为空时，与后端同口径）——不重拉也能立即显示。 */
async function onExtracted({ items: itemsFromDone, company }) {
  if (company && detail.value && !detail.value.company) {
    detail.value.company = company
  }
  try {
    detail.value = await getExperience(experienceId)
  } catch {
    if (detail.value) {
      detail.value.items = (itemsFromDone || []).map((it, index) => ({ id: `done-${index}`, ...it }))
    }
  }
  reExtracting.value = false
}

/** 「重新提取」：后端为「提取即替换」语义（IS-53），复调提取端点即整篇重做——先确认再发。 */
async function onReExtract() {
  try {
    await ElMessageBox.confirm(
      `重新提取会重新调用 AI，并用新结果替换现有 ${items.value.length} 条条目。`,
      '重新提取',
      { type: 'warning', confirmButtonText: '重新提取', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  reExtracting.value = true
}

/** 提取区状态上报：提取中禁用删除——删除与提取落库并发时，条目并入会撞外键失败。 */
function onExtractState(state) {
  extracting.value = state === 'running'
}

function locateFromQuery() {
  const id = Number(route.query.item)
  if (!id) return
  highlightItemId.value = id
  nextTick(() => {
    document.getElementById(`exp-item-${id}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    setTimeout(() => (highlightItemId.value = null), 2400)
  })
}

async function onDelete() {
  try {
    await ElMessageBox.confirm(
      items.value.length
        ? `删除这篇面经？原文与 ${items.value.length} 条结构化条目将一并删除。`
        : '删除这篇面经？原文将一并删除。',
      '删除确认',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  try {
    await deleteExperience(experienceId)
  } catch {
    return // 拦截器已提示失败原因
  }
  ElMessage.success('已删除')
  router.push('/experiences')
}

function backToList() {
  router.push('/experiences')
}

onMounted(load)
</script>

<template>
  <section class="detail">
    <header class="detail__head">
      <el-button link :icon="Back" @click="backToList">返回面经</el-button>
      <span class="detail__title">{{ title }}</span>
      <span v-if="detail?.source" class="detail__source">{{ detail.source }}</span>
      <span v-if="detail" class="detail__meta">{{ shortDateTime(detail.created_at) }}</span>
      <el-button
        v-if="detail"
        class="detail__del"
        link
        type="danger"
        :disabled="extracting"
        @click="onDelete"
        >删除</el-button
      >
    </header>

    <AppError v-if="errorMsg" class="detail__error" :message="errorMsg" @retry="load">
      <el-button size="small" @click="backToList">返回列表</el-button>
    </AppError>

    <div v-else v-loading="loading" class="detail__body">
      <template v-if="detail">
        <!-- 提取区：无条目时常驻（入口 / 进度 / 失败重试）；「重新提取」运行 / 失败期间也显示 -->
        <ExperienceExtract
          v-if="!hasItems || reExtracting"
          :experience-id="experienceId"
          :auto-start="route.query.extract === '1' || reExtracting"
          :closable="hasItems"
          @extracted="onExtracted"
          @close="reExtracting = false"
          @state="onExtractState"
        />

        <!-- 结构化条目（重新提取期间保持可见——旧条目到新结果并库前仍是用户可读的内容） -->
        <section v-if="hasItems">
          <h3 class="detail__section-title">
            结构化条目<span class="detail__count">{{ items.length }}</span>
            <el-button
              class="detail__reextract"
              link
              type="primary"
              :icon="Refresh"
              :disabled="extracting"
              @click="onReExtract"
              >重新提取</el-button
            >
          </h3>
          <ol class="detail__list">
            <li
              v-for="(item, index) in items"
              :id="`exp-item-${item.id}`"
              :key="item.id"
              class="detail__item"
              :class="{ 'detail__item--hl': highlightItemId === item.id }"
            >
              <span class="detail__index">{{ index + 1 }}</span>
              <div class="detail__item-main">
                <p class="detail__q">{{ item.question }}</p>
                <p v-if="item.answer_points" class="detail__a">{{ item.answer_points }}</p>
              </div>
            </li>
          </ol>
        </section>

        <!-- 原文：有条目默认收起；无条目（提取未完成）时展开 -->
        <section class="detail__original">
          <button type="button" class="detail__toggle" @click="showOriginal = !showOriginal">
            {{ showOriginal ? '收起原文' : `查看原文（${textLength(detail.original_text)} 字）` }}
          </button>
          <p v-if="showOriginal" class="detail__text">{{ detail.original_text }}</p>
        </section>
      </template>
    </div>
  </section>
</template>

<style scoped>
.detail {
  background: var(--c-card);
  border: 1px solid var(--c-border);
  border-radius: var(--r-card);
  box-shadow: 0 1px 2px rgba(42, 39, 64, 0.05);
  padding: var(--card-padding);
}

.detail__head {
  display: flex;
  align-items: center;
  gap: 12px;
  padding-bottom: 12px;
  margin-bottom: var(--card-gap);
  border-bottom: 1px solid var(--c-divider);
}
.detail__title {
  font-size: var(--fs-title);
  font-weight: 600;
  color: var(--c-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.detail__source {
  flex: 0 0 auto;
  padding: 1px 8px;
  font-size: var(--fs-xs);
  color: var(--c-text-2);
  background: var(--c-bg);
  border-radius: var(--r-mark);
}
.detail__meta {
  flex: 0 0 auto;
  font-size: var(--fs-sm);
  color: var(--c-text-3);
  font-variant-numeric: tabular-nums;
}
.detail__del {
  margin-left: auto;
}

/* 错误块外观由 AppError 组件承担，这里只留布局（步骤 27 收口） */
.detail__error {
  margin-bottom: var(--card-gap);
}

.detail__body {
  display: flex;
  flex-direction: column;
  gap: var(--card-gap);
  min-height: 120px;
}

.detail__section-title {
  display: flex;
  align-items: center;
  margin: 0 0 10px;
  font-size: var(--fs-title);
  font-weight: 700;
  color: var(--c-text);
}
.detail__reextract {
  margin-left: auto; /* 贴右：与「删除」同一视觉列 */
  font-weight: 400;
}
.detail__count {
  display: inline-block;
  margin-left: 8px;
  padding: 1px 8px;
  font-size: var(--fs-xs);
  font-weight: 400;
  color: var(--m-experience);
  background: color-mix(in srgb, var(--m-experience) 12%, var(--c-card));
  border-radius: var(--r-mark);
  vertical-align: 2px;
}

.detail__list {
  display: grid;
  gap: 8px;
  margin: 0;
  padding: 0;
  list-style: none;
}
.detail__item {
  display: flex;
  gap: 12px;
  padding: 12px 14px;
  border: 1px solid var(--c-border);
  border-radius: var(--r-control);
  transition: background 0.4s, border-color 0.4s;
}
/* 检索跳转定位后的短暂高亮 */
.detail__item--hl {
  border-color: var(--m-experience);
  background: color-mix(in srgb, var(--m-experience) 8%, var(--c-card));
}
.detail__index {
  flex: 0 0 auto;
  width: 22px;
  height: 22px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: var(--fs-xs);
  color: var(--m-experience);
  background: color-mix(in srgb, var(--m-experience) 12%, var(--c-card));
  border-radius: 50%;
}
.detail__item-main {
  flex: 1;
  min-width: 0;
}
.detail__q {
  margin: 0;
  font-size: var(--fs-body);
  color: var(--c-text);
  line-height: 1.7;
}
.detail__a {
  margin: 6px 0 0;
  font-size: var(--fs-sm);
  color: var(--c-text-2);
  line-height: 1.8;
  white-space: pre-wrap;
  word-break: break-word;
}

.detail__original {
  padding-top: 4px;
}
.detail__toggle {
  padding: 0;
  font: inherit;
  font-size: var(--fs-sm);
  color: var(--brand);
  background: transparent;
  border: 0;
  cursor: pointer;
}
.detail__text {
  margin: 10px 0 0;
  padding: 12px 14px;
  font-size: var(--fs-sm);
  color: var(--c-text-2);
  line-height: 1.9;
  background: var(--c-bg);
  border-radius: var(--r-control);
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
