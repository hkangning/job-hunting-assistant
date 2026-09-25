<script setup>
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import SideNav from './components/SideNav.vue'
import AppHeader from './components/AppHeader.vue'

const route = useRoute()
const collapse = ref(false)

// 账号页（入场动画/登录/注册）走全屏壳：无侧栏无顶栏（系统设计 §4.1）
const isBlank = computed(() => route.meta.layout === 'blank')
</script>

<template>
  <router-view v-if="isBlank" />
  <el-container v-else class="app-layout">
    <el-aside :width="collapse ? '64px' : '230px'" class="app-aside">
      <SideNav :collapse="collapse" />
    </el-aside>
    <el-container>
      <el-header height="56px" class="app-header">
        <AppHeader :collapse="collapse" @toggle="collapse = !collapse" />
      </el-header>
      <el-main class="app-main">
        <router-view />
      </el-main>
    </el-container>
    <!-- 步骤 16 挂载位：<AgentFloatBall /> -->
  </el-container>
</template>

<style>
/* 全局基础样式（设计文档 3.5：不建 styles/ 目录以外的地方，写在此处非 scoped 块内） */
html,
body,
#app {
  height: 100%;
  margin: 0;
}
</style>

<style scoped>
.app-layout {
  height: 100vh;
}
.app-aside {
  overflow: hidden;
  transition: width 0.22s ease;
}
.app-header {
  padding: 0;
  background: var(--c-card);
  border-bottom: 1px solid var(--c-border);
}
.app-main {
  padding: var(--content-padding);
  background: var(--c-bg);
}
</style>
