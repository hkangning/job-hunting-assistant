<script setup>
/**
 * 校招情报（步骤 23 的页面，此处为占位）。
 *
 * 先建占位页而非留空路由，是为了让「校招情报」这个入口从现在就可达——
 * 概览页的空态引导、侧栏导航都指向它；若路由不存在，那两处都是死链。
 *
 * 实现内容见开发计划步骤 23：三类信息 Tab（宣讲会 / 双选会 / 岗位）+ 列表·日历视图、
 * 我的订阅、与投递 / JD 分析的打通。设计约定见问题记录 IS-29
 * （招聘信息与投递管理是「候选池 → 进度追踪」两段式，靠视觉语言区分、不合并）。
 */
import AppEmpty from '../components/AppEmpty.vue'
</script>

<template>
  <div class="campus">
    <AppEmpty
      type="build"
      title="校招情报正在建设中"
      description="多所高校就业网的宣讲会 / 双选会 / 岗位聚合、跨源去重与变更提醒，见开发计划步骤 23"
      style="--empty-color: var(--m-campus)"
    />
  </div>
</template>

<style scoped>
.campus {
  background: var(--c-card);
  border: 1px solid var(--c-border);
  border-radius: var(--r-card);
  box-shadow: 0 1px 2px rgba(42, 39, 64, 0.05);
}
</style>
