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
    <!-- 宽度不传 width prop，改由 CSS 类读 tokens.css 的变量：原写法把 230px / 64px
         在 tokens.css 与这里各写了一遍，改一处另一处不动。el-aside 的 width 默认
         为 null 且为 null 时不生成内联样式，故 CSS 可以接管。 -->
    <el-aside class="app-aside" :class="{ 'app-aside--collapsed': collapse }">
      <SideNav :collapse="collapse" />
    </el-aside>
    <el-container>
      <el-header class="app-header">
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
  width: var(--sidebar-w);
  overflow: hidden;
  transition: width 0.22s ease;
}
.app-aside--collapsed {
  width: var(--sidebar-w-collapsed);
}
.app-header {
  /* 高度读 tokens.css 变量：原为 height="56px" prop，与 --header-h 各写一遍。
     而 SideNav 的品牌区高度读的正是 --header-h——两处不同源会让顶栏与侧栏错位。 */
  height: var(--header-h);
  padding: 0;
  background: var(--c-card);
  border-bottom: 1px solid var(--c-border);
}
.app-main {
  padding: var(--content-padding);
  background: var(--c-bg);
}
</style>
