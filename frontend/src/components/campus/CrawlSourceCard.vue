<script setup>
/**
 * 信息源管理（SRS §3.18「源管理」/ 接口文档 §3.16 `/crawl-sources`）：嵌在设置页「信息采集」卡片内。
 *
 * 一厂商一解析器 + 一校一配置：新增一所学校 = 新增一行源（学校名 / 系统类型 / 域名 / 参数），不写代码。
 * 手动触发 = **强制刷新**（不受每日抓取开关与「每源每日 1 次」限制，接口文档 §3.16）；
 * 单源失败不整体报错（逐源结果见明细），指定单源失败才 502 + 70002。
 */
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  createCrawlSource,
  deleteCrawlSource,
  listCrawlSources,
  runCrawl,
  updateCrawlSource
} from '../../api/campus'
import { crawlStatusMeta } from '../../constants/campus'
import { shortDateTime } from '../../utils/datetime'
import AppEmpty from '../AppEmpty.vue'
import AppError from '../AppError.vue'

const SYSTEM_TYPES = [
  { value: '91JOB', label: '91job' },
  { value: 'BYSJY', label: '云就业' },
  { value: 'JYSD', label: '才立方' }
]
// 各系统类型的参数键（与接口文档 §3.16「params 按 system_type 取值」一致）
const PARAM_FIELDS = {
  '91JOB': [{ key: 'xxdm', label: '学校代码 xxdm', required: true, placeholder: '如 10288' }],
  BYSJY: [
    { key: 'panel_name', label: '栏目名 panel_name', required: true, placeholder: '如 宣讲会' },
    { key: 'panel_id', label: '栏目 id panel_id', required: true, placeholder: '如 1' }
  ],
  JYSD: [{ key: 'start_path', label: '入口路径 start_path', required: false, placeholder: '可选，如 /job/list' }]
}

const sources = ref([])
// 首屏初值 true：不闪「还没有信息源」假空态（步骤 27）
const loading = ref(true)
const errorText = ref('')

const dialogVisible = ref(false)
const editingId = ref(null)
const saving = ref(false)
const form = ref(emptyForm())

const running = ref(false)
const runResult = ref(null)

const systemOptions = SYSTEM_TYPES
const paramFields = computed(() => PARAM_FIELDS[form.value.system_type] || [])
const isEdit = computed(() => editingId.value != null)

function emptyForm() {
  return { school_name: '', system_type: '91JOB', domain: '', params: {}, enabled: true }
}

async function load() {
  loading.value = true
  errorText.value = ''
  try {
    const data = await listCrawlSources({ silent: true })
    sources.value = data.items
  } catch (e) {
    errorText.value = e?.message || '信息源加载失败'
    sources.value = []
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editingId.value = null
  form.value = emptyForm()
  dialogVisible.value = true
}

function openEdit(row) {
  editingId.value = row.id
  form.value = {
    school_name: row.school_name,
    system_type: row.system_type,
    domain: row.domain,
    params: { ...(row.params || {}) },
    enabled: row.enabled
  }
  dialogVisible.value = true
}

/** params 只提交当前系统类型认识的键 + 可选 max_pages（空了就不传）。 */
function buildParams() {
  const params = {}
  for (const field of paramFields.value) {
    const value = String(form.value.params[field.key] ?? '').trim()
    if (value) params[field.key] = value
  }
  const maxPages = String(form.value.params.max_pages ?? '').trim()
  if (maxPages) params.max_pages = Number(maxPages)
  return Object.keys(params).length ? params : null
}

const canSave = computed(() => {
  if (!form.value.school_name.trim() || !form.value.domain.trim()) return false
  return paramFields.value.every((f) => !f.required || String(form.value.params[f.key] ?? '').trim())
})

async function onSave() {
  if (!canSave.value || saving.value) return
  saving.value = true
  try {
    const payload = {
      school_name: form.value.school_name.trim(),
      domain: form.value.domain.trim(),
      params: buildParams()
    }
    if (isEdit.value) {
      // 系统类型不支持修改（接口文档 §3.16）——不提交该字段
      await updateCrawlSource(editingId.value, { ...payload, enabled: form.value.enabled })
      ElMessage.success('已保存；该源采集状态已重置，可立即重试')
    } else {
      await createCrawlSource({ ...payload, system_type: form.value.system_type })
      ElMessage.success('已新增信息源')
    }
    dialogVisible.value = false
    load()
  } catch {
    // 拦截器已提示失败原因，不重复弹（步骤 27：双提示消除）
  } finally {
    saving.value = false
  }
}

async function onDelete(row) {
  try {
    await ElMessageBox.confirm(`确定删除信息源「${row.school_name}」吗？`, '删除确认', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消'
    })
  } catch {
    return
  }
  try {
    await deleteCrawlSource(row.id)
  } catch {
    return // 拦截器已提示失败原因
  }
  ElMessage.success('已删除')
  load()
}

async function onRun(sourceId) {
  if (running.value) return
  running.value = true
  runResult.value = null
  try {
    const data = await runCrawl(sourceId ? { source_id: sourceId } : {})
    runResult.value = data
    if (!sourceId) {
      ElMessage.success(`抓取完成：成功 ${data.ok} / 失败 ${data.failed} / 受限 ${data.blocked}`)
    }
    load()
  } catch (e) {
    // 指定单源失败 → 502 + 70002，message 为该源失败原因
    ElMessage.error(e?.message || '抓取失败')
    load()
  } finally {
    running.value = false
  }
}

async function onToggle(row, enabled) {
  try {
    await updateCrawlSource(row.id, { enabled })
    row.enabled = enabled
  } catch {
    row.enabled = !enabled
  }
}

