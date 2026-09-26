<script setup>
// 投递看板：5 状态列 + 列间拖拽流转（SRS FR-002 / FR-004）
// 受控展示层：不改父组件数据，拖拽被接受后 emit('transit')，由页面调接口
// 卡片只放关键信息（公司 / 岗位 / 投递天数 / 排期），其余点开卡片看详情
import { reactive, ref, watch } from 'vue'
import draggable from 'vuedraggable'
import {
  APPLICATION_STATUSES,
  CLOSE_REASON_LABELS,
  LEGAL_TRANSITIONS,
  STATUS_COLORS,
  canTransit
} from '../constants/application'
import { shortDateTime } from '../utils/datetime'

const props = defineProps({
  items: { type: Array, default: () => [] }
})
const emit = defineEmits(['edit', 'transit'])

// 拖拽中记录源状态，用于给「放不下」的列加视觉反馈（否则用户拖过去松手只看到弹回，不知为何）
const dragFromStatus = ref(null)

function onDragStart(status) {
  dragFromStatus.value = status
}

function onDragEnd() {
  dragFromStatus.value = null
}

/** 拖拽中：不可放置的列整体变灰（终态列与非法流转目标）；自己的列不提示 */
function isDropBlocked(colStatus) {
  if (!dragFromStatus.value || dragFromStatus.value === colStatus) return false
  return !canTransit(dragFromStatus.value, colStatus)
}

/** 排期标签：按当前状态补上下文，否则用户看不出这串日期是什么
 *  终态（OFFER / CLOSED）返回空串——那时排期已无意义，不再展示 */
function eventLabel(status) {
  if (status === 'INTERVIEW') return '面试'
  if (status === 'APPLIED' || status === 'WRITTEN') return '笔试'
  return ''
}

// 每列一个可变数组，供 draggable 的 v-model 绑定；随 props.items 重建
const groups = reactive({ APPLIED: [], WRITTEN: [], INTERVIEW: [], OFFER: [], CLOSED: [] })

watch(
  () => props.items,
  (list) => {
    APPLICATION_STATUSES.forEach((s) => {
      groups[s.value] = list.filter((item) => item.status === s.value)
    })
  },
  { immediate: true }
)

/** 该列是否允许拖出：仅当存在合法流转目标（如今只剩「已结束」是终态） */
function canPullFrom(status) {
  return (LEGAL_TRANSITIONS[status] || []).length > 0
}

/** 落点预判：读目标列与拖拽卡片各自的 data-status，非法落点直接拖不动
 *  注意：to.el 是 sortablejs 挂载的列表元素（.kanban__list），data-status 必须绑在它身上——
 *  绑到父级 .kanban__col 会取到 undefined，导致 canTransit 恒为 false、所有拖拽被静默拒绝。
 *  closest 为兜底：属性若被渲染到子元素，仍能取到目标列状态。 */
function canDropTo(to, from, dragEl) {
  const toStatus = to.el?.dataset?.status ?? to.el?.closest?.('[data-status]')?.dataset?.status
  const fromStatus = dragEl?.dataset?.status
  return canTransit(fromStatus, toStatus)
}

/** 拖拽完成：卡片只可能在列间移动（列内已用 :sort="false" 禁止）
 *  带上 item 与源状态，由页面弹确认框后再落库（避免误拖即生效、无从挽回） */
function onChange(evt, columnStatus) {
  if (!evt.added) return
  const item = evt.added.element
  if (item && item.status !== columnStatus) {
    emit('transit', { item: { ...item }, status: columnStatus })
  }
}

/** 投递天数：applied_at（YYYY-MM-DD）到今天的自然日差 */
function daysSince(appliedAt) {
  if (!appliedAt) return 0
  const [y, m, d] = appliedAt.split('-').map(Number)
  const start = new Date(y, m - 1, d)
  const now = new Date()
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  return Math.max(0, Math.round((today - start) / 86400000))
}

/** 下次笔试/面试时间：2026-09-26 14:00:00 → 09-26 14:00 */
/** 距今天 ≤3 天的排期：琥珀加粗提示（设计文档 §4.5.4：强调须稀缺，故不铺底色） */
function isUrgent(value) {
  if (!value) return false
  const [y, m, d] = value.slice(0, 10).split('-').map(Number)
  const target = new Date(y, m - 1, d)
  const now = new Date()
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const diff = Math.round((target - today) / 86400000)
  return diff >= 0 && diff <= 3
}
</script>

