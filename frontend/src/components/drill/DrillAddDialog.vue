<script setup>
/**
 * 新建练习题（FR-020 / 接口文档 §3.15）。
 *
 * 两种建题形态：
 * - **手动写题**（`source=CUSTOM`）：标题 + 题面；
 * - **从既有数据导入**（`WRONG` 错题本 / `EXPERIENCE` 面经条目 / `JD` 投递记录）：先选来源条目，
 *   **只记来源不复制内容**——`ref_id` 记来源实体 id，题面以本次写入的 `question` 为准
 *   （标题回填来源条目标题，可改）。
 *
 * `RESUME`（画像经历）/ `INTRO` 暂不提供：`ref_id` 语义文档未定义（画像经历存在
 * `user_profile.experiences` JSON 数组里、条目没有独立 id），登记为待后端确认项，不在此造契约。
 */
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { createDrill } from '../../api/drill'
import { listWrongQuestions } from '../../api/wrongQuestions'
import { listExperiences } from '../../api/experiences'
import { listApplications } from '../../api/applications'

const props = defineProps({
  modelValue: { type: Boolean, default: false }
})
const emit = defineEmits(['update:modelValue', 'created'])

/** 来源选项：手动 + 三个可导入来源（顺序按使用频次）。 */
const SOURCES = [
  { value: 'CUSTOM', label: '手动写题', hint: '自己拟题面，例如「自我介绍」' },
  { value: 'WRONG', label: '从错题本导入', hint: '把一道错题变成练习题' },
  { value: 'EXPERIENCE', label: '从面经导入', hint: '把面经里的题目拿过来练' },
  { value: 'JD', label: '从投递记录导入', hint: '按目标岗位的 JD 练讲解' }
]

const formRef = ref(null)
const submitting = ref(false)
const loadingSource = ref(false)
const candidates = ref([])
const form = reactive({ source: 'CUSTOM', title: '', question: '', refId: null })

const rules = {
  title: [
    { required: true, message: '请填题目标题', trigger: 'blur' },
    { max: 50, message: '标题不超过 50 字', trigger: 'blur' }
  ]
}

const isImport = computed(() => form.source !== 'CUSTOM')
const currentSource = computed(() => SOURCES.find((s) => s.value === form.source))

/** 来源条目在列表里的显示文案（三类实体的字段名各不相同）。 */
function candidateLabel(item) {
  if (form.source === 'WRONG') return item.content || `错题 #${item.id}`
  if (form.source === 'JD') return [item.company, item.position].filter(Boolean).join(' · ') || `投递 #${item.id}`
  return item.title || `面经条目 #${item.id}`
}

/** 拉候选来源条目：三个来源各走自己的列表接口（只取前 50 条，够挑题用）。 */
async function loadCandidates() {
  if (!isImport.value) return
  loadingSource.value = true
  candidates.value = []
  try {
    const params = { page: 1, page_size: 50 }
    const data =
      form.source === 'WRONG'
        ? await listWrongQuestions(params)
        : form.source === 'EXPERIENCE'
          ? await listExperiences(params)
          : await listApplications(params)
    candidates.value = data?.items || []
  } catch {
    // 拦截器已提示失败原因，不重复弹（步骤 27：双提示消除）
  } finally {
    loadingSource.value = false
  }
}

/** 选中来源条目：标题回填（可改），题面留空由 AI 按标题 + 来源生成。 */
function onPickCandidate(id) {
  const item = candidates.value.find((c) => c.id === id)
  if (!item) return
  form.refId = item.id
  form.title = candidateLabel(item).slice(0, 50)
}

/** 切换来源：清掉上一次的来源残留（含已选项）。 */
function onSourceChange() {
  form.refId = null
  form.question = ''
  candidates.value = []
  formRef.value?.clearValidate()
  loadCandidates()
}

watch(
  () => props.modelValue,
  (open) => {
    if (!open) return
    Object.assign(form, { source: 'CUSTOM', title: '', question: '', refId: null })
    candidates.value = []
    formRef.value?.clearValidate()
  }
)

function close() {
  emit('update:modelValue', false)
}

async function submit() {
  if (!formRef.value) return
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return
  if (isImport.value && form.refId == null) {
    ElMessage.warning('请先选择来源条目')
    return
  }

  submitting.value = true
  try {
    const payload = { title: form.title.trim(), source: form.source }
    if (form.question.trim()) payload.question = form.question.trim()
    if (isImport.value) payload.ref_id = form.refId
    const topic = await createDrill(payload)
    ElMessage.success('题目已创建')
    emit('created', topic)
    close()
  } catch {
    // 失败不关窗（用户可改后重试）；提示由拦截器弹出，不重复弹（步骤 27：双提示消除）
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    title="新建练习题"
    width="560px"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <el-form ref="formRef" :model="form" :rules="rules" label-width="88px">
      <el-form-item label="题目来源">
        <el-radio-group v-model="form.source" @change="onSourceChange">
          <el-radio v-for="s in SOURCES" :key="s.value" :value="s.value">{{ s.label }}</el-radio>
        </el-radio-group>
        <p class="add__hint">{{ currentSource?.hint }}</p>
      </el-form-item>

      <el-form-item v-if="isImport" label="来源条目" required>
        <el-select
          v-model="form.refId"
          v-loading="loadingSource"
          placeholder="选择要练的那一条"
          style="width: 100%"
          @change="onPickCandidate"
        >
          <el-option
            v-for="item in candidates"
            :key="item.id"
            :label="candidateLabel(item)"
            :value="item.id"
          />
        </el-select>
        <p v-if="!loadingSource && !candidates.length" class="add__hint">
          暂无可导入的来源条目——先去对应模块里积累一条，或改用手动写题。
        </p>
      </el-form-item>

      <el-form-item label="标题" prop="title">
        <el-input v-model="form.title" maxlength="50" show-word-limit placeholder="例如：自我介绍" />
      </el-form-item>

      <el-form-item label="题面">
        <el-input
          v-model="form.question"
          type="textarea"
          :rows="4"
          maxlength="2000"
          show-word-limit
          :placeholder="
            isImport
              ? '留空则由 AI 按标题 + 来源生成题面'
              : '完整题目，例如：请用一分钟做个自我介绍'
          "
        />
      </el-form-item>
    </el-form>

    <template #footer>
      <el-button :disabled="submitting" @click="close">取消</el-button>
      <el-button type="primary" :loading="submitting" @click="submit">创建题目</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.add__hint {
  margin: 4px 0 0;
  font-size: var(--fs-xs);
  color: var(--c-text-3);
  line-height: 1.6;
}
</style>
