<script setup>
/**
 * 岗位列表：类型标签 · 公司 · 标题 + 元数据（城市 / 学历 / 专业 / 薪资 / 截止 / 匹配度 / 来源学校）
 * + 「已变更」「已过期」状态角标 + 「已投递」弱化 + 三操作（查看原文 / 加入投递 / 分析匹配度）。
 *
 * 已投递取**弱化**不重排（系统设计 §4.8 允许「沉底或弱化」二选一：服务端排序不该被前端打乱）。
 * 删除仅对投喂项开放（自动抓取的公共岗位不可删，后端 10001）。
 */
import { JOB_TYPE_META, ingestSourceLabel } from '../../constants/campus'
import { shortDateTime, datePart } from '../../utils/datetime'
import AppEmpty from '../AppEmpty.vue'

defineProps({
  items: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  emptyText: { type: String, default: '还没有聚合到岗位' }
})
const emit = defineEmits(['open-url', 'apply', 'analyze', 'remove'])
</script>

<template>
  <AppEmpty
    v-if="!loading && !items.length"
    type="campus"
    :description="emptyText"
    style="--empty-color: var(--m-campus)"
  />
  <ul v-else v-loading="loading" class="cjob">
    <li
      v-for="item in items"
      :key="item.id"
      class="cjob__item"
      :class="{ 'cjob__item--applied': item.is_applied, 'cjob__item--muted': item.status === 'EXPIRED' }"
    >
      <div class="cjob__main">
        <div class="cjob__line">
          <el-tag v-if="JOB_TYPE_META[item.job_type]" size="small" effect="plain" class="cjob__type">
            {{ JOB_TYPE_META[item.job_type].label }}
          </el-tag>
          <span class="cjob__title">{{ item.company }} · {{ item.title }}</span>
          <el-tag v-if="item.status === 'CHANGED'" size="small" type="warning" effect="plain">已变更</el-tag>
          <el-tag v-if="item.is_applied" size="small" type="success" effect="plain">已投递</el-tag>
        </div>
        <div class="cjob__meta">
          <span v-if="item.city">{{ item.city }}</span>
          <span v-if="item.edu_req">{{ item.edu_req }}</span>
          <span v-if="item.major_req" class="cjob__major" :title="item.major_req">专业：{{ item.major_req }}</span>
          <span v-if="item.salary_text">{{ item.salary_text }}</span>
          <span v-if="item.deadline" class="cjob__deadline">{{ datePart(item.deadline) }} 截止</span>
          <span v-if="item.match_score > 0" class="cjob__score">匹配度 {{ item.match_score }}</span>
          <span v-if="item.ingest_source === 'FEED'" class="cjob__feed">{{ ingestSourceLabel(item.ingest_source) }}</span>
          <el-tag
            v-if="item.source_site"
            size="small"
            type="info"
            effect="plain"
            :title="item.source_site"
          >
            {{ item.source_site }}
          </el-tag>
          <span v-if="item.status === 'EXPIRED'" class="cjob__expired">已过期</span>
        </div>
        <div class="cjob__actions">
          <el-button link type="primary" :disabled="!item.source_url" @click.stop="emit('open-url', item.source_url)">
            查看原文
          </el-button>
          <el-button link type="primary" @click.stop="emit('apply', item)">加入投递</el-button>
          <el-button link type="primary" @click.stop="emit('analyze', item)">分析匹配度</el-button>
          <el-button
            v-if="item.ingest_source === 'FEED'"
            link
            class="cjob__remove"
            @click.stop="emit('remove', item)"
          >
            删除
          </el-button>
          <span v-if="item.first_seen_at" class="cjob__seen">{{ shortDateTime(item.first_seen_at) }} 入库</span>
        </div>
      </div>
    </li>
  </ul>
</template>

<style scoped>
.cjob {
  display: grid;
  gap: 8px;
  margin: 0;
  padding: 0;
  list-style: none;
  min-height: 60px;
}
.cjob__item {
  padding: 12px 14px;
  border: 1px solid var(--c-border);
  border-radius: var(--r-control);
  transition: border-color 0.15s;
}
.cjob__item:hover {
  border-color: var(--m-campus);
}
/* 已投递：使命已完成——弱化不干预排序（§4.8 第 4 条） */
.cjob__item--applied {
  opacity: 0.62;
}
/* 已过期：灰化 */
.cjob__item--muted {
  opacity: 0.5;
}
.cjob__main {
  min-width: 0;
}
.cjob__line {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.cjob__type {
  flex: 0 0 auto;
}
.cjob__title {
  font-size: var(--fs-body);
  color: var(--c-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.cjob__meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 6px;
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}
.cjob__major {
  max-width: 240px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.cjob__deadline {
  font-variant-numeric: tabular-nums;
}
.cjob__score {
  padding: 1px 6px;
  color: var(--m-campus);
  background: color-mix(in srgb, var(--m-campus) 12%, var(--c-card));
  border-radius: var(--r-mark);
}
.cjob__feed {
  padding: 1px 6px;
  background: var(--c-bg);
  border-radius: var(--r-mark);
}
.cjob__expired {
  padding: 1px 6px;
  background: var(--c-bg);
  border-radius: var(--r-mark);
}
.cjob__actions {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-top: 8px;
}
.cjob__remove.el-button {
  color: var(--c-text-3);
}
.cjob__remove.el-button:hover {
  color: var(--el-color-danger);
}
.cjob__seen {
  margin-left: auto;
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}
</style>
