<script setup>
/**
 * 宣讲会 / 双选会列表（同一组件，`info_type` 由父页决定）：时间 · 公司 · 标题 + 元数据组
 * （地点 / 需求专业 / 匹配度 / 来源学校标签）+ 「已变更」角标、过期灰化。
 *
 * 数据与分页由父页持有（照 WrongList 的分工），本组件只展示与发事件。
 */
import { campusEventStatus, sourceSiteBrief } from '../../constants/campus'
import { shortDateTime } from '../../utils/datetime'
import AppEmpty from '../AppEmpty.vue'

defineProps({
  items: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  emptyText: { type: String, default: '还没有聚合到信息' }
})
const emit = defineEmits(['open-url'])

/** 有原文链接才可点开——无链接的条目是静态行（与原「查看原文」操作同判据）。 */
function openItem(item) {
  if (item.source_url) emit('open-url', item.source_url)
}
</script>

<template>
  <AppEmpty
    v-if="!loading && !items.length"
    type="campus"
    :description="emptyText"
    style="--empty-color: var(--m-campus)"
  />
  <ul v-else v-loading="loading" class="cev">
    <li
      v-for="item in items"
      :key="item.id"
      class="cev__item"
      :class="{
        'cev__item--muted': campusEventStatus(item.status).muted,
        'cev__item--link': !!item.source_url
      }"
      :title="item.source_url ? '查看原文' : '该条目没有原文链接'"
      @click="openItem(item)"
    >
      <div class="cev__main">
        <div class="cev__line">
          <span class="cev__when">{{ shortDateTime(item.event_date) }}</span>
          <span class="cev__title">
            {{ item.company ? `${item.company} · ` : '' }}{{ item.title }}
          </span>
          <el-tag v-if="campusEventStatus(item.status).changed" size="small" type="warning" effect="plain">
            已变更
          </el-tag>
        </div>
        <div class="cev__meta">
          <span v-if="item.location">{{ item.location }}</span>
          <span v-if="item.major_req" class="cev__major" :title="item.major_req">
            专业：{{ item.major_req }}
          </span>
          <span v-if="item.match_score > 0" class="cev__score">匹配度 {{ item.match_score }}</span>
          <el-tag
            v-if="sourceSiteBrief(item.source_site)"
            size="small"
            type="info"
            effect="plain"
            :title="item.source_site"
          >
            {{ sourceSiteBrief(item.source_site) }}
          </el-tag>
          <span v-if="item.status === 'EXPIRED'" class="cev__expired">已过期</span>
        </div>
      </div>
      <span v-if="item.source_url" class="cev__arrow">›</span>
    </li>
  </ul>
</template>

<style scoped>
.cev {
  display: grid;
  gap: 8px;
  margin: 0;
  padding: 0;
  list-style: none;
  min-height: 60px;
}
.cev__item {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 12px 14px;
  border: 1px solid var(--c-border);
  border-radius: var(--r-control);
  transition: border-color 0.15s;
}
.cev__item--link {
  cursor: pointer;
}
.cev__item--link:hover {
  border-color: var(--m-campus);
}
/* 过期灰化（系统设计 §4.8 第 3 条：状态不复用投递色，用角标 / 灰化表达） */
.cev__item--muted {
  opacity: 0.55;
}
.cev__main {
  flex: 1;
  min-width: 0;
}
.cev__line {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.cev__when {
  flex: 0 0 auto;
  font-size: var(--fs-sm);
  color: var(--c-text-2);
  font-variant-numeric: tabular-nums;
}
.cev__title {
  font-size: var(--fs-body);
  color: var(--c-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.cev__meta {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 6px;
  font-size: var(--fs-xs);
  color: var(--c-text-3);
  min-width: 0;
}
.cev__major {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 240px;
}
.cev__score {
  padding: 1px 6px;
  color: var(--m-campus);
  background: color-mix(in srgb, var(--m-campus) 12%, var(--c-card));
  border-radius: var(--r-mark);
}
.cev__expired {
  padding: 1px 6px;
  background: var(--c-bg);
  border-radius: var(--r-mark);
}
.cev__arrow {
  flex: 0 0 auto;
  font-size: 18px;
  line-height: 1.4;
  color: var(--c-text-3);
  transition: color 0.15s;
}
.cev__item:hover .cev__arrow {
  color: var(--m-campus);
}
</style>
