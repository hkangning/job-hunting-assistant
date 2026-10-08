<script setup>
/**
 * 添加错题（知识点形态）。
 *
 * 页面上只做这一种形态：题库题形态（`{question_id}`）需要「挑题」能力，而题库只有随机抽题接口，
 * 挑不了——它的入口留给其他场景（面试点评 / 练习模式点评里自动建题再入本）。
 */
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { addWrongQuestion } from '../../api/wrongQuestions'
import { directionOptions } from '../../utils/practiceMeta'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  meta: { type: Object, default: null }
})
const emit = defineEmits(['update:modelValue', 'added'])

const formRef = ref(null)
const submitting = ref(false)
const form = reactive({ content: '', answer: '', direction: '', source_type: 'INTERVIEW' })

const rules = {
  content: [{ required: true, message: '请填题干', trigger: 'blur' }],
  answer: [{ required: true, message: '请填标准答案', trigger: 'blur' }],
  direction: [{ required: true, message: '请选领域', trigger: 'change' }]
}

/** 领域选项：与错题本筛选共用一份（`practiceMeta.js`），来自 `GET /practice/meta`。 */
const domainOptions = computed(() => directionOptions(props.meta))

/** 每次打开重置表单，避免上次的残留。 */
watch(
  () => props.modelValue,
  (open) => {
    if (!open) return
    Object.assign(form, { content: '', answer: '', direction: '', source_type: 'INTERVIEW' })
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

  submitting.value = true
  try {
    await addWrongQuestion({ ...form })
    ElMessage.success('已加入错题本')
    emit('added')
    close()
  } catch {
    // 409 + 10003（题干撞车）等失败留在对话框里改；提示由拦截器弹出，不重复弹（步骤 27）
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    title="添加知识点到错题本"
    width="560px"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <el-form ref="formRef" :model="form" :rules="rules" label-width="88px">
      <el-form-item label="题干" prop="content">
        <el-input
          v-model="form.content"
          type="textarea"
          :rows="3"
          maxlength="2000"
          show-word-limit
          placeholder="要记的知识点问题"
        />
      </el-form-item>
      <el-form-item label="标准答案" prop="answer">
        <el-input
          v-model="form.answer"
          type="textarea"
          :rows="3"
          maxlength="5000"
          show-word-limit
          placeholder="参考答案——复习判定的依据"
        />
      </el-form-item>
      <el-form-item label="领域" prop="direction">
        <el-select v-model="form.direction" placeholder="选择知识领域" style="width: 100%">
          <el-option
            v-for="opt in domainOptions"
            :key="opt.value"
            :label="opt.label"
            :value="opt.value"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="来源" prop="source_type">
        <el-radio-group v-model="form.source_type">
          <el-radio value="INTERVIEW">面试遇到</el-radio>
          <el-radio value="DRILL">练习模式</el-radio>
        </el-radio-group>
      </el-form-item>
    </el-form>

    <template #footer>
      <el-button :disabled="submitting" @click="close">取消</el-button>
      <el-button type="primary" :loading="submitting" @click="submit">加入错题本</el-button>
    </template>
  </el-dialog>
</template>
