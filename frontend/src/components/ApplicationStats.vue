<script setup>
// 投递统计条：总数 / 本周新增 + 状态占比堆叠条 + 计数图例
// 受控组件：全部指标由页面传入的 items 现算，不调接口
import { computed } from 'vue'
import { APPLICATION_STATUSES } from '../constants/application'

const props = defineProps({
  items: { type: Array, default: () => [] },
  truncated: { type: Boolean, default: false }
})

const total = computed(() => props.items.length)

const counts = computed(() => {
  const map = Object.fromEntries(APPLICATION_STATUSES.map((s) => [s.value, 0]))
  props.items.forEach((item) => {
    if (map[item.status] !== undefined) map[item.status] += 1
  })
  return map
})

/** 本周新增：applied_at 落在本周一（含）至今 */
const weekAdded = computed(() => {
  const now = new Date()
  const mondayOffset = (now.getDay() + 6) % 7 // 以周一为一周之始
  const monday = new Date(now.getFullYear(), now.getMonth(), now.getDate() - mondayOffset)
  return props.items.filter((item) => {
    if (!item.applied_at) return false
    const [y, m, d] = item.applied_at.split('-').map(Number)
    return new Date(y, m - 1, d) >= monday
  }).length
})

/** 堆叠条分段：只保留非零状态，段宽 = 该状态占比 */
const segments = computed(() =>
  APPLICATION_STATUSES.filter((s) => counts.value[s.value] > 0).map((s) => ({
    ...s,
    count: counts.value[s.value],
    percent: (counts.value[s.value] / total.value) * 100
  }))
)
</script>

<template>
  <div class="stats">
    <div class="stats__summary">
      <span class="stats__total">{{ total }} 条投递</span>
      <span class="stats__week">本周 +{{ weekAdded }}</span>
    </div>

    <div class="stats__right">
      <div class="stats__bar">
        <div
          v-for="seg in segments"
          :key="seg.value"
          class="stats__seg"
          :style="{ width: seg.percent + '%', background: seg.color }"
          :title="`${seg.label} ${seg.count} 条`"
        ></div>
      </div>
      <div class="stats__legend">
        <span v-for="s in APPLICATION_STATUSES" :key="s.value" class="stats__legend-item">
          <span class="stats__dot" :style="{ background: s.color }"></span>
          {{ s.label }} <b>{{ counts[s.value] }}</b>
        </span>
      </div>
    </div>

    <span v-if="truncated" class="stats__truncated">仅显示最近 500 条</span>
  </div>
</template>

<style scoped>
.stats {
  flex: none;
  display: flex;
  align-items: center;
  gap: 22px;
  background: var(--c-card);
  border: 1px solid var(--c-border);
  border-radius: var(--r-card);
  padding: 10px 16px;
}
.stats__summary {
  flex: none;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.stats__total {
  font-size: 15px;
  font-weight: 700;
  color: var(--c-text);
  line-height: 1.2;
}
.stats__week {
  font-size: 11.5px;
  color: var(--c-text-3);
}
.stats__right {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.stats__bar {
  display: flex;
  height: 6px;
  border-radius: var(--r-bar);
  overflow: hidden;
  background: var(--c-divider);
}
.stats__seg {
  height: 100%;
  transition: width 0.25s ease;
}
.stats__legend {
  display: flex;
  flex-wrap: wrap;
  gap: 2px 14px;
}
.stats__legend-item {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 11.5px;
  color: var(--c-text-2);
}
.stats__legend-item b {
  color: var(--c-text);
}
.stats__dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex: none;
}
.stats__truncated {
  flex: none;
  font-size: 11.5px;
  color: var(--s-interview);
}
</style>
