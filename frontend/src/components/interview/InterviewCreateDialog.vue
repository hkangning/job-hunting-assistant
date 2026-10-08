<script setup>
/**
 * 发起面试（接口文档 v1.33 §3.7 `POST /interview-sessions`）。
 *
 * 两条路径二选一：选一条投递记录（公司/岗位由后端带入）或手填；
 * 方向不硬编码 19 项——取自 `GET /practice/meta` 的「栈 → 领域」，最前放「通用」（待改问题 #33）。
 */
import { computed, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { listApplications } from '../../api/applications'
import { createInterviewSession } from '../../api/interview'
import { getProfileApi } from '../../api/profile'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  /** `GET /practice/meta` 的结果，由页面加载后传入（页面也要用它的方向中文名）。 */
  meta: { type: Object, default: null }
})
const emit = defineEmits(['update:modelValue', 'created'])

const router = useRouter()

const formRef = ref(null)
const submitting = ref(false)
/** 画像是否填写了经历条目——决定面试是否会出现「项目深挖」环节（后端按经历分配项目题）。 */
const hasResume = ref(false)
const form = reactive({
  applicationId: null,
  company: '',
  position: '',
  direction: 'GENERAL',
  questionCount: 8,
  intensity: 'MEDIUM'
})

/** 三档差异说明（接口文档 v1.36 §3.7 的强度表）；强度随会话固定，中途不可改。 */
const INTENSITY_OPTIONS = [
  { value: 'LARGE', label: '大厂', desc: '偏原理与系统设计，追问更深、评分更严' },
  { value: 'MEDIUM', label: '中厂', desc: '兼顾原理与工程实操（默认）' },
  { value: 'SMALL', label: '小厂', desc: '偏基础与实用，追问浅、评分宽' }
]

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
      questionCount: 8,
      intensity: 'MEDIUM'
    })
    formRef.value?.clearValidate()
    searchApplications('')
    getProfileApi()
      .then((data) => (hasResume.value = Array.isArray(data?.experiences) && data.experiences.length > 0))
      .catch(() => (hasResume.value = false)) // 拉不到按"无经历"提示，不阻塞发起
  }
)

function close() {
  emit('update:modelValue', false)
}

/** 「去个人中心」：关掉弹窗再跳（避免弹窗残留在新页面上层）。 */
function openProfile() {
  close()
  router.push('/profile')
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
    payload.intensity = form.intensity

    const session = await createInterviewSession(payload)
    ElMessage.success('面试已创建')
    emit('created', session)
    close()
  } catch {
    // 拦截器已提示失败原因，不重复弹（步骤 27：双提示消除）
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
      <el-form-item label="面试强度">
        <el-radio-group v-model="form.intensity" class="create__intensity">
          <el-radio
            v-for="opt in INTENSITY_OPTIONS"
            :key="opt.value"
            :value="opt.value"
            class="create__intensity-item"
          >
            <span class="create__intensity-name">{{ opt.label }}</span>
            <span class="create__intensity-desc">{{ opt.desc }}</span>
          </el-radio>
        </el-radio-group>
      </el-form-item>
    </el-form>

    <!-- 面试流程说明：让「完整流程」在发起前就可知可预期 -->
    <div class="create__flow">
      <div class="create__flow-steps">
        <span class="create__flow-step">自我介绍</span>
        <span class="create__flow-arrow">→</span>
        <span class="create__flow-step">技术问答</span>
        <template v-if="hasResume">
          <span class="create__flow-arrow">→</span>
          <span class="create__flow-step">项目深挖</span>
        </template>
        <span class="create__flow-arrow">→</span>
        <span class="create__flow-step">总结报告</span>
      </div>
      <p v-if="!hasResume" class="create__flow-hint">
        完善经历后可得「项目深挖」环节——去
        <a href="#" @click.prevent="openProfile">个人中心</a>上传简历或添加经历
      </p>
      <p v-else class="create__flow-hint">「项目深挖」将依据你画像中的经历出题</p>
    </div>

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
/* 强度三档：竖排单选，每档带一句差异说明 */
.create__intensity {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
}
.create__intensity-item {
  height: auto;
  margin-right: 0;
  padding: 4px 0;
}
.create__intensity-name {
  margin-right: 8px;
  font-weight: 600;
}
.create__intensity-desc {
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}
.create__flow {
  padding: 10px 14px;
  background: var(--c-bg);
  border-radius: var(--r-control);
}
.create__flow-steps {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: var(--fs-sm);
  color: var(--c-text);
}
.create__flow-step {
  padding: 1px 8px;
  background: var(--c-card);
  border: 1px solid var(--c-border);
  border-radius: var(--r-mark);
}
.create__flow-arrow {
  color: var(--c-text-3);
}
.create__flow-hint {
  margin: 8px 0 0;
  font-size: var(--fs-xs);
  color: var(--c-text-2);
}
.create__flow-hint a {
  color: var(--brand);
  text-decoration: none;
}
</style>
