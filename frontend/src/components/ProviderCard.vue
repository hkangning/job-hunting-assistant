<script setup>
/**
 * 单个 AI 供应商卡片（SRS §3.15 / 接口文档 §3.3）。
 * 折叠态：名称 + 状态标签 + 当前模型；展开态：Key / 高级设置 / 模型 / 操作。
 * 只读探测（模型列表、连通性测试）由本组件自理、结果就地展示；
 * 写操作（保存 / 激活 / 删除）完成后 emit('changed')，由页面整体重拉 providers——
 * is_active 是互斥关系，局部更新会在切换后留下两个「当前使用中」。
 */
import { computed, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  activateProviderApi,
  deleteProviderApi,
  listModelsApi,
  saveProviderApi,
  testProviderApi
} from '../api/llmProviders'

// 后端注册表中唯一 needs_key=False 的供应商；接口 DTO 未暴露该字段，故按标识约定判断
// （已记入问题记录：若将来新增免 Key 供应商，此处会漏判）
const KEYLESS_PROVIDERS = ['ollama']

const props = defineProps({ item: { type: Object, required: true } })
const emit = defineEmits(['changed'])

const needsKey = computed(() => !KEYLESS_PROVIDERS.includes(props.item.provider))

const expanded = ref(false)
const showAdvanced = ref(false) // 高级设置（base_url）
const saving = ref(false)
const testing = ref(false)
const testResult = ref(null) // { ok, text }——连通性测试结果，就地展示

// 表单：展开时从 props.item 同步；保存成功后单独清空 api_key
const form = reactive({ api_key: '', base_url: '', model: '' })

// 模型列表（本组件自理；modelsLoaded 保证同一次页面停留内不重复请求，点「刷新」才重拉）
const models = ref([])
const modelsLoaded = ref(false)
const modelsLoading = ref(false)
const modelsError = ref('')
const modelsSource = ref('remote')

// 状态标签三态（SRS §3.15）：色点 + 文字，不做彩色胶囊（系统设计 §4.5.4）
const status = computed(() => {
  if (props.item.is_active) return { text: '当前使用中', color: 'var(--brand)' }
  if (props.item.key_set) return { text: '已配置', color: 'var(--s-offer)' }
  return { text: '未配置', color: 'var(--c-text-3)' }
})

// 下拉选项：模型列表 + 账号已存值的兜底（列表拉不到时仍能回显，不被静默清空）
const modelOptions = computed(() => {
  const options = models.value.map((m) => ({
    value: m.id,
    label: m.is_free ? `${m.display_name}（免费）` : m.display_name
  }))
  const current = props.item.model
  if (current && !options.some((o) => o.value === current)) {
    options.unshift({ value: current, label: `${current}（当前已存）` })
  }
  return options
})

function syncForm() {
  form.api_key = ''
  form.base_url = props.item.base_url
  form.model = props.item.model
  testResult.value = null
}

function toggle() {
  expanded.value = !expanded.value
  if (!expanded.value) return
  syncForm()
  if (props.item.provider === 'custom') showAdvanced.value = true // 必填项不藏在折叠区
  if (!modelsLoaded.value) loadModels()
}

// ---------- 只读探测：模型列表 ----------

async function loadModels(refresh = false) {
  if (needsKey.value && !props.item.key_set) {
    modelsError.value = '保存 Key 后可拉取模型列表，也可直接输入模型 ID'
    return
  }
  modelsLoading.value = true
  modelsError.value = ''
  try {
    const data = await listModelsApi(props.item.provider, refresh, { silent: true })
    models.value = data.models || []
    modelsSource.value = data.source
    modelsLoaded.value = true
  } catch (err) {
    modelsError.value = err.message || '模型列表拉取失败'
  } finally {
    modelsLoading.value = false
  }
}

// ---------- 只读探测：连通性测试 ----------

