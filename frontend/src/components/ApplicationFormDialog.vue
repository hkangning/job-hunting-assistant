<script setup>
// 投递新增/编辑表单（FR-002）。编辑时状态只读：接口文档 §3.3 明确 PUT 不改 status
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { createApplication, getApplication, updateApplication } from '../api/applications'
import { APPLICATION_STATUSES, CLOSE_REASONS, STATUS_COLORS, STATUS_LABELS } from '../constants/application'
import { CITY_OPTIONS } from '../constants/regions'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  applicationId: { type: Number, default: null }
})
const emit = defineEmits(['update:modelValue', 'saved', 'delete'])

const formRef = ref(null)
const saving = ref(false)
const loading = ref(false)
const isEdit = computed(() => props.applicationId != null)
// 级联选择器的值（路径数组），与 form.city 双向对应
const cityPath = ref([])

const form = reactive({
  company: '',
  position: '',
  city: '',
  expected_salary: '',
  applied_at: '',
  channel: '',
  status: 'APPLIED',
  close_reason: null,
  next_event_at: null,
  remark: ''
})

// 与后端 ApplicationCreate DTO 对齐（接口文档 §3.3）
const rules = {
  company: [
    { required: true, message: '请填写公司名称', trigger: 'blur' },
    { max: 100, message: '公司名称不超过 100 字', trigger: 'blur' }
  ],
  position: [
    { required: true, message: '请填写岗位名称', trigger: 'blur' },
    { max: 100, message: '岗位名称不超过 100 字', trigger: 'blur' }
  ],
  city: [{ max: 50, message: '城市不超过 50 字', trigger: 'blur' }],
  expected_salary: [{ max: 50, message: '期望薪资不超过 50 字', trigger: 'blur' }],
  channel: [{ max: 50, message: '投递渠道不超过 50 字', trigger: 'blur' }]
}

/** 城市名 → 级联路径（如 ['江苏省','南京']）；直辖市为单级；列表外返回空 */
function pathOfCity(city) {
  if (!city) return []
  for (const p of CITY_OPTIONS) {
    if (!p.children) {
      if (p.value === city) return [p.value]
      continue
    }
    if (p.children.some((c) => c.value === city)) return [p.value, city]
  }
  return []
}

function isKnownCity(city) {
  if (!city) return true
  return CITY_OPTIONS.some((p) =>
    p.children ? p.children.some((c) => c.value === city) : p.value === city
  )
}

/** 列表外的城市（历史自由文本）临时补一个一级选项，保证能回显、不被静默清空 */
const cityOptions = computed(() => {
  if (isKnownCity(form.city)) return CITY_OPTIONS
  return [...CITY_OPTIONS, { value: form.city, label: `${form.city}（原值，不在省市列表中）` }]
})

function onCityChange(path) {
  form.city = Array.isArray(path) && path.length ? path[path.length - 1] : ''
}

function todayString() {
  const now = new Date()
  const m = String(now.getMonth() + 1).padStart(2, '0')
  const d = String(now.getDate()).padStart(2, '0')
  return `${now.getFullYear()}-${m}-${d}`
}

function resetForm() {
  Object.assign(form, {
    company: '',
    position: '',
    city: '',
    expected_salary: '',
    applied_at: todayString(),
    channel: '',
    status: 'APPLIED',
    close_reason: null,
    next_event_at: null,
    remark: ''
  })
  cityPath.value = []
  formRef.value?.clearValidate()
}

async function loadDetail(id) {
  loading.value = true
  try {
    const detail = await getApplication(id)
    Object.assign(form, {
      company: detail.company,
      position: detail.position,
      city: detail.city || '',
      expected_salary: detail.expected_salary || '',
      applied_at: detail.applied_at || todayString(),
      channel: detail.channel || '',
      status: detail.status,
      close_reason: detail.close_reason || null,
      next_event_at: detail.next_event_at,
      remark: detail.remark || ''
    })
    cityPath.value = pathOfCity(form.city)
  } finally {
    loading.value = false
  }
}

// 打开时初始化：新增→清空并取当天；编辑→回填全部字段（PUT 是全量更新，必须回填）
watch(
  () => props.modelValue,
  (visible) => {
    if (!visible) return
    if (isEdit.value) loadDetail(props.applicationId)
    else resetForm()
  }
)

/** 请求删除当前记录：确认与接口调用交由父组件（删除流程保持单一出处），成功后才关闭本对话框 */
function emitDelete() {
  emit('delete', { id: props.applicationId, company: form.company, position: form.position })
}

function close() {
  emit('update:modelValue', false)
}

/** 空串转 null：避免把 "" 存进可空字段 */
function orNull(value) {
  const text = (value || '').trim()
  return text === '' ? null : text
}

