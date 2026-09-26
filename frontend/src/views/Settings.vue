<script setup>
/**
 * 系统设置（SRS §3.12 / 接口文档 §3.12）：账号级偏好 + 系统级抓取开关。
 * 保存方式：快照 diff + 统一「保存设置」按钮（接口为部分更新语义，只提交变更字段）。
 * 原设置页的 LLM 字段已全部迁至 AI 配置页（步骤 8 瘦身）。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { getSettingsApi, updateSettingsApi } from '../api/settings'
import { useAppStore } from '../stores/app'

// 音色列表：GET /tts/voices 属步骤 22（尚未实现），本步用 SRS §3.12 列举的三个音色过渡；
// 步骤 22 落地后改为从接口拉取并删除本常量
const TTS_VOICES = [
  { id: 'zh-CN-XiaoxiaoNeural', name: '晓晓' },
  { id: 'zh-CN-YunxiNeural', name: '云希' },
  { id: 'zh-CN-YunyangNeural', name: '云扬' }
]

// 参与 diff 的字段（asr_app_id / asr_api_key 不在其中：留空 = 不修改，不是"清空"）
const DIFF_KEYS = [
  'voice_enabled',
  'asr_provider',
  'tts_enabled',
  'tts_voice',
  'default_question_count',
  'crawl_enabled',
  'crawl_url'
]

const appStore = useAppStore()

const loading = ref(true)
const saving = ref(false)
const asrKeySet = ref(false)

const form = reactive({
  voice_enabled: false,
  asr_provider: 'funasr',
  asr_app_id: '',
  asr_api_key: '',
  tts_enabled: false,
  tts_voice: 'zh-CN-XiaoxiaoNeural',
  default_question_count: 8,
  crawl_enabled: false,
  crawl_url: ''
})

let snapshot = {} // 加载时的原始值，用于 diff

// 已存音色不在过渡列表中时补一项，避免回显被静默清空（同投递表单城市字段的兜底思路）
const voiceOptions = computed(() => {
  const options = TTS_VOICES.map((v) => ({ value: v.id, label: `${v.name}（${v.id}）` }))
  if (form.tts_voice && !options.some((o) => o.value === form.tts_voice)) {
    options.unshift({ value: form.tts_voice, label: `${form.tts_voice}（当前已存）` })
  }
  return options
})

function applySettings(data) {
  Object.assign(form, {
    voice_enabled: !!data.voice_enabled,
    asr_provider: data.asr_provider || 'funasr',
    asr_app_id: '',
    asr_api_key: '',
    tts_enabled: !!data.tts_enabled,
    tts_voice: data.tts_voice || 'zh-CN-XiaoxiaoNeural',
    default_question_count: data.default_question_count ?? 8,
    crawl_enabled: !!data.crawl_enabled,
    crawl_url: data.crawl_url || ''
  })
  asrKeySet.value = !!data.asr_key_set
  snapshot = Object.fromEntries(DIFF_KEYS.map((k) => [k, form[k]]))
  appStore.setSettings(data) // 供后续步骤（13 陪练题量、22 语音开关）取用
}

async function load() {
  loading.value = true
  try {
    applySettings(await getSettingsApi())
  } finally {
    loading.value = false
  }
}

async function save() {
  const payload = {}
  for (const key of DIFF_KEYS) {
    // 布尔严格传布尔：接口对非布尔值一律 10001，不做隐式转换
    if (form[key] !== snapshot[key]) payload[key] = form[key]
  }
  if (form.asr_app_id) payload.asr_app_id = form.asr_app_id // 留空 = 不修改
  if (form.asr_api_key) payload.asr_api_key = form.asr_api_key

  if (!Object.keys(payload).length) {
    ElMessage.info('没有需要保存的变更')
    return
  }
  saving.value = true
  try {
    applySettings(await updateSettingsApi(payload))
    ElMessage.success('设置已保存')
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <div v-loading="loading" class="settings">
    <el-card shadow="never" class="settings__card">
      <h3 class="settings__title">语音交互</h3>
      <el-form label-width="120px">
        <el-form-item label="语音作答">
          <el-switch v-model="form.voice_enabled" />
          <span class="settings__hint">模拟面试与练习模式的语音输入总开关</span>
        </el-form-item>
        <el-form-item label="ASR 供应商">
          <el-radio-group v-model="form.asr_provider">
            <el-radio value="funasr">本地模型（FunASR）</el-radio>
            <el-radio value="xunfei">云端（讯飞）</el-radio>
          </el-radio-group>
        </el-form-item>
        <template v-if="form.asr_provider === 'xunfei'">
          <el-form-item label="讯飞 AppID">
            <el-input v-model="form.asr_app_id" placeholder="留空则不修改" />
          </el-form-item>
          <el-form-item label="讯飞 API Key">
            <el-input
              v-model="form.asr_api_key"
              type="password"
              show-password
              :placeholder="asrKeySet ? '已配置，留空则不修改' : '粘贴 API Key'"
            />
          </el-form-item>
        </template>
        <el-form-item label="AI 回复朗读">
          <el-switch v-model="form.tts_enabled" />
        </el-form-item>
        <el-form-item label="播报音色">
          <el-select
            v-model="form.tts_voice"
            :disabled="!form.tts_enabled"
            style="width: 280px"
          >
            <el-option v-for="o in voiceOptions" :key="o.value" :value="o.value" :label="o.label" />
          </el-select>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card shadow="never" class="settings__card">
      <h3 class="settings__title">模拟面试</h3>
      <el-form label-width="120px">
        <el-form-item label="默认题量">
          <el-input-number v-model="form.default_question_count" :min="1" :max="50" />
          <span class="settings__hint">新建面试会话时的默认题目数量（1~50）</span>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card shadow="never" class="settings__card">
      <h3 class="settings__title">就业网抓取</h3>
      <p class="settings__note">以下为系统级配置：任一账号修改后对全部账号生效。</p>
      <el-form label-width="120px">
        <el-form-item label="每日抓取">
          <el-switch v-model="form.crawl_enabled" />
        </el-form-item>
        <el-form-item label="目标地址">
          <el-input
            v-model="form.crawl_url"
            :disabled="!form.crawl_enabled"
            placeholder="留空则使用默认就业网地址"
          />
        </el-form-item>
      </el-form>
    </el-card>

    <div class="settings__footer">
      <el-button type="primary" :loading="saving" @click="save">保存设置</el-button>
    </div>
  </div>
</template>

<style scoped>
.settings__card {
  border-radius: var(--r-card);
  margin-bottom: var(--card-gap);
}
.settings__title {
  font-size: 13px;
  font-weight: 700;
  color: var(--c-text);
  margin: 0 0 14px;
}
.settings__hint {
  font-size: 12px;
  color: var(--c-text-2);
  margin-left: 10px;
}
.settings__note {
  font-size: 12px;
  color: var(--c-text-2);
  margin: 0 0 12px;
}
.settings__footer {
  display: flex;
  justify-content: flex-end;
  padding: 4px 0 8px;
}
</style>
