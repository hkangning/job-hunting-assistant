<script setup>
/**
 * 领域掌握度可视化：按技术栈分组，逐领域一条掌握度进度条。
 *
 * 只含有练习记录的领域（全无记录则不出现在 `groups` 中）；掌握度低的领域标红，
 * 与抽题的「薄弱优先」呼应——它同时也是「练什么」的决策依据。
 */
import { shortDateTime } from '../../utils/datetime'
import AppEmpty from '../AppEmpty.vue'

defineProps({
  groups: { type: Array, default: () => [] },
  /** 首屏加载中不显示「还没有掌握度数据」假空态（步骤 27） */
  loading: { type: Boolean, default: false }
})
</script>

<template>
  <section class="mastery__card">
    <h3 class="mastery__title dot-title">各领域掌握度</h3>
    <AppEmpty
      v-if="!loading && !groups.length"
      type="chart"
      size="sm"
      title="还没有掌握度数据"
      description="练过之后这里会显示各领域掌握度"
      style="--empty-color: var(--m-practice)"
    />

    <div v-for="group in groups" :key="group.stack" class="mastery__group">
      <div class="mastery__group-head">
        <span class="mastery__group-name">{{ group.label }}</span>
        <span class="mastery__group-average">平均 {{ group.average }}</span>
      </div>
      <div
        v-for="domain in group.domains"
        :key="domain.direction"
        class="mastery__domain"
        :class="{ 'mastery__domain--weak': domain.mastery < 60 }"
        :title="
          domain.last_practiced_at
            ? `最近练习 ${shortDateTime(domain.last_practiced_at)}`
            : '还没练过'
        "
      >
        <span class="mastery__domain-name">{{ domain.label }}</span>
        <span class="mastery__bar"><i :style="{ width: `${domain.mastery}%` }" /></span>
        <span class="mastery__domain-value">{{ domain.mastery }}</span>
        <span class="mastery__domain-meta">练过 {{ domain.covered_count }} 题</span>
      </div>
    </div>
  </section>
</template>

<style scoped>
/* 辅助卡＝线框卡（透明底、无阴影）：与白色主卡形成「虚 / 实」两层 */
.mastery__card {
  background: transparent;
  border: 1px solid var(--c-border);
  border-radius: var(--r-card);
  padding: var(--card-padding);
}

.mastery__title {
  margin: 0 0 12px;
  font-size: var(--fs-title);
  font-weight: 700;
  color: var(--c-text);
}

.mastery__group + .mastery__group {
  margin-top: 14px;
}
.mastery__group-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}
.mastery__group-name {
  font-size: var(--fs-body);
  font-weight: 600;
  color: var(--c-text);
}
.mastery__group-average {
  font-size: var(--fs-sm);
  color: var(--c-text-2);
}

.mastery__domain {
  display: grid;
  grid-template-columns: 96px 1fr 32px auto;
  align-items: center;
  gap: 8px;
  padding: 3px 0;
  font-size: var(--fs-sm);
  color: var(--c-text-2);
}
.mastery__domain-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.mastery__bar {
  display: block;
  height: 8px;
  background: var(--c-divider);
  border-radius: var(--r-bar);
  overflow: hidden;
}
.mastery__bar i {
  display: block;
  height: 100%;
  background: var(--m-practice);
}
.mastery__domain--weak .mastery__bar i {
  background: var(--m-wrong);
}
.mastery__domain-value {
  text-align: right;
  font-variant-numeric: tabular-nums;
  color: var(--c-text);
}
.mastery__domain-meta {
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}
</style>
