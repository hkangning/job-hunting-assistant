<script setup>
/**
 * 训练历史：题干预览、模式、状态、综合分、轮数、时间；RUNNING 的会话可就地结算
 * （接口文档 v1.26 §3.8：RUNNING 与 FINISHED 均可调 finish，按当前进度结算）。
 */
import { computed } from 'vue'
import { shortDateTime } from '../../utils/datetime'

const props = defineProps({
  items: { type: Array, default: () => [] },
  total: { type: Number, default: 0 },
  page: { type: Number, default: 1 },
  pageSize: { type: Number, default: 10 },
  modeFilter: { type: String, default: '' },
  meta: { type: Object, default: null }
})
const emit = defineEmits(['open', 'resume', 'page-change', 'mode-change'])

/** 未练完的点进去就是接着练，已完成的点进去是回看——按状态决定，不必让用户先分辨。 */
function handleClick(item) {
  if (item.status === 'RUNNING') emit('resume', item)
  else emit('open', item)
}

const modeOptions = computed(() => props.meta?.modes || [])
const modeLabel = (value) => modeOptions.value.find((m) => m.value === value)?.label || value
const pageCount = computed(() => Math.max(1, Math.ceil(props.total / props.pageSize)))
</script>

<template>
  <section class="history__card">
    <header class="history__head">
      <h3 class="history__title">训练记录</h3>
      <el-select
        :model-value="modeFilter"
        size="small"
        clearable
        placeholder="全部模式"
        class="history__filter"
        @update:model-value="emit('mode-change', $event || '')"
      >
        <el-option
          v-for="mode in modeOptions"
          :key="mode.value"
          :label="mode.label"
          :value="mode.value"
        />
      </el-select>
    </header>

    <el-empty v-if="!items.length" description="还没有训练记录" :image-size="60" />

    <ul v-else class="history__list">
      <li v-for="item in items" :key="item.id" class="history__item" @click="handleClick(item)">
        <span class="history__question">{{ item.question_content }}</span>
        <div class="history__meta">
          <span class="history__mode">{{ modeLabel(item.mode) }}</span>
          <span v-if="item.status === 'RUNNING'" class="history__state history__state--running">进行中</span>
          <span v-else-if="item.passed" class="history__state history__state--pass">通过</span>
          <span v-else class="history__state history__state--fail">未通过</span>
          <div class="history__right">
            <el-button
              v-if="item.status === 'RUNNING'"
              type="primary"
              plain
              size="small"
              @click.stop="emit('resume', item)"
            >
              继续作答
            </el-button>
            <template v-else>
              <span class="history__score">{{ item.overall_score ?? '—' }}<i>分</i></span>
              <span class="history__time">{{ shortDateTime(item.started_at) }}</span>
            </template>
          </div>
        </div>
      </li>
    </ul>

    <div v-if="total > pageSize" class="history__pager">
      <el-button size="small" :disabled="page === 1" @click="emit('page-change', page - 1)">
        上一页
      </el-button>
      <span class="history__pager-text">{{ page }} / {{ pageCount }}</span>
      <el-button size="small" :disabled="page >= pageCount" @click="emit('page-change', page + 1)">
        下一页
      </el-button>
    </div>
  </section>
</template>

<style scoped>
.history__card {
  background: var(--c-card);
  border: 1px solid var(--c-border);
  border-radius: var(--r-card);
  box-shadow: 0 1px 2px rgba(42, 39, 64, 0.05);
  padding: var(--card-padding);
}

.history__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 8px;
}
.history__title {
  margin: 0;
  font-size: var(--fs-title);
  font-weight: 700;
  color: var(--c-text);
}
.history__filter {
  width: 110px;
}

.history__list {
  margin: 0;
  padding: 0;
  list-style: none;
}
.history__item {
  padding: 9px 10px;
  border-radius: var(--r-control);
  cursor: pointer;
  transition: background 0.15s;
}
.history__item:hover {
  background: var(--c-bg);
}

.history__question {
  display: block;
  overflow: hidden;
  font-size: var(--fs-sm);
  color: var(--c-text);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.history__meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 6px;
}
.history__mode {
  padding: 1px 7px;
  font-size: var(--fs-xs);
  color: var(--c-text-2);
  background: var(--c-bg);
  border-radius: var(--r-mark);
}
.history__state {
  font-size: var(--fs-xs);
}
.history__state--running {
  color: var(--s-interview);
}
.history__state--pass {
  color: var(--s-offer);
}
.history__state--fail {
  color: var(--m-wrong);
}
.history__right {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-left: auto;
}
.history__score {
  font-size: var(--fs-body);
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  color: var(--c-text);
}
.history__score i {
  margin-left: 1px;
  font-size: var(--fs-xs);
  font-style: normal;
  font-weight: 400;
  color: var(--c-text-3);
}
.history__time {
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}

.history__pager {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  margin-top: 10px;
}
.history__pager-text {
  font-size: var(--fs-xs);
  color: var(--c-text-2);
}
</style>
