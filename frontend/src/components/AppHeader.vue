<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Fold, Expand, Bell } from '@element-plus/icons-vue'

defineProps({
  collapse: { type: Boolean, default: false }
})
defineEmits(['toggle'])

const route = useRoute()
const router = useRouter()
const title = computed(() => route.meta.title || '')

// 「新增投递」是最高频操作，固定在顶栏；跳转带 query，由投递页打开新增表单
function goNewApplication() {
  router.push({ path: '/applications', query: { action: 'new' } })
}
</script>

<template>
  <div class="app-header">
    <el-icon class="app-header__toggle" @click="$emit('toggle')">
      <component :is="collapse ? Expand : Fold" />
    </el-icon>
    <h1 class="app-header__title">{{ title }}</h1>

    <div class="app-header__actions">
      <!-- 页面级操作注入位：页面组件用 <Teleport to="#app-header-actions-slot"> 注入 -->
      <div id="app-header-actions-slot" class="app-header__slot"></div>
      <slot name="actions" />
      <el-icon class="app-header__icon" title="提醒"><Bell /></el-icon>
      <el-button type="primary" @click="goNewApplication">＋ 新增投递</el-button>
    </div>
  </div>
</template>

<style scoped>
.app-header {
  display: flex;
  align-items: center;
  gap: 12px;
  width: 100%;
  height: 100%;
}
.app-header__toggle {
  font-size: 20px;
  cursor: pointer;
  color: var(--c-text-2);
}
.app-header__toggle:hover {
  color: var(--brand);
}
.app-header__title {
  margin: 0;
  font-size: 15.5px;
  font-weight: 700;
  color: var(--c-text);
}
.app-header__actions {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 14px;
}
.app-header__slot {
  display: flex;
  align-items: center;
  gap: 14px;
}
.app-header__slot:empty {
  display: none;
}
.app-header__icon {
  font-size: 17px;
  cursor: pointer;
  color: var(--c-text-2);
}
.app-header__icon:hover {
  color: var(--brand);
}
</style>
