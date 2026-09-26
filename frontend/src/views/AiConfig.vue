<script setup>
/**
 * AI 配置页（SRS §3.15 / 接口文档 §3.3）：两条上手路径并存于同一页。
 *
 * 顶部「免费模型」下拉——选中即生效、全程不填 Key（两类来源：公开免 Key 服务与平台共享 Key）；
 * 下方「我的配置」列表——每行一家供应商，行首标记当前使用中。两条路径**共用同一个激活位**，
 * 「当前用哪个」永远只有一个答案（接口文档 §3.3）。
 *
 * 注册表内的供应商退到弹窗的预选项里，不再平铺在页面上（需求 §3.15 页面结构）。
 */
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  activateProviderApi,
  deleteProviderApi,
  listFreeModelsApi,
  listProvidersApi,
  selectFreeModelApi
} from '../api/llmProviders'
import ProviderFormDialog from '../components/ProviderFormDialog.vue'

const loading = ref(true)
const error = ref('')
const active = ref(null)
const providers = ref([]) // 注册表全部 13 项（未配置的也在，但只在弹窗里当预选项）
const freeGroups = ref([]) // 免费模型清单（两类来源）
const freeValue = ref('') // 当前选中的免费模型，编码为 `provider::model`
const dialogVisible = ref(false)
const editing = ref(null) // 编辑态目标项；null = 新增

/** 「我的配置」= 配置过的行；一行都没配的家不进列表（退到弹窗的预选项）。
 *
 * **不能用 `base_url` 判**：接口对未配置的家也会返回注册表默认端点，拿它当判据会恒真、
 * 把全部 13 家都列出来（走查时踩过）。只看账号自己产生过的痕迹：存过 Key / 走过免费档 / 选过模型。
 */
const configured = computed(() =>
  providers.value.filter((p) => p.key_set || p.use_shared || p.model)
)

/** 免费下拉：按供应商分组的选项组。 */
const freeOptions = computed(() =>
  freeGroups.value.map((g) => ({
    label: g.name,
    options: g.models.map((m) => ({ value: `${g.provider}::${m.id}`, label: m.display_name }))
  }))
)

/** 当前生效行若走的免费档，回显到下拉框。 */
const currentFree = computed(() => {
  const row = providers.value.find((p) => p.provider === active.value)
  return row && row.use_shared ? `${row.provider}::${row.model}` : ''
})

/** 当前生效项的文字描述，置顶展示。
 *
 * 两条路径（免费下拉 / 我的配置列表）共用同一个激活位，但下拉框只显示模型名、
 * 列表圆点又不够显眼——**「现在用的是什么」应该有唯一一处明确的答案**。
 * 顺带解决一个真实困惑：重复选同一个免费模型时 `change` 不触发、界面毫无反应，
 * 有了这行就能看出「它本来就已经是当前项」。
 */
const activeLabel = computed(() => {
  const row = providers.value.find((p) => p.provider === active.value)
  if (!row) return '未配置（AI 功能不可用）'
  return `${row.name} · ${row.model || '默认模型'}${row.use_shared ? '（免费档）' : ''}`
})

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [list, free] = await Promise.all([
      listProvidersApi({ silent: true }),
      listFreeModelsApi({ silent: true })
    ])
    providers.value = list.providers || []
    active.value = list.active
    freeGroups.value = free.providers || []
    freeValue.value = currentFree.value
  } catch (err) {
    error.value = err.message || '配置加载失败'
  } finally {
    loading.value = false
  }
}

/** 选中免费模型即生效（后端保存 + 激活一步完成，账号无需自备 Key）。 */
async function onFreeChange(value) {
  if (!value) return
  const [provider, model] = value.split('::')
  try {
    await selectFreeModelApi({ provider, model })
    ElMessage.success('已切换，开始使用该免费模型')
    await load()
  } catch {
    freeValue.value = currentFree.value // 失败回退到原值，避免下拉框显示成已切换
  }
}

async function onActivate(item) {
  await activateProviderApi(item.provider)
  ElMessage.success(`已切换到 ${item.name}`)
  await load()
}

async function onRemove(item) {
  const isCurrent = item.is_active
  try {
    await ElMessageBox.confirm(
      isCurrent
        ? `「${item.name}」是当前使用的配置，删除后 AI 功能将不可用，直至重新选择。确定删除？`
        : `删除「${item.name}」的配置（Key / 模型 / 端点）？`,
      '删除配置',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    )
  } catch {
    return // 取消
  }
  await deleteProviderApi(item.provider)
  ElMessage.success('已删除')
  await load()
}

