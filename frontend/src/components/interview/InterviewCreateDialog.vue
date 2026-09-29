<script setup>
/**
 * 发起面试（接口文档 v1.31 §3.7 `POST /interview-sessions`）。
 *
 * 两条路径二选一：选一条投递记录（公司/岗位由后端带入）或手填；
 * 方向不硬编码 19 项——取自 `GET /practice/meta` 的「栈 → 领域」，最前放「通用」（待改问题 #33）。
 */
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { listApplications } from '../../api/applications'
import { createInterviewSession } from '../../api/interview'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  /** `GET /practice/meta` 的结果，由页面加载后传入（页面也要用它的方向中文名）。 */
  meta: { type: Object, default: null }
})
const emit = defineEmits(['update:modelValue', 'created'])

const formRef = ref(null)
const submitting = ref(false)
const form = reactive({
  applicationId: null,
  company: '',
  position: '',
  direction: 'GENERAL',
  questionCount: 8
})

const rules = {
  company: [
    {
      validator: (_, value, callback) =>
        form.applicationId || value?.trim() ? callback() : callback(new Error('请填公司')),
      trigger: 'blur'
    }
  ],
  position: [
    {
      validator: (_, value, callback) =>
        form.applicationId || value?.trim() ? callback() : callback(new Error('请填岗位')),
      trigger: 'blur'
    }
  ]
}

// ---------- 投递下拉（远程搜索，默认最近 50 条） ----------

const applications = ref([])
const searching = ref(false)
let searchTimer = null

function searchApplications(keyword = '') {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(async () => {
    searching.value = true
    try {
      const data = await listApplications({ company: keyword || undefined, page: 1, page_size: 50 })
      applications.value = data.items || []
    } catch {
      applications.value = [] // 拉不到就空列表——不阻塞手填路径
    } finally {
      searching.value = false
    }
  }, 300)
}

function onPickApplication(id) {
  const app = applications.value.find((item) => item.id === id)
  if (app) {
    form.company = app.company
    form.position = app.position
  }
}

// ---------- 方向（meta 分组 + 通用置顶） ----------

const directionGroups = computed(() => [
  { label: '通用', options: [{ value: 'GENERAL', label: '不限方向' }] },
  ...(props.meta?.stacks || []).map((stack) => ({
    label: stack.label,
    options: (stack.domains || []).map((d) => ({ value: d.value, label: d.label }))
  }))
])

// ---------- 开合与提交 ----------

watch(
  () => props.modelValue,
  (open) => {
    if (!open) return
    Object.assign(form, {
      applicationId: null,
      company: '',
      position: '',
      direction: 'GENERAL',
      questionCount: 8
    })
    formRef.value?.clearValidate()
    searchApplications('')
  }
)

function close() {
  emit('update:modelValue', false)
}

async function submit() {
  if (!formRef.value) return
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return

  submitting.value = true
  try {
    // 选了投递：公司/岗位由后端带入，不重复传（契约：未传 application_id 时两者才必填）
    const payload = form.applicationId
      ? { application_id: form.applicationId }
      : { company: form.company.trim(), position: form.position.trim() }
    payload.direction = form.direction
    payload.question_count = form.questionCount

    const session = await createInterviewSession(payload)
    ElMessage.success('面试已创建')
    emit('created', session)
    close()
  } catch (error) {
    ElMessage.error(error?.message || '创建失败，请稍后重试')
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    title="发起模拟面试"
    width="560px"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <el-form ref="formRef" :model="form" :rules="rules" label-width="88px">
      <el-form-item label="关联投递">
        <el-select
          v-model="form.applicationId"
          filterable
          remote
          clearable
          :remote-method="searchApplications"
          :loading="searching"
          placeholder="选择一条投递记录（可留空手动填写）"
          style="width: 100%"
          @change="onPickApplication"
        >
          <el-option
            v-for="app in applications"
            :key="app.id"
            :label="`${app.company} · ${app.position}`"
            :value="app.id"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="公司" prop="company">
        <el-input v-model="form.company" :disabled="!!form.applicationId" placeholder="公司名称" />
      </el-form-item>
      <el-form-item label="岗位" prop="position">
        <el-input v-model="form.position" :disabled="!!form.applicationId" placeholder="岗位名称" />
      </el-form-item>
      <el-form-item label="面试方向">
        <el-select v-model="form.direction" style="width: 100%">
          <el-option-group v-for="group in directionGroups" :key="group.label" :label="group.label">
            <el-option
              v-for="opt in group.options"
              :key="opt.value"
              :label="opt.label"
              :value="opt.value"
            />
          </el-option-group>
        </el-select>
      </el-form-item>
      <el-form-item label="题量">
        <el-input-number v-model="form.questionCount" :min="3" :max="15" />
        <span class="create__hint">3~15 题，默认 8 题</span>
      </el-form-item>
    </el-form>

    <template #footer>
      <el-button :disabled="submitting" @click="close">取消</el-button>
      <el-button type="primary" :loading="submitting" @click="submit">开始面试</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.create__hint {
  margin-left: 10px;
  font-size: 12px;
  color: var(--c-text-3);
}
</style>