<template>
  <div class="kanban">
    <div
      v-for="col in APPLICATION_STATUSES"
      :key="col.value"
      class="kanban__col"
      :class="{ 'kanban__col--drop-blocked': isDropBlocked(col.value) }"
      :data-status="col.value"
    >
      <div class="kanban__head">
        <span class="kanban__dot" :style="{ background: col.color }"></span>
        <span class="kanban__title">{{ col.label }}</span>
        <span class="kanban__count">{{ groups[col.value].length }}</span>
      </div>

      <draggable
        v-model="groups[col.value]"
        item-key="id"
        class="kanban__list"
        :class="{ 'kanban__list--empty': groups[col.value].length === 0 }"
        :data-status="col.value"
        :sort="false"
        :group="{
          name: 'applications',
          pull: canPullFrom(col.value),
          put: canDropTo
        }"
        @change="(evt) => onChange(evt, col.value)"
        @start="onDragStart(col.value)"
        @end="onDragEnd"
      >
        <template #item="{ element }">
          <div
            class="kanban-card"
            :data-status="element.status"
            :style="{ borderLeftColor: STATUS_COLORS[element.status] }"
            @click="emit('edit', element)"
          >
            <div class="kanban-card__company">{{ element.company }}</div>
            <div class="kanban-card__position">{{ element.position }}</div>

            <div class="kanban-card__foot">
              <span class="kanban-card__days">投递 {{ daysSince(element.applied_at) }} 天</span>
              <span
                v-if="element.close_reason"
                class="kanban-card__reason"
                :title="`结束原因：${CLOSE_REASON_LABELS[element.close_reason]}`"
              >
                {{ CLOSE_REASON_LABELS[element.close_reason] }}
              </span>
              <span
                v-if="element.next_event_at && eventLabel(element.status)"
                class="kanban-card__event"
                :class="{ 'kanban-card__event--urgent': isUrgent(element.next_event_at) }"
                :title="`下次${eventLabel(element.status)}：${element.next_event_at}`"
              >
                {{ eventLabel(element.status) }} {{ shortDateTime(element.next_event_at) }}
              </span>
            </div>
          </div>
        </template>
      </draggable>
    </div>
  </div>
</template>

<style scoped>
.kanban {
  display: flex;
  gap: var(--card-gap);
  height: 100%;
  min-height: 0;
  /* 列被压到 min-width 以下时改为横向滚动，而不是把卡片内容挤成竖排 */
  overflow-x: auto;
}
.kanban__col {
  flex: 1 1 0;
  /* 168px 是卡片内容不被迫换行的下限：卡片可用宽 = 列宽 − 47（列/卡片内边距与边框） */
  min-width: 168px;
  min-height: 0;
  display: flex;
  flex-direction: column;
  border: 1px solid var(--c-border);
  border-radius: var(--r-card);
  padding: 10px;
}
.kanban__head {
  flex: none;
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 8px;
  padding: 0 2px;
}
/* 拖拽中：放不下的列整体变灰并转虚线，明确回答「为什么拖不过去」 */
.kanban__col--drop-blocked {
  opacity: 0.45;
  border-style: dashed;
}
.kanban__col--drop-blocked .kanban-card {
  pointer-events: none;
}
.kanban__dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex: none;
}
.kanban__title {
  font-size: var(--fs-sm);
  font-weight: 600;
  color: var(--c-text-2);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.kanban__count {
  margin-left: auto;
  font-size: var(--fs-xs);
  color: var(--c-text-3);
  flex: none;
}
.kanban__list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding-right: 2px;
}
/* 细滚动条：默认系统滚动条在小列宽里过于抢眼 */
.kanban__list::-webkit-scrollbar {
  width: 6px;
}
.kanban__list::-webkit-scrollbar-track {
  background: transparent;
}
.kanban__list::-webkit-scrollbar-thumb {
  background: var(--c-border);
  border-radius: 3px;
}
.kanban__list::-webkit-scrollbar-thumb:hover {
  background: var(--c-text-3);
}
/* 空列：虚线即拖拽落点区域本身（伪元素承载文字，不产生可拖拽节点） */
.kanban__list--empty {
  border: 1px dashed var(--c-border);
  border-radius: var(--r-control);
  align-items: center;
  justify-content: center;
}
.kanban__list--empty::before {
  content: '拖入卡片';
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}
.kanban-card {
  position: relative;
  background: var(--c-card);
  border: 1px solid var(--c-border);
  border-left: 3px solid var(--m-application);
  border-radius: var(--r-control);
  padding: 9px 11px;
  cursor: pointer;
  flex: none;
  transition: box-shadow 0.15s ease;
}
.kanban-card:hover {
  box-shadow: 0 2px 8px rgba(122, 107, 196, 0.13);
}
.kanban-card__company {
  font-size: var(--fs-body);
  font-weight: 600;
  color: var(--c-text);
  line-height: 1.35;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.kanban-card__position {
  margin-top: 2px;
  font-size: var(--fs-xs);
  color: var(--c-text-2);
  line-height: 1.35;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.kanban-card__foot {
  margin-top: 7px;
  display: flex;
  align-items: center;
  gap: 4px 8px;
  /* 窄列时允许折行：排期带标签后更长，宁可换行也不截断 */
  flex-wrap: wrap;
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}
/* nowrap + flex:none：否则列宽偏窄时会被 flex 压到一个字宽，中文逐字竖排 */
.kanban-card__days {
  flex: none;
  white-space: nowrap;
  font-weight: 600;
  color: var(--c-text-2);
}
.kanban-card__event {
  margin-left: auto;
  flex: none;
  /* 排期是要看的信息，不能用最弱一级文字色（原 --c-text-3 过浅） */
  color: var(--c-text-2);
}
.kanban-card__event--urgent {
  color: var(--s-interview);
  font-weight: 700;
}
/* 结束原因是终态记录的唯一分类信息，用最浅一级标记承载（分类非警示，不铺强调色） */
.kanban-card__reason {
  margin-left: auto;
  flex: none;
  padding: 1px 6px;
  border-radius: var(--r-mark);
  background: var(--c-divider);
  color: var(--c-text-2);
  font-size: var(--fs-xs);
}
</style>