function runDetailLine(detail) {
  const meta = crawlStatusMeta(detail.status)
  const counts = detail.counts || {}
  const parts = [`新增 ${counts.new ?? 0}`, `更新 ${counts.updated ?? 0}`, `变更 ${counts.changed ?? 0}`]
  return `${detail.school_name}：${meta.label}（${parts.join(' / ')}）${detail.error ? `—— ${detail.error}` : ''}`
}

onMounted(load)
</script>

<template>
  <div class="src">
    <div class="src__bar">
      <div class="src__actions">
        <el-button size="small" :loading="running" @click="onRun()">立即抓取全部</el-button>
        <el-button size="small" type="primary" @click="openCreate">新增信息源</el-button>
      </div>
      <span class="src__hint">手动抓取为强制刷新，不受上方「每日抓取」开关限制</span>
    </div>

    <AppError v-if="errorText" class="src__error" :message="errorText" @retry="load" />

    <div v-if="runResult" class="src__result">
      <div class="src__summary">
        本次结果：成功 {{ runResult.ok }} / 失败 {{ runResult.failed }} / 受限 {{ runResult.blocked }}；
        新增 {{ runResult.items_new }} · 更新 {{ runResult.items_updated }} · 变更 {{ runResult.items_changed }} ·
        归档 {{ runResult.expired }}
      </div>
      <ul class="src__details">
        <li v-for="detail in runResult.details" :key="detail.source_id">{{ runDetailLine(detail) }}</li>
      </ul>
    </div>

    <el-table v-loading="loading" :data="sources" size="small" class="src__table">
      <template #empty>
        <AppEmpty
          v-if="!loading && !errorText"
          type="campus"
          size="sm"
          description="还没有信息源——新增一个学校就业网，采集会自动跑"
          style="--empty-color: var(--m-campus)"
        />
      </template>
      <el-table-column prop="school_name" label="学校" min-width="120" />
      <el-table-column label="系统" width="90">
        <template #default="{ row }">
          {{ SYSTEM_TYPES.find((t) => t.value === row.system_type)?.label || row.system_type }}
        </template>
      </el-table-column>
      <el-table-column prop="domain" label="域名" min-width="180" show-overflow-tooltip />
      <el-table-column label="启用" width="76">
        <template #default="{ row }">
          <el-switch :model-value="row.enabled" size="small" @update:model-value="(v) => onToggle(row, v)" />
        </template>
      </el-table-column>
      <el-table-column label="上次抓取" width="130">
        <template #default="{ row }">{{ shortDateTime(row.last_crawl_at) || '—' }}</template>
      </el-table-column>
      <el-table-column label="上次结果" width="110">
        <template #default="{ row }">
          <el-tooltip v-if="row.last_status" :content="row.last_error || row.last_status" placement="top">
            <el-tag size="small" :type="crawlStatusMeta(row.last_status).type" effect="plain">
              {{ crawlStatusMeta(row.last_status).label }}
            </el-tag>
          </el-tooltip>
          <span v-else>—</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="180" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" size="small" :loading="running" @click="onRun(row.id)">抓这个源</el-button>
          <el-button link type="primary" size="small" @click="openEdit(row)">编辑</el-button>
          <el-button link size="small" class="src__del" @click="onDelete(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog
      v-model="dialogVisible"
      :title="isEdit ? '编辑信息源' : '新增信息源'"
      width="520px"
      append-to-body
    >
      <el-form label-width="132px" label-position="left">
        <el-form-item label="学校名称">
          <el-input v-model="form.school_name" maxlength="100" placeholder="如 南京理工大学（下发时作为来源站点名）" />
        </el-form-item>
        <el-form-item label="系统类型">
          <el-select v-model="form.system_type" :disabled="isEdit">
            <el-option v-for="opt in systemOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
          </el-select>
          <span v-if="isEdit" class="src__form-hint">类型不可修改；需换类型请删除后重建</span>
        </el-form-item>
        <el-form-item label="域名">
          <el-input v-model="form.domain" maxlength="200" placeholder="https://njust.91job.org.cn" />
        </el-form-item>
        <el-form-item v-for="field in paramFields" :key="field.key" :label="field.label">
          <el-input v-model="form.params[field.key]" :placeholder="field.placeholder" />
        </el-form-item>
        <el-form-item label="最大页数 max_pages">
          <el-input-number v-model="form.params.max_pages" :min="1" :max="50" controls-position="right" />
          <span class="src__form-hint">可选，留空按默认页数</span>
        </el-form-item>
        <el-form-item v-if="isEdit" label="启用">
          <el-switch v-model="form.enabled" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" :disabled="!canSave" @click="onSave">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.src__bar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 10px;
}
.src__actions {
  display: flex;
  gap: 8px;
}
.src__hint {
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}
/* 错误块外观由 AppError 组件承担，这里只留布局（步骤 27 收口） */
.src__error {
  margin-bottom: 10px;
}
.src__result {
  padding: 10px 12px;
  margin-bottom: 10px;
  background: var(--c-bg);
  border-radius: var(--r-control);
  font-size: var(--fs-sm);
  color: var(--c-text-2);
}
.src__summary {
  color: var(--c-text);
}
.src__details {
  margin: 6px 0 0;
  padding-left: 18px;
  font-size: var(--fs-xs);
  line-height: 1.8;
}
.src__del.el-button {
  color: var(--c-text-3);
}
.src__del.el-button:hover {
  color: var(--el-color-danger);
}
.src__form-hint {
  margin-left: 10px;
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}
</style>
