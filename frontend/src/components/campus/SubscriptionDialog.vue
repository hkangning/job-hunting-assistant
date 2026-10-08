<script setup>
/**
 * 我的订阅（FR-022 / 接口文档 §3.16 `/subscriptions`）：规则列表 + 新建 / 编辑 / 启停 / 删除。
 *
 * 匹配语义（界面须讲清，避免「填了没生效」的困惑）：**维度之间为「与」，同一维度内为「或」，
 * 留空 = 该维度不限**。服务端对数组另有清洗（去空白 / 去重 / 单项 ≤50 字 / 每维 ≤20 项），
 * 前端先按同一口径约束，避免提交了才发现被截断。
 */
import { computed, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  createSubscription,
  deleteSubscription,
  listSubscriptions,
  updateSubscription
} from '../../api/campus'
import AppEmpty from '../AppEmpty.vue'
import AppError from '../AppError.vue'

const props = defineProps({
  modelValue: { type: Boolean, default: false }
})
const emit = defineEmits(['update:modelValue'])

const ITEM_MAX = 50
const DIM_MAX = 20
const INFO_TYPE_OPTIONS = [
  { value: 'TALK', label: '宣讲会' },
  { value: 'FAIR', label: '双选会' },
  { value: 'JOB', label: '岗位' }
]

const rules = ref([])
// 首屏初值 true：不闪「还没有订阅规则」假空态（步骤 27）
const loading = ref(true)
const errorText = ref('')

const editing = ref(null) // null = 未开表单；{} = 新建；{id, ...} = 编辑
const form = ref(emptyForm())
const saving = ref(false)

function emptyForm() {
  return { name: '', keywords: [], companies: [], cities: [], info_types: [], enabled: true }
}

const canSave = computed(() => form.value.name.trim().length > 0 && form.value.name.trim().length <= ITEM_MAX)

async function load() {
  loading.value = true
  errorText.value = ''
  try {
    rules.value = await listSubscriptions({ silent: true })
  } catch (e) {
    errorText.value = e?.message || '订阅规则加载失败'
    rules.value = []
  } finally {
    loading.value = false
  }
}

watch(
  () => props.modelValue,
  (visible) => {
    if (!visible) return
    editing.value = null
    load()
  },
  { immediate: true }
)

function openCreate() {
  editing.value = {}
  form.value = emptyForm()
}

function openEdit(rule) {
  editing.value = rule
  form.value = {
    name: rule.name,
    keywords: [...(rule.keywords || [])],
    companies: [...(rule.companies || [])],
    cities: [...(rule.cities || [])],
    info_types: [...(rule.info_types || [])],
    enabled: !!rule.enabled
  }
}

/** 数组约束与后端同口径：去空白 / 去重 / 单项 ≤50 字 / 每维 ≤20 项。 */
function normalizeList(list) {
  const out = []
  for (const raw of list || []) {
    const item = String(raw).trim().slice(0, ITEM_MAX)
    if (item && !out.includes(item)) out.push(item)
    if (out.length >= DIM_MAX) break
  }
  return out
}

async function onSave() {
  if (!canSave.value || saving.value) return
  saving.value = true
  try {
    const payload = {
      name: form.value.name.trim(),
      keywords: normalizeList(form.value.keywords),
      companies: normalizeList(form.value.companies),
      cities: normalizeList(form.value.cities),
      info_types: normalizeList(form.value.info_types),
      enabled: form.value.enabled
    }
    if (editing.value?.id) {
      await updateSubscription(editing.value.id, payload) // 四维全量下发：空数组 = 清空该维度
      ElMessage.success('已保存')
    } else {
      await createSubscription(payload)
      ElMessage.success('已创建')
    }
    editing.value = null
    load()
  } catch {
    // 拦截器已提示失败原因，不重复弹（步骤 27：双提示消除）
  } finally {
    saving.value = false
  }
}

async function onToggle(rule, enabled) {
  try {
    const updated = await updateSubscription(rule.id, { enabled })
    Object.assign(rule, updated)
  } catch {
    rule.enabled = !enabled // 失败回滚开关
  }
}

async function onDelete(rule) {
  try {
    await ElMessageBox.confirm(`确定删除订阅规则「${rule.name}」吗？`, '删除确认', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消'
    })
  } catch {
    return
  }
  try {
    await deleteSubscription(rule.id)
  } catch {
    return // 拦截器已提示失败原因
  }
  ElMessage.success('已删除')
  load()
}

