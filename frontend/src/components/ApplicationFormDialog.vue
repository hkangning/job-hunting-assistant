<script setup>
// 投递新增/编辑表单（FR-002）。编辑时状态只读：接口文档 §3.3 明确 PUT 不改 status
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { createApplication, getApplication, updateApplication } from '../api/applications'
import { APPLICATION_STATUSES, STATUS_COLORS, STATUS_LABELS } from '../constants/application'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  applicationId: { type: Number, default: null }
})
const emit = defineEmits(['update:modelValue', 'saved'])

const formRef = ref(null)
const saving = ref(false)
const loading = ref(false)
const isEdit = computed(() => props.applicationId != null)

const form = reactive({
  company: '',
  position: '',
  city: '',
  expected_salary: '',
  applied_at: '',
  channel: '',
  status: 'APPLIED',
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
    next_event_at: null,
    remark: ''
  })
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
      next_event_at: detail.next_event_at,
      remark: detail.remark || ''
    })
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
    <el-form ref="formRef" v-loading="loading" :model="form" :rules="rules" label-width="100px">
      <el-form-item label="公司名称" prop="company">
        <el-input v-model="form.company" maxlength="100" placeholder="如：浩鲸科技" />
      </el-form-item>
      <el-form-item label="岗位名称" prop="position">
        <el-input v-model="form.position" maxlength="100" placeholder="如：Java 开发" />
      </el-form-item>
      <el-form-item label="工作城市" prop="city">
        <el-input v-model="form.city" maxlength="50" placeholder="如：南京" />
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
      <el-button @click="close">取消</el-button>
      <el-button type="primary" :loading="saving" @click="submit">保存</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
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
</style>
