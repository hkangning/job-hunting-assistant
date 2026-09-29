<script setup>
/**
 * 错题列表：状态筛选 + 条目（题干 / 领域 / 档位 / 到期标记）+ 分页 + 删除入口。
 *
 * 排序由后端给（未掌握优先 → 到期先后 → id），本组件不再排。
 */
import { computed } from 'vue'
import { directionLabelMap } from '../../utils/practiceMeta'

const props = defineProps({
  items: { type: Array, default: () => [] },
  total: { type: Number, default: 0 },
  page: { type: Number, default: 1 },
  pageSize: { type: Number, default: 10 },
  status: { type: String, default: '' },
  loading: { type: Boolean, default: false },
  meta: { type: Object, default: null },
  emptyText: { type: String, default: '错题本还是空的' }
})
const emit = defineEmits(['open', 'remove', 'page-change', 'status-change'])

const STATUS_OPTIONS = [
  { value: '', label: '全部' },
  { value: 'PENDING', label: '待复习' },
  { value: 'MASTERED', label: '已掌握' }
]

/** 领域中文名：取自 meta 的栈 → 领域映射（与陪练页同一份元数据）。 */
const directionLabels = computed(() => directionLabelMap(props.meta))

/**
 * 后端给的是 `YYYY-MM-DD HH:mm:ss`，先转成各浏览器都能解析的形态再比。
 */
function toDate(text) {
  return new Date(String(text || '').replace(/-/g, '/'))
}

/** 已到期 = `next_review_at <= 现在` **且**未掌握——已掌握的条目不标（其 next_review_at 不再更新）。 */
function isDue(item) {
  return !item.mastered_at && toDate(item.next_review_at) <= new Date()
}

function dueLabel(item) {
  if (item.mastered_at) return ''
  const days = Math.ceil((toDate(item.next_review_at) - Date.now()) / 86400000)
  return days <= 0 ? '已到期' : `${days} 天后`
}
</script>

<template>
  <section class="wrong">
    <header class="wrong__head">
      <h3 class="wrong__title">错题本</h3>
      <div class="seg">
        <button
          v-for="opt in STATUS_OPTIONS"
          :key="opt.value"
          type="button"
          class="seg__item"
          :class="{ 'seg__item--on': status === opt.value }"
          @click="emit('status-change', opt.value)"
        >
          {{ opt.label }}
        </button>
      </div>
    </header>

    <el-empty v-if="!loading && !items.length" :description="emptyText" />

    <template v-else>
      <ul v-loading="loading" class="wrong__list">
        <li v-for="item in items" :key="item.id" class="wrong__item" @click="emit('open', item)">
          <div class="wrong__main">
            <span class="wrong__content">{{ item.content }}</span>
            <div class="wrong__meta">
              <span class="wrong__dir">{{ directionLabels[item.direction] || item.direction }}</span>
              <span class="wrong__stage">
                <template v-if="item.mastered_at">四档已走完</template>
                <template v-else>第 {{ item.review_stage }} 档</template>
              </span>
              <span v-if="isDue(item)" class="wrong__due">{{ dueLabel(item) }}</span>
              <span v-else-if="dueLabel(item)" class="wrong__later">{{ dueLabel(item) }}</span>
              <span v-if="item.mastered_at" class="wrong__mastered">已掌握</span>
            </div>
          </div>
          <el-button
            link
            class="wrong__remove"
            title="从错题本移除"
            @click.stop="emit('remove', item)"
          >
            删除
          </el-button>
        </li>
      </ul>

      <el-pagination
        v-if="total > pageSize"
        class="wrong__pager"
        layout="prev, pager, next"
        :current-page="page"
        :page-size="pageSize"
        :total="total"
        @current-change="emit('page-change', $event)"
      />
    </template>
  </section>
</template>

<style scoped>
.wrong {
  background: var(--c-card);
  border: 1px solid var(--c-border);
  border-radius: var(--r-card);
  box-shadow: 0 1px 2px rgba(42, 39, 64, 0.05);
  padding: var(--card-padding);
}

.wrong__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: var(--card-gap);
}
.wrong__title {
  margin: 0;
  font-size: var(--fs-title);
  font-weight: 700;
  color: var(--c-text);
}

/* 分段控件：与准备台同一形态（选中态实底） */
.seg {
  display: flex;
  gap: 4px;
  padding: 3px;
  background: var(--c-bg);
  border-radius: var(--r-control);
}
.seg__item {
  padding: 5px 12px;
  font: inherit;
  font-size: var(--fs-sm);
  color: var(--c-text-2);
  background: transparent;
  border: 0;
  border-radius: var(--r-mark);
  cursor: pointer;
}
.seg__item--on {
  color: var(--c-text);
  background: var(--c-card);
  font-weight: 600;
}

.wrong__list {
  display: grid;
  gap: 8px;
  margin: 0;
  padding: 0;
  list-style: none;
  min-height: 60px;
}
.wrong__item {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 12px 14px;
  border: 1px solid var(--c-border);
  border-radius: var(--r-control);
  cursor: pointer;
  transition: border-color 0.15s;
}
.wrong__item:hover {
  border-color: var(--m-wrong);
}
.wrong__main {
  flex: 1;
  min-width: 0;
}
.wrong__content {
  display: block;
  font-size: var(--fs-body);
  line-height: 1.6;
  color: var(--c-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.wrong__meta {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 6px;
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}
/* 到期用模块色（错题本＝--m-wrong），未到期保持弱化 */
.wrong__due {
  padding: 1px 6px;
  color: var(--m-wrong);
  background: color-mix(in srgb, var(--m-wrong) 12%, var(--c-card));
  border-radius: var(--r-mark);
}
.wrong__mastered {
  padding: 1px 6px;
  color: var(--m-practice);
  background: color-mix(in srgb, var(--m-practice) 12%, var(--c-card));
  border-radius: var(--r-mark);
}
.wrong__remove {
  flex: 0 0 auto;
}

.wrong__pager {
  justify-content: flex-end;
  margin-top: var(--card-gap);
}
</style>
