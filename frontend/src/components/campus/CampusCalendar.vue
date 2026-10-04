<script setup>
/**
 * 站内日历（FR-022）：月视图一次聚合四类事件（宣讲会 / 双选会 / 笔试 / 面试）。
 *
 * 数据按整月下发（`GET /calendar`，接口文档 §3.16），切月即重拉；空月份渲染一句说明，不报错。
 * 点日期 → 下方展开当日清单；点事件 → 活动打开原文（无链接则不动作）、笔试 / 面试跳投递页定位。
 *
 * 颜色：活动取模块色（宣讲会实色 / 双选会浅一档），笔试 / 面试取投递状态色
 * （它们本就是投递事件，系统设计 §4.5.1 的状态色归属投递链路）。
 */
import { computed, onMounted, ref } from 'vue'
import { listCalendar } from '../../api/campus'
import { calendarTypeMeta } from '../../constants/campus'
import { shortDateTime } from '../../utils/datetime'
import { buildMonthGrid, groupByDay, monthRange } from '../../utils/campusCalendar'

const emit = defineEmits(['open-event'])

const cursor = ref(new Date())
const items = ref([])
const loading = ref(false)
const error = ref('')
const selectedDay = ref('') // 点日期后展开的当日清单

const grid = computed(() => buildMonthGrid(cursor.value))
const byDay = computed(() => groupByDay(items.value))
const monthLabel = computed(() => `${cursor.value.getFullYear()} 年 ${cursor.value.getMonth() + 1} 月`)
const todayKey = computed(() => {
  const now = new Date()
  const m = String(now.getMonth() + 1).padStart(2, '0')
  const d = String(now.getDate()).padStart(2, '0')
  return `${now.getFullYear()}-${m}-${d}`
})
const selectedEvents = computed(() => (selectedDay.value ? byDay.value[selectedDay.value] || [] : []))

async function load() {
  loading.value = true
  error.value = ''
  selectedDay.value = ''
  try {
    const { start, end } = monthRange(cursor.value)
    items.value = await listCalendar({ start, end }, { silent: true })
  } catch (e) {
    error.value = e?.message || '日历加载失败'
    items.value = []
  } finally {
    loading.value = false
  }
}

function shiftMonth(delta) {
  cursor.value = new Date(cursor.value.getFullYear(), cursor.value.getMonth() + delta, 1)
  load()
}

function goToday() {
  cursor.value = new Date()
  load()
}

function pickDay(cell) {
  selectedDay.value = selectedDay.value === cell.date ? '' : cell.date
}

/** 事件点击交给父页：活动切到对应 Tab 的列表并定位，笔试 / 面试跳投递页。 */
function openEvent(event) {
  emit('open-event', event)
}

onMounted(load)
</script>

<template>
  <div class="ccal">
    <div class="ccal__bar">
      <div class="ccal__nav">
        <el-button link @click="shiftMonth(-1)">‹ 上月</el-button>
        <span class="ccal__month">{{ monthLabel }}</span>
        <el-button link @click="shiftMonth(1)">下月 ›</el-button>
      </div>
      <el-button size="small" @click="goToday">今天</el-button>
    </div>

    <div v-if="error" class="ccal__error">
      <span>{{ error }}</span>
      <el-button size="small" @click="load">重试</el-button>
    </div>

    <div v-loading="loading" class="ccal__grid">
      <div v-for="week in ['一', '二', '三', '四', '五', '六', '日']" :key="week" class="ccal__weekday">
        周{{ week }}
      </div>
      <div
        v-for="cell in grid"
        :key="cell.date"
        class="ccal__cell"
        :class="{
          'ccal__cell--out': !cell.inMonth,
          'ccal__cell--today': cell.date === todayKey,
          'ccal__cell--picked': cell.date === selectedDay
        }"
        @click="pickDay(cell)"
      >
        <span class="ccal__day">{{ cell.day }}</span>
        <div class="ccal__events">
          <div
            v-for="event in (byDay[cell.date] || []).slice(0, 2)"
            :key="`${event.event_type}-${event.ref_type}-${event.ref_id}`"
            class="ccal__event"
            :title="`${calendarTypeMeta(event.event_type).label} · ${event.title}`"
            @click.stop="openEvent(event)"
          >
            <i class="ccal__dot" :class="calendarTypeMeta(event.event_type).className"></i>
            <span class="ccal__event-text">{{ event.title }}</span>
          </div>
          <span v-if="(byDay[cell.date] || []).length > 2" class="ccal__more">
            +{{ (byDay[cell.date] || []).length - 2 }}
          </span>
        </div>
      </div>
    </div>

    <p v-if="!loading && !items.length && !error" class="ccal__empty">本月暂无安排</p>

    <div v-if="selectedDay" class="ccal__day">
      <h4 class="ccal__day-title">{{ selectedDay }} 的安排</h4>
      <div v-if="selectedEvents.length" class="ccal__day-list">
        <div v-for="event in selectedEvents" :key="`d-${event.event_type}-${event.ref_id}`" class="ccal__day-item">
          <i class="ccal__dot" :class="calendarTypeMeta(event.event_type).className"></i>
          <span class="ccal__day-type">{{ calendarTypeMeta(event.event_type).label }}</span>
          <span class="ccal__day-when">{{ shortDateTime(event.event_at) }}</span>
          <span class="ccal__day-text">{{ event.title }}</span>
          <span v-if="event.company" class="ccal__day-company">{{ event.company }}</span>
          <span v-if="event.location" class="ccal__day-loc">{{ event.location }}</span>
          <el-button
            v-if="event.ref_type === 'campus_event' || event.ref_type === 'application'"
            link
            type="primary"
            class="ccal__day-go"
            @click="openEvent(event)"
          >
            {{ event.ref_type === 'application' ? '去投递页' : '查看信息' }}
          </el-button>
        </div>
      </div>
      <p v-else class="ccal__day-empty">这一天没有安排</p>
    </div>
  </div>
