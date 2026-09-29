<script setup>
/**
 * 错题列表：状态筛选 + 条目（题干 / 领域 / 档位 / 到期标记）+ 分页 + 删除入口。
 *
 * 排序由后端给（未掌握优先 → 到期先后 → id），本组件不再排。
 */
import { computed } from 'vue'
import { Delete } from '@element-plus/icons-vue'
import { QTYPE_LABELS, directionLabelMap } from '../../utils/practiceMeta'
import { dueText } from '../../utils/reviewPlan'
import AppEmpty from '../AppEmpty.vue'

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
</script>

<template>
  <section class="wrong">
    <header class="wrong__head">
      <h3 class="wrong__title dot-title">错题本</h3>
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

    <AppEmpty
      v-if="!loading && !items.length"
      type="wrong"
      :description="emptyText"
      style="--empty-color: var(--m-wrong)"
    />

    <template v-else>
      <ul v-loading="loading" class="wrong__list">
        <li v-for="item in items" :key="item.id" class="wrong__item" @click="emit('open', item)">
          <div class="wrong__main">
            <span class="wrong__content">{{ item.content }}</span>
            <div class="wrong__meta">
              <span class="wrong__dir">{{ directionLabels[item.direction] || item.direction }}</span>
              <span class="wrong__qtype">{{ QTYPE_LABELS[item.qtype] || item.qtype }}</span>
              <span v-if="item.mastered_at" class="wrong__mastered">已掌握</span>
              <span v-else-if="isDue(item)" class="wrong__due">{{ dueText(item.next_review_at) }}</span>
              <span v-else class="wrong__later">{{ dueText(item.next_review_at) }}</span>
            </div>
          </div>
          <span class="wrong__arrow">›</span>
          <el-button
            link
            class="wrong__remove"
            title="从错题本移除"
            :icon="Delete"
            @click.stop="emit('remove', item)"
          />
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
  /* 32px 高：点击热区达惯例下限（原 28px） */
  padding: 7px 14px;
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
/* 题型：中性浅底标签——类型是中性信息，不抢到期标记的模块色 */
.wrong__qtype {
  padding: 1px 6px;
  background: var(--c-bg);
  border-radius: var(--r-mark);
}
/* 进入提示：常驻低对比度，hover 随条目变模块色 */
.wrong__arrow {
  flex: 0 0 auto;
  font-size: 18px;
  line-height: 1;
  color: var(--c-text-3);
  transition: color 0.15s;
}
.wrong__item:hover .wrong__arrow {
  color: var(--m-wrong);
}
/* 删除：常驻图标、低对比度，hover 才显危险色（常驻可见是底线，只是不以文字抢注意力） */
.wrong__remove.el-button {
  flex: 0 0 auto;
  color: var(--c-text-3);
}
.wrong__remove.el-button:hover {
  color: var(--el-color-danger);
}

.wrong__pager {
  justify-content: flex-end;
  margin-top: var(--card-gap);
}
</style>
