<script setup>
/**
 * AI 配置页（SRS §3.15 / 接口文档 §3.3）。
 * 页面持有 providers 列表为唯一数据源；卡片动作完成后 emit changed，由本页整体重拉——
 * is_active 是互斥关系，局部更新会在切换后留下两个「当前使用中」。
 */
import { computed, onMounted, ref } from 'vue'
import { listProvidersApi } from '../api/llmProviders'
import ProviderCard from '../components/ProviderCard.vue'

const loading = ref(true)
const error = ref('')
const active = ref(null)
const providers = ref([])

// 按后端返回的 group 分组，组顺序即注册表顺序，不在前端重排
const groups = computed(() => {
  const map = new Map()
  for (const p of providers.value) {
    if (!map.has(p.group)) map.set(p.group, [])
    map.get(p.group).push(p)
  }
  return [...map.entries()].map(([name, items]) => ({ name, items }))
})

async function load() {
  loading.value = true
  error.value = ''
  try {
    const data = await listProvidersApi({ silent: true })
    providers.value = data.providers || []
    active.value = data.active
  } catch (err) {
    error.value = err.message || '配置加载失败'
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div v-loading="loading" class="ai-config">
    <!-- 加载失败：可重试 -->
    <div v-if="error" class="ai-config__error">
      <span>{{ error }}</span>
      <el-button size="small" @click="load">重试</el-button>
    </div>

    <!-- 未配置任何可用供应商：AI 功能不可用，必须让用户一眼看到 -->
    <el-alert
      v-else-if="!loading && !active"
      type="warning"
      :closable="false"
      show-icon
      title="尚未配置可用的 AI 供应商，AI 功能暂不可用"
      class="ai-config__alert"
    />

    <section v-for="g in groups" :key="g.name" class="ai-config__group">
      <h3 class="ai-config__group-title">{{ g.name }}</h3>
      <ProviderCard v-for="p in g.items" :key="p.provider" :item="p" @changed="load" />
    </section>

    <el-empty v-if="!loading && !error && !providers.length" description="暂无供应商数据" />
  </div>
</template>

<style scoped>
/* 页面不渲染标题：标题职责归顶栏（系统设计 §4.4），页内再渲染会出现同屏两个相同标题 */
.ai-config__error {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 18px;
  background: var(--c-card);
  border: 1px solid var(--c-border);
  border-radius: var(--r-card);
  font-size: 13px;
  color: var(--c-text);
}
.ai-config__alert {
  margin-bottom: 14px;
}
.ai-config__group {
  margin-bottom: 18px;
}
.ai-config__group-title {
  font-size: 12px;
  font-weight: 700;
  color: var(--c-text-2);
  margin: 4px 0 10px;
}
</style>
