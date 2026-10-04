<script setup>
/**
 * 投喂弹窗（接口文档 §3.16 `POST /job-postings/ingest` → `POST /job-postings`）：
 * 录入原文（文本 / 链接二选一）→ AI 抽取预览（**不入库**）→ 确认入库。
 *
 * 失败分支：未配 AI → 10012（引导去 AI 配置页，原文保留可直接重试，**不降级为手动填表**）；
 * 抽取不可解析 / 链接被拒 / 登录墙 / 内网地址 → 70003（提示原因，可改原文重试）。
 * 确认入库成功后把原文按新岗位 id 暂存（供「分析匹配度」预填，见 utils/campusStash.js）。
 */
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { createJobPosting, ingestJobPosting } from '../../api/campus'
import { saveIngestText } from '../../utils/campusStash'
import { JOB_TYPE_META } from '../../constants/campus'

const props = defineProps({
  modelValue: { type: Boolean, default: false }
})
const emit = defineEmits(['update:modelValue', 'saved'])

const router = useRouter()

const TEXT_MAX = 20000
const URL_MAX = 500
const FIELD_LIMITS = { title: 200, company: 100, city: 50, edu_req: 50, major_req: 300, salary_text: 100 }

const mode = ref('text') // text | url
const text = ref('')
const url = ref('')
const parsing = ref(false)
const saving = ref(false)
const errorText = ref('')
const needAiConfig = ref(false)

const step = ref('input') // input | preview
const fields = ref(emptyFields())
const missing = ref([])
const fetchedFrom = ref('text')

function emptyFields() {
  return {
    title: '',
    company: '',
    city: '',
    edu_req: '',
    major_req: '',
    salary_text: '',
    job_type: '',
    deadline: null
  }
}

const canParse = computed(() => {
  if (mode.value === 'text') return text.value.trim().length > 0 && text.value.length <= TEXT_MAX
  const value = url.value.trim()
  return value.length > 0 && value.length <= URL_MAX && /^https?:\/\//i.test(value)
})

const canSave = computed(() => fields.value.title.trim() && fields.value.company.trim())

const missingSet = computed(() => new Set(missing.value))

// 每次打开重置到录入步（上次的预览 / 错误不带进来）
watch(
  () => props.modelValue,
  (visible) => {
    if (!visible) return
    step.value = 'input'
    errorText.value = ''
    needAiConfig.value = false
    parsing.value = false
    saving.value = false
  },
  { immediate: true }
)

function close() {
  emit('update:modelValue', false)
}

/** 原文：文本通道直接取输入；链接通道以抓取到的正文为准（预览阶段用不到，入库时回传用户输入）。 */
const rawExcerpt = computed(() => (mode.value === 'text' ? text.value.trim() : url.value.trim()))

async function onParse() {
  if (!canParse.value || parsing.value) return
  parsing.value = true
  errorText.value = ''
  needAiConfig.value = false
  try {
    const data = await ingestJobPosting(
      mode.value === 'text' ? { text: text.value.trim() } : { url: url.value.trim() }
    )
    fields.value = { ...emptyFields(), ...data.fields }
    missing.value = data.missing || []
    fetchedFrom.value = data.fetched_from || mode.value
    step.value = 'preview'
  } catch (e) {
    if (e?.code === 10012) {
      needAiConfig.value = true
      errorText.value = e.message || '未配置 AI 供应商'
    } else {
      errorText.value = e?.message || '解析失败，请检查原文后重试'
    }
  } finally {
    parsing.value = false
  }
}

async function onConfirm() {
  if (!canSave.value || saving.value) return
  saving.value = true
  try {
    const payload = {
      title: fields.value.title.trim(),
      company: fields.value.company.trim(),
      city: fields.value.city?.trim() || undefined,
      edu_req: fields.value.edu_req?.trim() || undefined,
      major_req: fields.value.major_req?.trim() || undefined,
      salary_text: fields.value.salary_text?.trim() || undefined,
      job_type: fields.value.job_type || undefined,
      deadline: fields.value.deadline || undefined,
      source_url: mode.value === 'url' ? url.value.trim() : undefined,
      raw_excerpt: rawExcerpt.value || undefined
    }
    const created = await createJobPosting(payload)
    saveIngestText(created.id, payload.raw_excerpt) // 「分析匹配度」预填用
    ElMessage.success('已入库')
    emit('saved')
    close()
  } catch (e) {
    ElMessage.error(e?.message || '入库失败')
  } finally {
    saving.value = false
  }
}