async function submit() {
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return

  const payload = {
    company: form.company.trim(),
    position: form.position.trim(),
    city: orNull(form.city),
    expected_salary: orNull(form.expected_salary),
    applied_at: form.applied_at || null,
    channel: orNull(form.channel),
    next_event_at: form.next_event_at || null,
    remark: orNull(form.remark)
  }
  // status 仅新增时可指定（编辑走看板拖拽，PUT 不改 status）
  if (!isEdit.value) payload.status = form.status
  // 结束原因仅已结束的记录可改（其余状态传该字段会被后端拒为 10001）
  if (isEdit.value && form.status === 'CLOSED') payload.close_reason = form.close_reason

  saving.value = true
  try {
    if (isEdit.value) await updateApplication(props.applicationId, payload)
    else await createApplication(payload)
    ElMessage.success(isEdit.value ? '已保存' : '已新增')
    emit('saved')
    close()
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    :title="isEdit ? '编辑投递' : '新增投递'"
    width="560px"
    @update:model-value="close"
  >
    <el-form ref="formRef" v-loading="loading" :model="form" :rules="rules" label-width="120px">
      <el-form-item label="公司名称" prop="company">
        <el-input v-model="form.company" maxlength="100" placeholder="如：浩鲸科技" />
      </el-form-item>
      <el-form-item label="岗位名称" prop="position">
        <el-input v-model="form.position" maxlength="100" placeholder="如：Java 开发" />
      </el-form-item>
      <el-form-item label="工作城市" prop="city">
        <el-cascader
          v-model="cityPath"
          class="form-city"
          :options="cityOptions"
          :show-all-levels="false"
          placeholder="可搜索城市，或先选省份"
          clearable
          filterable
          popper-class="city-cascader-popper"
          @change="onCityChange"
        />
      </el-form-item>
      <el-form-item label="期望薪资" prop="expected_salary">
        <el-input v-model="form.expected_salary" maxlength="50" placeholder="如：13k*14" />
      </el-form-item>
      <el-form-item label="投递日期" prop="applied_at">
        <el-date-picker v-model="form.applied_at" type="date" value-format="YYYY-MM-DD" placeholder="默认当天" />
      </el-form-item>
      <el-form-item label="投递渠道" prop="channel">
        <el-input v-model="form.channel" maxlength="50" placeholder="如：官网 / BOSS / 内推" />
      </el-form-item>
      <el-form-item label="进度状态">
        <el-select v-if="!isEdit" v-model="form.status" style="width: 100%">
          <el-option v-for="s in APPLICATION_STATUSES" :key="s.value" :label="s.label" :value="s.value" />
        </el-select>
        <template v-else>
          <span class="form-status__dot" :style="{ background: STATUS_COLORS[form.status] }"></span>
          <span class="form-status__text">{{ STATUS_LABELS[form.status] }}</span>
          <span class="form-status__hint">状态请在看板上拖拽流转</span>
        </template>
      </el-form-item>
      <el-form-item v-if="isEdit && form.status === 'CLOSED'" label="结束原因">
        <el-select v-model="form.close_reason" style="width: 100%">
          <el-option v-for="r in CLOSE_REASONS" :key="r.value" :label="r.label" :value="r.value" />
        </el-select>
        <span class="form-status__hint">选错了可以在这里改</span>
      </el-form-item>
      <el-form-item label="下次笔试/面试">
        <el-date-picker
          v-model="form.next_event_at"
          type="datetime"
          value-format="YYYY-MM-DD HH:mm:ss"
          placeholder="可不填"
        />
      </el-form-item>
      <el-form-item label="备注">
        <el-input v-model="form.remark" type="textarea" :rows="3" placeholder="面试进展、联系人等" />
      </el-form-item>
    </el-form>
    <template #footer>
      <div class="form-footer">
        <!-- 删除入口：仅编辑态（新增时无记录可删）。置于左侧与主操作分离，降低误点概率 -->
        <el-button v-if="isEdit" type="danger" plain @click="emitDelete">删除</el-button>
        <div class="form-footer__main">
          <el-button @click="close">取消</el-button>
          <el-button type="primary" :loading="saving" @click="submit">保存</el-button>
        </div>
      </div>
    </template>
  </el-dialog>
</template>

<style scoped>
/* 底部操作区：删除靠左与主操作分离——危险操作不该和「保存」挤在一起 */
.form-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.form-footer__main {
  display: flex;
  gap: 12px;
  margin-left: auto;
}
.form-status__dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
  margin-right: 6px;
}
.form-status__text {
  font-size: 13px;
  color: var(--c-text);
}
.form-status__hint {
  margin-left: 10px;
  font-size: 11.5px;
  color: var(--c-text-3);
}
.form-city {
  width: 100%;
}
</style>
