<script setup>
/**
 * 面经整理（步骤 17 的页面，此处为占位）。
 *
 * 实现内容见开发计划步骤 17：粘贴面经 → AI 结构化提取 → 条目检索；
 * 提取失败时原文保留，不丢内容。
 */
import AppEmpty from '../components/AppEmpty.vue'
</script>

<template>
  <div class="experiences">
    <AppEmpty
      type="build"
      title="面经整理正在建设中"
      description="粘贴一篇面经，AI 自动拆成结构化条目（公司 / 岗位 / 轮次 / 问题），关键词一搜就命中，见开发计划步骤 17"
      style="--empty-color: var(--m-experience)"
    />
  </div>
</template>

<style scoped>
.experiences {
  background: var(--c-card);
  border: 1px solid var(--c-border);
  border-radius: var(--r-card);
  box-shadow: 0 1px 2px rgba(42, 39, 64, 0.05);
}
</style>