/** 维度摘要：空 = 不限。 */
function summary(list) {
  return list && list.length ? list.join('、') : '不限'
}
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    title="我的订阅"
    width="640px"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <p class="sub__note">
      订阅规则命中后写入站内提醒（概览与提醒列表可见）。匹配语义：<b>维度之间为「与」、同一维度内为「或」</b>，留空 = 该维度不限。
    </p>

    <AppError v-if="errorText" class="sub__error" size="sm" :message="errorText" @retry="load" />

    <!-- 表单（新建 / 编辑） -->
    <div v-if="editing" class="sub__form">
      <el-form label-width="76px" label-position="left">
        <el-form-item label="规则名称">
          <el-input v-model="form.name" :maxlength="ITEM_MAX" placeholder="如：南京的后端岗位" />
        </el-form-item>
        <el-form-item label="关键词">
          <el-select
            v-model="form.keywords"
            multiple
            filterable
            allow-create
            default-first-option
            :multiple-limit="DIM_MAX"
            placeholder="回车添加；命中岗位 / 活动标题或公司名"
          />
        </el-form-item>
        <el-form-item label="公司">
          <el-select
            v-model="form.companies"
            multiple
            filterable
            allow-create
            default-first-option
            :multiple-limit="DIM_MAX"
            placeholder="回车添加；公司名（忽略括号后缀）"
          />
        </el-form-item>
        <el-form-item label="城市">
          <el-select
            v-model="form.cities"
            multiple
            filterable
            allow-create
            default-first-option
            :multiple-limit="DIM_MAX"
            placeholder="回车添加；岗位按城市、活动按地点"
          />
        </el-form-item>
        <el-form-item label="信息类型">
          <el-select v-model="form.info_types" multiple :multiple-limit="3" placeholder="不选 = 不限">
            <el-option v-for="opt in INFO_TYPE_OPTIONS" :key="opt.value" :label="opt.label" :value="opt.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="form.enabled" />
        </el-form-item>
      </el-form>
      <div class="sub__form-actions">
        <el-button @click="editing = null">取消</el-button>
        <el-button type="primary" :loading="saving" :disabled="!canSave" @click="onSave">保存</el-button>
      </div>
    </div>

    <!-- 规则列表 -->
    <template v-else>
      <AppEmpty
        v-if="!loading && !rules.length && !errorText"
        type="campus"
        size="sm"
        description="还没有订阅规则——建一条，命中「当日新入库 / 变更」的校招信息就会写进站内提醒。"
        style="--empty-color: var(--m-campus)"
      />
      <ul v-else v-loading="loading" class="sub__list">
        <li v-for="rule in rules" :key="rule.id" class="sub__item" :class="{ 'sub__item--off': !rule.enabled }">
          <div class="sub__main">
            <div class="sub__name">{{ rule.name }}</div>
            <div class="sub__meta">
              <span>关键词：{{ summary(rule.keywords) }}</span>
              <span>公司：{{ summary(rule.companies) }}</span>
              <span>城市：{{ summary(rule.cities) }}</span>
              <span>
                类型：{{
                  rule.info_types.length
                    ? rule.info_types.map((t) => INFO_TYPE_OPTIONS.find((o) => o.value === t)?.label || t).join('、')
                    : '不限'
                }}
              </span>
            </div>
          </div>
          <el-switch :model-value="rule.enabled" @update:model-value="(v) => onToggle(rule, v)" />
          <el-button link type="primary" @click="openEdit(rule)">编辑</el-button>
          <el-button link class="sub__del" @click="onDelete(rule)">删除</el-button>
        </li>
      </ul>

      <div class="sub__actions">
        <el-button type="primary" @click="openCreate">新建规则</el-button>
      </div>
    </template>
  </el-dialog>
</template>

<style scoped>
.sub__note {
  margin: 0 0 12px;
  font-size: var(--fs-sm);
  color: var(--c-text-3);
  line-height: 1.7;
}
/* 错误块外观由 AppError 组件承担，这里只留布局（步骤 27 收口） */
.sub__error {
  margin-bottom: 10px;
}
.sub__empty {
  margin: 0 0 12px;
  font-size: var(--fs-sm);
  color: var(--c-text-3);
}
.sub__list {
  display: grid;
  gap: 8px;
  margin: 0 0 12px;
  padding: 0;
  list-style: none;
}
.sub__item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid var(--c-border);
  border-radius: var(--r-control);
}
.sub__item--off {
  opacity: 0.6;
}
.sub__main {
  flex: 1;
  min-width: 0;
}
.sub__name {
  font-size: var(--fs-body);
  color: var(--c-text);
  font-weight: 600;
}
.sub__meta {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 4px;
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}
.sub__del.el-button {
  color: var(--c-text-3);
}
.sub__del.el-button:hover {
  color: var(--el-color-danger);
}
.sub__actions {
  display: flex;
  justify-content: flex-end;
}
.sub__form-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 4px;
}
</style>