function openAdd() {
  editing.value = null
  dialogVisible.value = true
}

function openEdit(item) {
  editing.value = item
  dialogVisible.value = true
}

onMounted(load)
</script>

<template>
  <div class="ai" v-loading="loading">
    <el-alert v-if="error" :title="error" type="error" :closable="false" class="ai__error" />

    <div class="ai__current">
      当前使用中：<strong>{{ activeLabel }}</strong>
    </div>

    <!-- 免费模型：选中即生效 -->
    <section v-if="freeOptions.length" class="ai__card">
      <h3 class="ai__card-title">免费模型</h3>
      <el-select
        v-model="freeValue"
        class="ai__free"
        placeholder="选一个免费模型即可开始使用（无需填 Key）"
        @change="onFreeChange"
      >
        <el-option-group v-for="g in freeOptions" :key="g.label" :label="g.label">
          <el-option v-for="o in g.options" :key="o.value" :label="o.label" :value="o.value" />
        </el-option-group>
      </el-select>
      <p class="ai__hint">平台预置或公开免费，不用自己配置；随时可改用下方自己的 Key。</p>
    </section>

    <!-- 我的配置 -->
    <section class="ai__card">
      <div class="ai__head">
        <h3 class="ai__card-title">我的配置</h3>
        <el-button type="primary" size="small" @click="openAdd">+ 添加自定义模型</el-button>
      </div>

      <el-empty v-if="!configured.length" description="还没有自己的配置" :image-size="60" />
      <ul v-else class="ai__list">
        <li v-for="item in configured" :key="item.provider" class="ai__row">
          <span class="ai__dot" :class="{ 'ai__dot--on': item.is_active }" />
          <span class="ai__name">{{ item.name }}</span>
          <span class="ai__model">{{ item.model || '默认模型' }}</span>
          <span v-if="item.use_shared" class="ai__tag">免费档</span>
          <span class="ai__group">{{ item.group }}</span>
          <div class="ai__ops">
            <el-button v-if="!item.is_active" size="small" @click="onActivate(item)">设为当前</el-button>
            <el-button size="small" @click="openEdit(item)">修改</el-button>
            <el-button size="small" type="danger" plain @click="onRemove(item)">删除</el-button>
          </div>
        </li>
      </ul>
    </section>

    <ProviderFormDialog v-model="dialogVisible" :item="editing" :providers="providers" @saved="load" />
  </div>
</template>

<style scoped>
.ai {
  display: flex;
  flex-direction: column;
  gap: 14px;
  max-width: 820px;
}
.ai__error {
  margin-bottom: 4px;
}
.ai__current {
  padding: 9px 14px;
  border-radius: var(--r-card);
  background: var(--c-bg);
  font-size: var(--fs-body);
  color: var(--c-text-2);
}
.ai__current strong {
  color: var(--c-text);
}
.ai__card {
  padding: 16px 18px;
  border: 1px solid var(--c-border);
  border-radius: var(--r-card);
  background: var(--c-card);
}
.ai__card-title {
  margin: 0 0 10px;
  font-size: var(--fs-title);
  font-weight: 600;
  color: var(--c-text);
}
.ai__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}
.ai__head .ai__card-title {
  margin: 0;
}
.ai__free {
  width: 100%;
}
.ai__hint {
  margin: 8px 0 0;
  font-size: var(--fs-sm);
  color: var(--c-text-3);
}
.ai__list {
  margin: 0;
  padding: 0;
  list-style: none;
}
.ai__row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 4px;
  border-bottom: 1px solid var(--c-divider);
}
.ai__row:last-child {
  border-bottom: none;
}
.ai__dot {
  width: 8px;
  height: 8px;
  flex-shrink: 0;
  border-radius: 50%;
  background: var(--c-border);
}
.ai__dot--on {
  background: var(--brand);
}
.ai__name {
  min-width: 120px;
  font-size: var(--fs-title);
  color: var(--c-text);
}
.ai__model {
  flex: 1;
  overflow: hidden;
  font-size: var(--fs-body);
  color: var(--c-text-2);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ai__tag {
  padding: 0 6px;
  border-radius: var(--r-mark);
  background: var(--c-bg);
  font-size: var(--fs-xs);
  color: var(--m-jd);
}
.ai__group {
  font-size: var(--fs-sm);
  color: var(--c-text-3);
}
.ai__ops {
  display: flex;
  gap: 6px;
}
</style>
