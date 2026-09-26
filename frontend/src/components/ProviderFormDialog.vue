<script setup>
/**
 * AI 供应商配置弹窗（SRS §3.15 / 接口文档 §3.3）：「添加自定义模型」与行内「修改」共用。
 *
 * 注册表内的供应商在此作为**预选项**提供（不再平铺在页面上）；编辑态**供应商锁定**——
 * 换供应商 = 删了重加（需求 §3.15 行操作）。
 *
 * 只读探测（模型列表、连通性测试）由本组件自理、结果就地展示；保存成功后 emit('saved')，
 * 由页面整体重拉——is_active 是互斥关系，局部更新会在切换后留下两个「当前使用中」。
 */
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { listModelsApi, saveProviderApi, testProviderApi } from '../api/llmProviders'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  /** 编辑态的目标项（`GET /llm-providers` 的单条）；新增态传 null */
  item: { type: Object, default: null },
  /** 注册表全部项，供供应商下拉预选 */
  providers: { type: Array, default: () => [] }
})
const emit = defineEmits(['update:modelValue', 'saved'])

const isEdit = computed(() => !!props.item)
const visible = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v)
})

const form = reactive({ provider: '', api_key: '', base_url: '', model: '' })
const saving = ref(false)
const testing = ref(false)
const testResult = ref(null) // { ok, text }
const models = ref([])
const modelsLoading = ref(false)
const modelsError = ref('')

/** 内置模型表的来源标记（接口文档 v1.24 §3.3）：`preview` = 未配 Key 时的预览清单，
 *  `fallback` = 配了 Key 但拉取失败的回退；空串表示当前列表是远程实时结果。 */
const builtinSource = ref('')

/** 当前选中的注册表项。 */
const meta = computed(() => props.providers.find((p) => p.provider === form.provider))
/** 该家是否需要 Key——取接口下发的 `needs_key`（注册表静态属性），不再按 provider 硬编码。 */
const needsKey = computed(() => meta.value?.needs_key !== false)

/** 模型下拉选项：拉到的列表 + 账号已存值的兜底（列表拉不到时仍能回显，不被静默清空）。 */
const modelOptions = computed(() => {
  const options = models.value.map((m) => ({
    value: m.id,
    label: m.display_name
  }))
  const current = form.model
  if (current && !options.some((o) => o.value === current)) {
    options.unshift({ value: current, label: `${current}（当前已存）` })
  }
  return options
})

watch(
  () => props.modelValue,
  (open) => {
    if (!open) return
    const item = props.item
    form.provider = item?.provider || ''
    form.api_key = ''
    form.base_url = item?.base_url || ''
    form.model = item?.model || ''
    models.value = []
    modelsError.value = ''
    builtinSource.value = ''
    testResult.value = null
    // 打开即预拉：不填 Key 也能看到内置模型表（接口 v1.24 已放开预览），
    // 免得用户对着空下拉无从下手
    if (form.provider) loadModels()
  }
)

/** 新增态切换供应商：清掉上一家的端点与模型（编辑态锁定，不触发），随即预拉该家清单。 */
watch(
  () => form.provider,
  () => {
    if (isEdit.value) return
    form.base_url = ''
    form.model = ''
    models.value = []
    modelsError.value = ''
    builtinSource.value = ''
    // 选中即拉：未填 Key 时后端回内置模型表（接口 v1.24），用户据此先看看有哪些可选
    if (form.provider) loadModels()
  }
)

async function loadModels(refresh = false) {
  if (!form.provider) return
  // 临时探测参数（接口 v1.13）：只在**尚未保存**该供应商配置时携带——已存配置传了会绕过 24h 缓存
  const tempKey = props.item?.key_set ? '' : form.api_key
  const tempBase = form.base_url && form.base_url !== props.item?.base_url ? form.base_url : ''
  // 未配 Key 也是合法路径（接口 v1.24）：后端回内置模型表供预览，故不再前置拦截。
  // 注意放宽的只是「看列表」——保存配置、连通性测试、激活仍强制填 Key。
  modelsLoading.value = true
  modelsError.value = ''
  try {
    const data = await listModelsApi(form.provider, { refresh, apiKey: tempKey, baseUrl: tempBase }, { silent: true })
    models.value = data.models || []
    // 内置表的两种来源要分文案（接口 v1.24 §3.3）：手里有 Key 说明是拉取失败的回退，
    // 没有 Key 则是主动预览。
    const hasKey = Boolean(props.item?.key_set || tempKey)
    builtinSource.value = data.source === 'builtin' ? (hasKey ? 'fallback' : 'preview') : ''
  } catch (err) {
    modelsError.value = err.message || '模型列表拉取失败'
    builtinSource.value = ''
  } finally {
    modelsLoading.value = false
  }
}

/** 粘贴 Key 后失焦即拉列表——「填了就能拉」的入口（接口 v1.13 的临时探测）。 */
function onKeyBlur() {
  if (form.api_key && !props.item?.key_set && !models.value.length) loadModels()
}