function goAiConfig() {
  close()
  router.push('/ai-config')
}
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    :title="step === 'input' ? '投喂一条招聘信息' : '确认岗位信息'"
    width="620px"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <!-- 第一步：录入原文 -->
    <div v-if="step === 'input'" class="ing">
      <div class="ing__tabs">
        <button
          type="button"
          class="ing__tab"
          :class="{ 'ing__tab--on': mode === 'text' }"
          @click="mode = 'text'"
        >
          粘贴文本
        </button>
        <button
          type="button"
          class="ing__tab"
          :class="{ 'ing__tab--on': mode === 'url' }"
          @click="mode = 'url'"
        >
          粘贴链接
        </button>
      </div>

      <template v-if="mode === 'text'">
        <el-input
          v-model="text"
          type="textarea"
          :rows="8"
          :maxlength="TEXT_MAX"
          show-word-limit
          placeholder="把招聘 JD / 宣讲会通知的原文粘进来，AI 会抽取岗位名称、公司、城市等信息"
        />
      </template>
      <template v-else>
        <el-input v-model="url" :maxlength="URL_MAX" placeholder="https://…（招聘信息链接）" clearable />
        <p class="ing__hint">
          链接会经合规抓取取正文（拒绝内网地址）；需要登录 / 被站点拒绝的页面会提示改为粘贴文本。
        </p>
      </template>

      <div v-if="errorText" class="ing__error">
        <span>{{ errorText }}</span>
        <el-button v-if="needAiConfig" size="small" type="primary" @click="goAiConfig">去 AI 配置</el-button>
      </div>
    </div>

    <!-- 第二步：抽取预览（不入库） -->
    <div v-else class="ing">
      <p class="ing__hint">
        以下是从{{ fetchedFrom === 'url' ? '链接正文' : '文本' }}中抽取的字段，确认无误后入库；标黄的字段没抽到，可手工补充。
      </p>
      <el-form label-width="76px" label-position="left" class="ing__form">
        <el-form-item :label="missingSet.has('title') ? '岗位名称*' : '岗位名称'">
          <el-input v-model="fields.title" :class="{ 'ing__miss': missingSet.has('title') }" :maxlength="FIELD_LIMITS.title" />
        </el-form-item>
        <el-form-item :label="missingSet.has('company') ? '公司*' : '公司'">
          <el-input v-model="fields.company" :class="{ 'ing__miss': missingSet.has('company') }" :maxlength="FIELD_LIMITS.company" />
        </el-form-item>
        <el-form-item label="城市" :class="{ 'ing__miss': missingSet.has('city') }">
          <el-input v-model="fields.city" :maxlength="FIELD_LIMITS.city" />
        </el-form-item>
        <el-form-item label="学历" :class="{ 'ing__miss': missingSet.has('edu_req') }">
          <el-input v-model="fields.edu_req" :maxlength="FIELD_LIMITS.edu_req" />
        </el-form-item>
        <el-form-item label="专业" :class="{ 'ing__miss': missingSet.has('major_req') }">
          <el-input v-model="fields.major_req" :maxlength="FIELD_LIMITS.major_req" />
        </el-form-item>
        <el-form-item label="薪资" :class="{ 'ing__miss': missingSet.has('salary_text') }">
          <el-input v-model="fields.salary_text" :maxlength="FIELD_LIMITS.salary_text" />
        </el-form-item>
        <el-form-item label="类型" :class="{ 'ing__miss': missingSet.has('job_type') }">
          <el-select v-model="fields.job_type" clearable placeholder="校招 / 实习 / 社招">
            <el-option v-for="(meta, value) in JOB_TYPE_META" :key="value" :label="meta.label" :value="value" />
          </el-select>
        </el-form-item>
        <el-form-item label="截止" :class="{ 'ing__miss': missingSet.has('deadline') }">
          <el-date-picker v-model="fields.deadline" type="date" value-format="YYYY-MM-DD" placeholder="投递截止日期" />
        </el-form-item>
      </el-form>
      <p class="ing__note">入库后归你的账号私有，其他账号看不到；自动抓取不存原文，投喂会留存原文供你日后校对。</p>
    </div>

    <template #footer>
      <el-button @click="close">取消</el-button>
      <template v-if="step === 'input'">
        <el-button type="primary" :loading="parsing" :disabled="!canParse" @click="onParse">解析预览</el-button>
      </template>
      <template v-else>
        <el-button @click="step = 'input'">上一步</el-button>
        <el-button type="primary" :loading="saving" :disabled="!canSave" @click="onConfirm">确认入库</el-button>
      </template>
    </template>
  </el-dialog>
</template>

<style scoped>
.ing__tabs {
  display: flex;
  gap: 4px;
  padding: 3px;
  margin-bottom: 12px;
  background: var(--c-bg);
  border-radius: var(--r-control);
  width: fit-content;
}
.ing__tab {
  padding: 6px 14px;
  font: inherit;
  font-size: var(--fs-sm);
  color: var(--c-text-2);
  background: transparent;
  border: 0;
  border-radius: var(--r-mark);
  cursor: pointer;
}
.ing__tab--on {
  color: var(--c-text);
  background: var(--c-card);
  font-weight: 600;
}
.ing__count {
  margin-top: 4px;
  text-align: right;
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}
.ing__hint {
  margin: 0 0 10px;
  font-size: var(--fs-sm);
  color: var(--c-text-3);
  line-height: 1.6;
}
.ing__error {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 10px;
  padding: 10px 12px;
  font-size: var(--fs-sm);
  color: var(--el-color-danger);
  background: var(--c-bg);
  border-radius: var(--r-control);
}
.ing__form :deep(.el-form-item) {
  margin-bottom: 10px;
}
.ing__miss :deep(.el-input__wrapper),
.ing__miss :deep(.el-select__wrapper) {
  box-shadow: 0 0 0 1px var(--el-color-warning) inset;
}
.ing__note {
  margin: 6px 0 0;
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}
</style>