async function onTest() {
  testing.value = true
  testResult.value = null
  // 不落库：用当前表单填入的凭据测，缺省则用账号已存配置
  const payload = { provider: props.item.provider }
  if (form.api_key) payload.api_key = form.api_key
  if (form.base_url) payload.base_url = form.base_url
  if (form.model) payload.model = form.model
  try {
    const data = await testProviderApi(payload, { silent: true })
    testResult.value = { ok: true, text: `连通正常（模型：${data.model}）` }
  } catch (err) {
    testResult.value = { ok: false, text: err.message || '连通性测试失败' }
  } finally {
    testing.value = false
  }
}

// ---------- 写操作：保存 / 激活 / 删除 ----------

function buildPayload() {
  const payload = {}
  if (form.api_key) payload.api_key = form.api_key // 留空 = 不修改已存 Key
  if (form.base_url !== props.item.base_url) payload.base_url = form.base_url // 空串 = 恢复默认
  if (form.model !== props.item.model) payload.model = form.model // 空串 = 用默认模型
  return payload
}

async function onSave() {
  if (props.item.provider === 'custom' && !form.base_url) {
    ElMessage.warning('自定义供应商必须填写 base_url')
    return
  }
  const payload = buildPayload()
  if (!Object.keys(payload).length) {
    ElMessage.info('没有需要保存的变更')
    return
  }
  saving.value = true
  try {
    await saveProviderApi(props.item.provider, payload)
    form.api_key = ''
    ElMessage.success('已保存')
    emit('changed')
  } finally {
    saving.value = false
  }
}

async function onActivate() {
  try {
    await activateProviderApi(props.item.provider)
    ElMessage.success(`已切换为「${props.item.name}」`)
    emit('changed')
  } catch {
    // 失败原因（如 10001 未配置 Key）由 request.js 统一提示
  }
}

async function onDelete() {
  const tip = props.item.is_active
    ? `删除「${props.item.name}」的配置？删除后 AI 功能将不可用。`
    : `删除「${props.item.name}」的配置？`
  try {
    await ElMessageBox.confirm(tip, '删除配置', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消'
    })
  } catch {
    return
  }
  try {
    await deleteProviderApi(props.item.provider)
    ElMessage.success('已删除')
    expanded.value = false // 收起：避免表单残留已删除的配置，再展开时重新同步
    emit('changed')
  } catch {
    // 失败原因由 request.js 统一提示
  }
}
</script>