</template>

<style scoped>
.ccal {
  min-height: 420px;
}
.ccal__bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}
.ccal__nav {
  display: flex;
  align-items: center;
  gap: 8px;
}
.ccal__month {
  font-size: var(--fs-title);
  font-weight: 700;
  color: var(--c-text);
  min-width: 110px;
  text-align: center;
}

.ccal__error {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 14px;
  margin-bottom: var(--card-gap);
  background: var(--c-bg);
  border-radius: var(--r-control);
}

.ccal__grid {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  gap: 4px;
  min-height: 320px;
}
.ccal__weekday {
  padding: 4px 0;
  text-align: center;
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}
.ccal__cell {
  min-height: 68px;
  padding: 4px 6px;
  background: var(--c-card);
  border: 1px solid var(--c-border);
  border-radius: var(--r-mark);
  cursor: pointer;
  transition: border-color 0.15s;
  overflow: hidden;
}
.ccal__cell:hover {
  border-color: var(--m-campus);
}
.ccal__cell--out {
  background: var(--c-bg);
  opacity: 0.6;
}
.ccal__cell--today {
  border-color: var(--m-campus);
  box-shadow: inset 0 0 0 1px var(--m-campus);
}
.ccal__cell--picked {
  background: color-mix(in srgb, var(--m-campus) 8%, var(--c-card));
}
.ccal__day {
  font-size: var(--fs-xs);
  color: var(--c-text-2);
  font-variant-numeric: tabular-nums;
}
.ccal__events {
  margin-top: 2px;
  display: grid;
  gap: 2px;
}
.ccal__event {
  display: flex;
  align-items: center;
  gap: 4px;
  cursor: pointer;
}
.ccal__event:hover .ccal__event-text {
  color: var(--m-campus);
}
.ccal__event-text {
  font-size: 12px;
  color: var(--c-text-2);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ccal__dot {
  flex: 0 0 auto;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--c-text-3);
}
/* 四类事件配色：活动取模块色（双选会浅一档），笔试 / 面试取投递状态色 */
.ccal__dot.is-talk {
  background: var(--m-campus);
}
.ccal__dot.is-fair {
  background: color-mix(in srgb, var(--m-campus) 55%, #fff);
}
.ccal__dot.is-exam {
  background: var(--s-written);
}
.ccal__dot.is-interview {
  background: var(--s-interview);
}
.ccal__more {
  font-size: 11px;
  color: var(--c-text-3);
}

.ccal__empty {
  margin: 10px 0 0;
  font-size: var(--fs-sm);
  color: var(--c-text-3);
  text-align: center;
}

.ccal__day {
  margin-top: var(--card-gap);
  padding-top: 10px;
  border-top: 1px solid var(--c-divider);
}
.ccal__day-title {
  margin: 0 0 8px;
  font-size: var(--fs-body);
  font-weight: 600;
  color: var(--c-text);
}
.ccal__day-list {
  display: grid;
  gap: 6px;
}
.ccal__day-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: var(--fs-sm);
  color: var(--c-text-2);
  min-width: 0;
}
.ccal__day-type {
  flex: 0 0 auto;
  color: var(--c-text-3);
  font-size: var(--fs-xs);
}
.ccal__day-when {
  flex: 0 0 auto;
  font-variant-numeric: tabular-nums;
  color: var(--c-text-3);
  font-size: var(--fs-xs);
}
.ccal__day-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ccal__day-company,
.ccal__day-loc {
  flex: 0 0 auto;
  color: var(--c-text-3);
  font-size: var(--fs-xs);
}
.ccal__day-go {
  margin-left: auto;
}
.ccal__day-empty {
  margin: 0;
  font-size: var(--fs-sm);
  color: var(--c-text-3);
}
</style>
