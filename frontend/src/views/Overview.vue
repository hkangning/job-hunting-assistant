<script setup>
import { ref, onMounted } from 'vue'
import request from '../api/request'

const loading = ref(true)
const connected = ref(false)
const health = ref(null)
const errorText = ref('')

async function loadHealth() {
  loading.value = true
  errorText.value = ''
  try {
    health.value = await request.get('/health')
    connected.value = true
  } catch (e) {
    connected.value = false
    errorText.value = e.message
  } finally {
    loading.value = false
  }
}

onMounted(loadHealth)
</script>

<template>
  <div>
    <el-card v-loading="loading" class="health-card">
      <template #header>后端连接状态</template>

      <template v-if="connected">
        <el-tag type="success">已连接</el-tag>
        <span class="health-card__text">
          AI 配置：{{ health && health.llm_configured ? '已配置' : '未配置' }}
        </span>
        <el-button size="small" @click="loadHealth">重新检测</el-button>
      </template>

      <template v-else-if="!loading">
        <el-tag type="danger">未连接</el-tag>
        <span class="health-card__text">{{ errorText }}</span>
        <el-button size="small" @click="loadHealth">重试</el-button>
      </template>
    </el-card>

    <el-empty description="页面建设中 · 对应开发计划步骤 5" />
  </div>
</template>

<style scoped>
.health-card {
  margin-bottom: var(--card-gap);
}
.health-card__text {
  margin: 0 12px;
  color: var(--c-text-2);
}
</style>