/** 组装连通性测试的载荷：一律用**表单当前值**（未保存的 Key / 端点 / 模型），
 *  后端按临时参数测、不读已存配置——这样「改了 Key 想换一家」也能先被验证。 */
function buildTestPayload() {
  const payload = { provider: form.provider }
  if (form.api_key) payload.api_key = form.api_key
  if (form.base_url) payload.base_url = form.base_url
  if (form.model) payload.model = form.model
  return payload
}

async function onTest() {
  testing.value = true
  testResult.value = null
  try {
    const data = await testProviderApi(buildTestPayload(), { silent: true })
    testResult.value = { ok: true, text: `连通正常（模型：${data.model}）` }
  } catch (err) {
    testResult.value = { ok: false, text: err.message || '连通性测试失败' }
  } finally {
    testing.value = false
  }
}

async function onSave() {
  if (!form.provider) {
    ElMessage.warning('请选择供应商')
    return
  }
  if (form.provider === 'custom' && !form.base_url) {
    ElMessage.warning('自定义供应商必须填写端点')
    return
  }
  // 编辑态只提交变更字段；新增态至少要有 Key（免 Key 的家除外）或模型
  const payload = {}
  if (form.api_key) payload.api_key = form.api_key
  if (!isEdit.value || form.base_url !== (props.item?.base_url || '')) payload.base_url = form.base_url
  if (!isEdit.value || form.model !== (props.item?.model || '')) payload.model = form.model
  if (isEdit.value && !form.api_key && !Object.keys(payload).length) {
    ElMessage.info('没有需要保存的变更')
    return
  }
  // 先测连通再落库：连不通就不该存下来。
  // 测试与保存是两个独立接口、非原子——极端情况下会出现「测试通过但保存失败」，
  // 此时如实报错即可，不额外补偿。
  saving.value = true
  testResult.value = null
  try {
    try {
      await testProviderApi(buildTestPayload(), { silent: true })
    } catch (err) {
      testResult.value = { ok: false, text: `连接失败，未保存：${err.message || '连通性测试未通过'}` }
      return
    }
    try {
      await saveProviderApi(form.provider, payload)
      ElMessage.success('已保存')
      visible.value = false
      emit('saved')
    } catch (err) {
      testResult.value = { ok: false, text: err.message || '保存失败' }
    }
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <el-dialog v-model="visible" :title="isEdit ? '修改配置' : '添加自定义模型'" width="520px">
    <el-form label-width="86px" label-position="left">
      <el-form-item label="供应商">
        <el-select v-model="form.provider" :disabled="isEdit" filterable placeholder="选择供应商" class="pf__full">
          <el-option v-for="p in providers" :key="p.provider" :label="`${p.name}（${p.group}）`" :value="p.provider" />
        </el-select>
      </el-form-item>

      <el-form-item v-if="needsKey" label="API Key">
        <el-input
          v-model="form.api_key"
          type="password"
          show-password
          :placeholder="item?.key_set ? '已保存，留空则不修改' : '粘贴该供应商的 API Key'"
          @blur="onKeyBlur"
        />
      </el-form-item>
      <el-form-item v-else label="API Key">
        <span class="pf__keyless">该供应商无需 Key，可直接保存</span>
      </el-form-item>

      <el-form-item label="端点">
        <el-input v-model="form.base_url" :placeholder="meta?.base_url || '留空则用注册表默认端点'" />
      </el-form-item>

      <el-form-item label="模型">
        <el-select
          v-model="form.model"
          filterable
          allow-create
          default-first-option
          placeholder="选择或直接输入模型 ID"
          class="pf__full"
        >
          <el-option v-for="o in modelOptions" :key="o.value" :label="o.label" :value="o.value" />
        </el-select>
        <div class="pf__actions">
          <el-button link type="primary" :loading="modelsLoading" @click="loadModels(true)">刷新模型列表</el-button>
          <el-button link type="primary" :loading="testing" @click="onTest">测试连通</el-button>
        </div>
      </el-form-item>

      <el-alert v-if="modelsError" class="pf__hint" :title="modelsError" type="info" :closable="false" />
      <!-- 内置模型表的两种来源分文案（接口文档 v1.24 §3.3）：用户据此知道该怎么拿到完整列表 -->
      <el-alert
        v-else-if="builtinSource"
        class="pf__hint"
        :title="
          builtinSource === 'preview'
            ? '内置清单（填写 Key 后拉取完整列表）'
            : '内置列表（上次拉取失败）'
        "
        type="info"
        :closable="false"
      />
      <el-alert
        v-if="testResult"
        class="pf__hint"
        :title="testResult.text"
        :type="testResult.ok ? 'success' : 'error'"
        :closable="false"
      />
    </el-form>

    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="saving" @click="onSave">
        {{ saving ? '验证并保存中…' : '保存' }}
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.pf__full {
  width: 100%;
}
.pf__actions {
  display: flex;
  gap: 12px;
  margin-top: 4px;
}
.pf__hint {
  margin-top: 4px;
}
.pf__keyless {
  font-size: var(--fs-body);
  color: var(--c-text-3);
}
</style>