<template>
  <div class="pcard" :class="{ 'pcard--active': item.is_active }">
    <!-- 折叠头：一行看全状态 -->
    <div class="pcard__head" @click="toggle">
      <span class="pcard__name">{{ item.name }}</span>
      <span class="pcard__status">
        <i class="pcard__dot" :style="{ background: status.color }"></i>{{ status.text }}
      </span>
      <span class="pcard__model">{{ item.model || '默认模型' }}</span>
      <span class="pcard__arrow" :class="{ 'pcard__arrow--up': expanded }">▾</span>
    </div>

    <div v-show="expanded" class="pcard__body">
      <p v-if="!needsKey" class="pcard__note">本地模型，无需 API Key</p>

      <!-- Key -->
      <div v-if="needsKey" class="pcard__field">
        <label>API Key</label>
        <el-input
          v-model="form.api_key"
          type="password"
          show-password
          :placeholder="item.key_set ? '已配置，留空则不修改' : '粘贴 API Key'"
        />
      </div>

      <!-- 高级设置 -->
      <div class="pcard__field">
        <el-button link type="primary" @click="showAdvanced = !showAdvanced">
          高级设置 {{ showAdvanced ? '▾' : '▸' }}
        </el-button>
        <div v-if="showAdvanced" class="pcard__advanced">
          <label>base_url</label>
          <el-input v-model="form.base_url" placeholder="留空 = 恢复默认端点" />
        </div>
      </div>

      <!-- 模型 -->
      <div class="pcard__field">
        <label>模型</label>
        <div class="pcard__model-row">
          <!-- allow-create：模型列表拉不到时（未保存 Key / 断网回退 / 自定义端点）仍可手输模型 ID，
               否则 custom 供应商会陷入「测试连通性需选模型 → 选模型需先保存 Key」的死结 -->
          <el-select
            v-model="form.model"
            filterable
            allow-create
            default-first-option
            clearable
            :loading="modelsLoading"
            placeholder="默认模型"
          >
            <el-option v-for="o in modelOptions" :key="o.value" :value="o.value" :label="o.label" />
          </el-select>
          <el-button link type="primary" @click="loadModels(true)">刷新</el-button>
        </div>
        <p v-if="modelsError" class="pcard__note">{{ modelsError }}</p>
        <p v-else-if="modelsSource === 'builtin'" class="pcard__note">
          内置列表（上次拉取失败）
        </p>
      </div>

      <!-- 就地结果 -->
      <p v-if="testResult" class="pcard__result" :class="testResult.ok ? 'is-ok' : 'is-err'">
        {{ testResult.text }}
      </p>

      <!-- 操作 -->
      <div class="pcard__actions">
        <el-button type="primary" :loading="saving" @click="onSave">保存</el-button>
        <el-button :loading="testing" @click="onTest">测试连通性</el-button>
        <el-button v-if="!item.is_active" @click="onActivate">设为当前使用</el-button>
        <el-button v-else disabled>当前使用中</el-button>
        <!-- 有配置行才可删（接口对未配置项返 10002）：Key / 模型 / 激活位任一存在即认为有配置 -->
        <el-button
          v-if="item.key_set || item.model || item.is_active"
          link
          type="danger"
          class="pcard__del"
          @click="onDelete"
        >
          删除配置
        </el-button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.pcard {
  background: var(--c-card);
  border: 1px solid var(--c-border);
  border-radius: var(--r-card);
  margin-bottom: var(--card-gap);
}
/* 当前激活项以左侧色条标识，不靠阴影（设计文档 §4.5.4 明确禁止"所有卡片压同一层阴影"） */
.pcard--active {
  border-left: 3px solid var(--brand);
}
.pcard__head {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 18px;
  cursor: pointer;
}
.pcard__name {
  font-size: 13px;
  font-weight: 700;
  color: var(--c-text);
}
.pcard__status {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  color: var(--c-text-2);
}
/* flex 子项默认可收缩，中文会逐字换行成竖排（步骤 4 的看板卡片踩过同一个坑）——
   一律 nowrap + 不可收缩，模型名过长时以省略号收尾而非压扁 */
.pcard__name,
.pcard__status,
.pcard__arrow {
  white-space: nowrap;
  flex: none;
}
.pcard__dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
}
.pcard__model {
  margin-left: auto;
  font-size: 12px;
  color: var(--c-text-2);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.pcard__arrow {
  font-size: 12px;
  color: var(--c-text-3);
  transition: transform 0.15s;
}
.pcard__arrow--up {
  transform: rotate(180deg);
}
.pcard__body {
  padding: 0 18px 16px;
}
.pcard__note {
  font-size: 12px;
  color: var(--c-text-2);
  margin: 0 0 10px;
}
.pcard__field {
  margin-bottom: 12px;
}
.pcard__field > label {
  display: block;
  font-size: 12px;
  color: var(--c-text-2);
  margin-bottom: 6px;
}
.pcard__advanced {
  margin-top: 8px;
}
.pcard__model-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.pcard__model-row .el-select {
  flex: 1;
}
.pcard__result {
  font-size: 12px;
  margin: 0 0 12px;
}
.pcard__result.is-ok {
  color: var(--s-offer);
}
.pcard__result.is-err {
  color: var(--m-wrong);
}
.pcard__actions {
  display: flex;
  align-items: center;
  gap: 10px;
  padding-top: 12px;
  border-top: 1px solid var(--c-divider);
}
.pcard__del {
  margin-left: auto;
}
</style>
