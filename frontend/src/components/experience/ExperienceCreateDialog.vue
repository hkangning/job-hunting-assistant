<script setup>
/**
 * 新增面经（接口文档 v1.33 §3.10 `POST /experiences`）。
 *
 * 契约口径：保存与提取分离——「保存并提取」先存原文、跳详情页由那里自动跑提取；
 * 「仅保存原文」只存档（提取消耗 AI 调用，格式太乱的原文可能只想留底）。
 */
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { createExperience } from '../../api/experiences'
import { textLength } from '../../utils/text'

const props = defineProps({
  modelValue: { type: Boolean, default: false }
})
const emit = defineEmits(['update:modelValue', 'created'])

const MAX_LEN = 10000

const formRef = ref(null)
const submitting = ref(false)
const form = reactive({ company: '', position: '', source: '', originalText: '' })

const count = computed(() => textLength(form.originalText))
const overLimit = computed(() => count.value > MAX_LEN)

const rules = {
  originalText: [
    {
      validator: (_, value, callback) => {
        if (!value?.trim()) return callback(new Error('请粘贴面经原文'))
        if (textLength(value) > MAX_LEN)
          return callback(new Error(`原文超出 ${MAX_LEN} 字上限（当前 ${textLength(value)} 字）`))
        callback()
      },
      trigger: 'blur'
    }
  ]
}

watch(
  () => props.modelValue,
  (open) => {
    if (!open) return
    Object.assign(form, { company: '', position: '', source: '', originalText: '' })
    formRef.value?.clearValidate()
  }
)

function close() {
  emit('update:modelValue', false)
}

/** `withExtract`：true = 保存并提取（跳详情页自动跑）；false = 仅保存原文。 */
async function submit(withExtract) {
  if (!formRef.value) return
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return

  submitting.value = true
  try {
    const payload = { original_text: form.originalText }
    if (form.company.trim()) payload.company = form.company.trim()
    if (form.position.trim()) payload.position = form.position.trim()
    if (form.source.trim()) payload.source = form.source.trim()

    const experience = await createExperience(payload)
    emit('created', { experience, withExtract })
    close()
  } catch (error) {
    ElMessage.error(error?.message || '保存失败，请稍后重试')
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    title="粘贴面经"
    width="620px"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <el-form ref="formRef" :model="form" :rules="rules" label-width="72px">
      <el-form-item label="原文" prop="originalText">
        <div class="create__text">
          <el-input
            v-model="form.originalText"
            type="textarea"
            :rows="10"
            placeholder="把面经原文整段粘进来，AI 会自动拆成「问题 + 答案要点」条目"
          />
          <div class="create__count" :class="{ 'create__count--over': overLimit }">
            {{ count }} / {{ MAX_LEN }}
          </div>
        </div>
      </el-form-item>
      <el-form-item label="公司">
        <el-input v-model="form.company" maxlength="100" placeholder="选填，如：南京浩鲸" />
      </el-form-item>
      <el-form-item label="岗位">
        <el-input v-model="form.position" maxlength="100" placeholder="选填，如：Java 开发" />
      </el-form-item>
      <el-form-item label="来源">
        <el-input v-model="form.source" maxlength="100" placeholder="选填，如：牛客 / 公众号 / 同学分享" />
      </el-form-item>
    </el-form>

    <template #footer>
      <el-button :disabled="submitting" @click="close">取消</el-button>
      <el-button :disabled="submitting || overLimit" @click="submit(false)">仅保存原文</el-button>
      <el-button type="primary" :loading="submitting" :disabled="overLimit" @click="submit(true)">
        保存并提取
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.create__text {
  width: 100%;
}
.create__count {
  margin-top: 4px;
  text-align: right;
  font-size: var(--fs-xs);
  color: var(--c-text-3);
  font-variant-numeric: tabular-nums;
}
.create__count--over {
  color: var(--el-color-danger);
  font-weight: 600;
}
</style>
