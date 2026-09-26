<script setup>
/**
 * AI 配置页（SRS §3.15 / 接口文档 §3.3）：单一入口「我的配置」。
 *
 * 每行一家供应商，行首标记当前使用中；「当前用哪个」永远只有一个答案（接口文档 §3.3）。
 * 注册表内的供应商退到弹窗的预选项里，不再平铺在页面上（需求 §3.15 页面结构）。
 *
 * 需求 v1.15 已**摘除平台免费模型档**——原「免费模型」下拉与公开免 Key 服务一并下线，
 * AI 能力统一由账号自配 API Key（接口文档 v1.23 §3.3）。
 */
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  activateProviderApi,
  deleteProviderApi,
  listProvidersApi
} from '../api/llmProviders'
import ProviderFormDialog from '../components/ProviderFormDialog.vue'

const loading = ref(true)
const error = ref('')
const active = ref(null)
const providers = ref([]) // 注册表全部 12 项（未配置的也在，但只在弹窗里当预选项）
const dialogVisible = ref(false)
const editing = ref(null) // 编辑态目标项；null = 新增

/** 「我的配置」= 配置过的行；一行都没配的家不进列表（退到弹窗的预选项）。
 *
 * **不能用 `base_url` 判**：接口对未配置的家也会返回注册表默认端点，拿它当判据会恒真、
 * 把全部 12 家都列出来（走查时踩过）。只看账号自己产生过的痕迹：存过 Key / 选过模型。
 */
const configured = computed(() =>
  providers.value.filter((p) => p.key_set || p.model)
)

/** 当前生效项的文字描述，置顶展示。
 *
 * 「现在用的是什么」应该有唯一一处明确的答案——列表圆点不够显眼。
 * 顺带解决一个真实困惑：重复点同一个**已激活的行**时界面毫无反应，
 * 有了这行就能看出「它本来就已经是当前项」。
 */
const activeLabel = computed(() => {
  const row = providers.value.find((p) => p.provider === active.value)
  if (!row) return '未配置（AI 功能不可用）'
  return `${row.name} · ${row.model || '默认模型'}`
})

async function load() {
  loading.value = true
  error.value = ''
  try {
    const list = await listProvidersApi({ silent: true })
    providers.value = list.providers || []
    active.value = list.active
  } catch (err) {
    error.value = err.message || '配置加载失败'
  } finally {
    loading.value = false
  }
}

async function onActivate(item) {
  await activateProviderApi(item.provider)
  ElMessage.success(`已切换到 ${item.name}`)
  await load()
}

/** 点击整行 = 设为当前（仅非激活行可点，激活行点击无意义）。
 *  行内「修改 / 删除」按钮所在的容器已 stopPropagation，不会误触发本函数。 */
function onRowClick(item) {
  if (item.is_active) return
  onActivate(item)
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

    <!-- 我的配置：当前使用中作为卡片首条，与列表同属一个容器 -->
    <section class="ai__card">
      <div class="ai__head">
        <h3 class="ai__card-title">我的配置</h3>
        <el-button type="primary" size="small" @click="openAdd">+ 添加自定义模型</el-button>
      </div>

      <div class="ai__current">
        <span class="ai__dot" :class="{ 'ai__dot--on': Boolean(active) }" />
        当前使用中：<strong>{{ activeLabel }}</strong>
      </div>

      <el-empty v-if="!configured.length" description="还没有自己的配置" :image-size="60" />
      <ul v-else class="ai__list">
        <li
          v-for="item in configured"
          :key="item.provider"
          class="ai__row"
          :class="{ 'ai__row--clickable': !item.is_active }"
          @click="onRowClick(item)"
        >
          <span class="ai__dot" :class="{ 'ai__dot--on': item.is_active }" />
          <span class="ai__name">{{ item.name }}</span>
          <span class="ai__model">{{ item.model || '默认模型' }}</span>
          <!-- 行内操作区 stopPropagation：否则点「修改 / 删除」会连带触发整行的「设为当前」 -->
          <div class="ai__ops" @click.stop>
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
  max-width: 1100px;
}
.ai__error {
  margin-bottom: 4px;
}
/* 卡片内的首条：与列表同属一个容器，「现在用哪个」不再浮在卡片外 */
.ai__current {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  padding: 9px 14px;
  border-radius: var(--r-control);
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
/* 非激活行可整行点击设为当前；激活行无此交互，故不加指针与悬停反馈 */
.ai__row--clickable {
  cursor: pointer;
}
.ai__row--clickable:hover {
  background: var(--c-bg);
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
.ai__ops {
  display: flex;
  gap: 6px;
}
</style>
