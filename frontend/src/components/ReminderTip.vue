<script setup>
/**
 * 概览区块的提醒文案行（步骤 20）：当日未读提醒的一句话文案，挂在对应区块标题下。
 * 无文案时不渲染——概览页「有内容才显示」的既有口径（空区块不占位置）。
 */
import { Bell } from '@element-plus/icons-vue'

defineProps({
  text: { type: String, default: '' }
})
</script>

<template>
  <p v-if="text" class="tip">
    <el-icon class="tip__icon"><Bell /></el-icon>
    <span>{{ text }}</span>
  </p>
</template>

<style scoped>
.tip {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  margin: 0 0 10px;
  padding: 8px 12px;
  border-radius: var(--r-control);
  background: color-mix(in srgb, var(--brand) 6%, var(--c-card));
  color: var(--brand);
  font-size: var(--fs-sm);
  line-height: 1.6;
}
.tip__icon {
  flex: none;
  font-size: 14px;
  margin-top: 3px;
}
</style>
