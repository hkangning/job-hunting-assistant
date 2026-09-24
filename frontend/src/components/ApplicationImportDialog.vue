<script setup>
// 投递批量导入（FR-003 方式三）：模板下载 → 选择文件 → 导入 → 错误行展示
// 错误码：20001 文件级（格式/体积/空文件/编码）、20002 全行非法（HTTP 400，携带行级清单）
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { UploadFilled } from '@element-plus/icons-vue'
import { downloadTemplate, importApplications } from '../api/applications'

defineProps({
  modelValue: { type: Boolean, default: false }
})
const emit = defineEmits(['update:modelValue', 'imported'])

const fileList = ref([])
const selectedFile = ref(null)
const importing = ref(false)
const downloading = ref(false)
const result = ref(null) // { success_count, errors: [{row, reason}] }
const failure = ref('') // 文件级失败的提示文案（20001）

function close() {
  emit('update:modelValue', false)
}

function reset() {
  fileList.value = []
  selectedFile.value = null
  result.value = null
  failure.value = ''
}

/** 前端预校验：与后端限制一致（.xlsx/.csv、≤2MB、非空） */
function validateFile(file) {
  const name = (file.name || '').toLowerCase()
  if (!name.endsWith('.xlsx') && !name.endsWith('.csv')) return '仅支持 .xlsx 或 .csv 文件'
  if (file.size > 2 * 1024 * 1024) return '文件大小超过 2MB'
  if (file.size === 0) return '文件内容为空'
  return ''
}

function onChange(file, files) {
  result.value = null
  failure.value = ''
  const reason = validateFile(file.raw || file)
  if (reason) {
    failure.value = reason
    fileList.value = []
    selectedFile.value = null
    return
  }
  fileList.value = files.slice(-1) // limit=1：只留最后一次选择
  selectedFile.value = file.raw
}

function onRemove() {
  selectedFile.value = null
  fileList.value = []
}

async function downloadTpl() {
  downloading.value = true
  try {
    const blob = await downloadTemplate()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'application_import_template.xlsx'
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
  } finally {
    downloading.value = false
  }
}

async function submit() {
  if (!selectedFile.value) {
    ElMessage.warning('请先选择文件')
    return
  }
  importing.value = true
  failure.value = ''
  try {
    result.value = await importApplications(selectedFile.value)
    if (result.value.success_count > 0) {
      ElMessage.success(`成功导入 ${result.value.success_count} 条`)
      emit('imported')
    }
  } catch (err) {
    // 20002：全行非法，错误明细在 err.data.errors（依赖 request.js 的 data 透传）
    failure.value = err.message || '导入失败'
    if (err.code === 20002 && err.data) result.value = err.data
    else if (err.code === 20001) result.value = null
  } finally {
    importing.value = false
  }
}
</script>

<template>
  <el-dialog :model-value="modelValue" title="批量导入投递" width="620px" @update:model-value="close" @closed="reset">
    <div class="import">
      <div class="import__step">
        <span class="import__step-no">1</span>
        <span class="import__step-text">下载模板，按表头填写</span>
        <el-button size="small" :loading="downloading" @click="downloadTpl">下载模板</el-button>
      </div>
      <div class="import__head">
        表头：company, position, city, applied_at, channel, status, remark（status 取值 APPLIED / WRITTEN /
        INTERVIEW / OFFER / CLOSED）
      </div>

      <div class="import__step">
        <span class="import__step-no">2</span>
        <span class="import__step-text">选择文件（.xlsx / .csv，≤2MB）</span>
      </div>
      <el-upload
        drag
        :auto-upload="false"
        :limit="1"
        accept=".xlsx,.csv"
        :file-list="fileList"
        :on-change="onChange"
        :on-remove="onRemove"
      >
        <el-icon class="import__upload-icon"><UploadFilled /></el-icon>
        <div class="import__upload-text">将文件拖到此处，或点击选择</div>
      </el-upload>

      <el-alert v-if="failure" :title="failure" type="error" :closable="false" show-icon class="import__alert" />

      <div v-if="result" class="import__result">
        <div class="import__summary">成功导入 <b>{{ result.success_count }}</b> 条</div>
        <el-table v-if="result.errors && result.errors.length" :data="result.errors" size="small" border>
          <el-table-column prop="row" label="行号" width="90" />
          <el-table-column prop="reason" label="错误原因" />
        </el-table>
        <div v-else class="import__ok">没有错误行</div>
      </div>
    </div>

    <template #footer>
      <el-button @click="close">关闭</el-button>
      <el-button type="primary" :loading="importing" :disabled="!selectedFile" @click="submit">开始导入</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.import__step {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}
.import__step-no {
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: var(--el-color-primary-light-9);
  color: var(--brand);
  font-size: 11.5px;
  font-weight: 700;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: none;
}
.import__step-text {
  font-size: 13px;
  color: var(--c-text);
}
.import__step .el-button {
  margin-left: auto;
}
.import__head {
  margin: 0 0 14px 26px;
  font-size: 11.5px;
  color: var(--c-text-3);
  line-height: 1.6;
}
.import__upload-icon {
  font-size: 34px;
  color: var(--c-text-3);
}
.import__upload-text {
  font-size: 12px;
  color: var(--c-text-2);
}
.import__alert {
  margin-top: 12px;
}
.import__result {
  margin-top: 14px;
}
.import__summary {
  font-size: 13px;
  color: var(--c-text);
  margin-bottom: 8px;
}
.import__summary b {
  color: var(--m-practice);
}
.import__ok {
  font-size: 12px;
  color: var(--c-text-3);
}
</style>
