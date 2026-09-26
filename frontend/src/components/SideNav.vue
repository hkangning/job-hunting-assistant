<script setup>
import { computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useOverviewStore } from '../stores/overview'
import { shortDateTime } from '../utils/datetime'

defineProps({
  collapse: { type: Boolean, default: false }
})

const route = useRoute()
const router = useRouter()

// 菜单项从路由表派生（单一数据源），过滤掉 hidden 路由
const menuItems = computed(() => router.options.routes.filter((r) => !r.meta?.hidden))

// 按 meta.group 分组，保持路由表声明顺序
const groups = computed(() => {
  const out = []
  for (const item of menuItems.value) {
    const name = item.meta.group
    let g = out.find((x) => x.name === name)
    if (!g) {
      g = { name, items: [] }
      out.push(g)
    }
    g.items.push(item)
  }
  return out
})

// 详情页高亮回其所属菜单项
const activeMenu = computed(() => route.meta.activeMenu || route.path)

// ---------- 今日待办（数据源 GET /overview，系统设计 §4.4）----------
// 与概览页共享 useOverviewStore：两处各调一次会在同一屏发两个相同请求，且数值可能不一致
const overviewStore = useOverviewStore()
const todos = computed(() => (overviewStore.data?.upcoming_events || []).slice(0, 3))

onMounted(() => {
  // 侧栏是全局的：用户直接落在投递页等非概览页时，也要有待办数据
  if (!overviewStore.data) overviewStore.fetch()
})
</script>

<template>
  <div class="side-nav">
    <div class="side-nav__brand">
      <span class="side-nav__mark">求</span>
      <span v-if="!collapse" class="side-nav__name">求职助手</span>
    </div>

    <el-menu
      :default-active="activeMenu"
      :collapse="collapse"
      :collapse-transition="false"
      router
      class="side-nav__menu"
    >
      <el-menu-item-group v-for="group in groups" :key="group.name" :title="group.name">
        <el-menu-item v-for="item in group.items" :key="item.path" :index="item.path">
          <span class="side-nav__dot" :style="{ background: item.meta.color }"></span>
          <template #title>{{ item.meta.title }}</template>
        </el-menu-item>
      </el-menu-item-group>
    </el-menu>

    <div v-if="!collapse && todos.length" class="side-nav__todo">
      <div class="side-nav__todo-title">今日待办</div>
      <div v-for="(t, i) in todos" :key="i" class="side-nav__todo-item">
        <span class="side-nav__todo-time">{{ shortDateTime(t.event_at) }}</span>
        <span class="side-nav__todo-text">{{ t.company }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.side-nav {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--c-sidebar);
  border-right: 1px solid var(--c-border);
}

.side-nav__brand {
  display: flex;
  align-items: center;
  gap: 9px;
  height: var(--header-h);
  flex-shrink: 0;
  padding: 0 16px;
}
.side-nav__mark {
  width: 28px;
  height: 28px;
  border-radius: var(--r-control);
  background: var(--brand);
  color: #fff;
  font-size: var(--fs-title);
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.side-nav__name {
  font-weight: 700;
  color: var(--brand);
  white-space: nowrap;
  letter-spacing: 0.3px;
}

.side-nav__menu {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  overflow-x: hidden;
  border-right: none;
  background: transparent;
  padding: 4px 10px 0;
}
/* 折叠态下 el-menu 自带内边距会挤压，收窄 */
.side-nav__menu.el-menu--collapse {
  padding: 4px 8px 0;
}

/* 折叠态：组标题收起为细分隔线（设计文档 4.4「折叠态以细分隔线代替组标题」）
   el-menu-item-group 的标题由 Element Plus 渲染，需用 :deep 穿透 */
.side-nav__menu.el-menu--collapse :deep(.el-menu-item-group__title) {
  padding: 0;
  margin: 10px 8px;
  height: 1px;
  font-size: 0;
  background: var(--c-border);
  overflow: hidden;
}

.side-nav__dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
  margin-right: 10px;
}
.side-nav__menu.el-menu--collapse .side-nav__dot {
  width: 9px;
  height: 9px;
  margin-right: 0;
}

.side-nav__todo {
  margin: 14px;
  padding: 14px;
  border-radius: var(--r-card);
  background: #fbf6ee;
  border: 1px solid #f0e3ce;
  flex-shrink: 0;
}
/* 标题是这块的"标签"（配一个色点），内容才是条目——故标题取弱化档、条目取次要用 */
.side-nav__todo-title {
  font-size: var(--fs-xs);
  font-weight: 700;
  color: #8f6220;
  margin-bottom: 7px;
  display: flex;
  align-items: center;
  gap: 5px;
}
.side-nav__todo-title::before {
  content: '';
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--m-interview);
}
.side-nav__todo-item {
  display: flex;
  gap: 7px;
  font-size: var(--fs-sm);
  color: var(--c-text-2);
  padding: 4px 0;
  line-height: 1.55;
}
.side-nav__todo-time {
  color: var(--m-interview);
  flex-shrink: 0;
}
.side-nav__todo-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
