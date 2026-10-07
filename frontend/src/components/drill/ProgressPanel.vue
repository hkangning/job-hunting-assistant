<script setup>
/**
 * 跨次进步对比（FR-020 / 接口文档 §3.15 `GET /drills/{id}/progress`）。
 *
 * 三块内容：
 * - **Delta 卡**：`deltas` 口径是「最近一次 vs 上一次」，固定给四项（得分 / 时长 / 填充词 / 停顿）
 *   ——这三项以上正是 AC-13 要求的对比维度；
 * - **指标切换**：一次只看一个指标（SRS 对跨次对比的界面要求），切换只影响折线；
 * - **趋势折线**：`items` 按遍次升序取点；某遍缺该指标时**跳过该点并标注**，
 *   而不是补 0（补 0 会把曲线拽下去，看趋势反而失真）。
 *
 * 练满 2 遍才有 `deltas`；不足时给「再练一遍」的引导，不画空图。
 */
import { computed, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import * as echarts from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { METRICS, deltaTone, formatDelta, metricValue, trendSeries } from '../../utils/drillMeta'

echarts.use([LineChart, GridComponent, TooltipComponent, CanvasRenderer])

const props = defineProps({
  /** `{ attempt_count, items, deltas }`；未加载完为 null。 */
  progress: { type: Object, default: null }
})

/** Delta 卡固定展示的四项（AC-13 要求「填充词、时长、停顿次数至少三项」）。 */
const DELTA_KEYS = ['score', 'duration_ms', 'filler_count', 'pause_count']

const chartEl = ref(null)
const chart = shallowRef(null)
const activeKey = ref('score')

const items = computed(() => props.progress?.items || [])
const hasCompare = computed(() => items.value.length >= 2 && !!props.progress?.deltas)

/** 最近两条记录（Delta 卡的 from / to）。 */
const pair = computed(() => {
  const list = items.value
  return list.length >= 2 ? [list[list.length - 2], list[list.length - 1]] : null
})

/** 有数据的指标才可切换（比如全程文字作答时表达指标全空）。 */
const availableKeys = computed(() =>
  METRICS.filter((m) => items.value.some((it) => it[m.key] != null)).map((m) => m.key)
)

const series = computed(() => trendSeries(items.value, activeKey.value))
const activeMetric = computed(() => METRICS.find((m) => m.key === activeKey.value))

/** 读取设计 token 实值（ECharts 画在 canvas 上读不到 CSS 变量）。 */
function token(name, fallback) {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name)
  return value.trim() || fallback
}

function buildOption() {
  const border = token('--c-border', '#CFCBDD')
  const divider = token('--c-divider', '#EAE8F2')
  const textMuted = token('--c-text-3', '#A5A0BC')
  const moduleColor = token('--m-drill', '#6C7BC9')
  return {
    grid: { left: 48, right: 20, top: 18, bottom: 28 },
    tooltip: {
      trigger: 'axis',
      formatter: (params) => {
        const p = params[0]
        return `第 ${p.name} 遍<br/>${activeMetric.value?.label}：${metricValue(activeKey.value, p.value)}`
      }
    },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: series.value.points.map((p) => String(p.seq)),
      axisLine: { lineStyle: { color: border } },
      axisLabel: { color: textMuted, fontSize: 11, formatter: (v) => `第${v}遍` }
    },
    yAxis: {
      type: 'value',
      splitLine: { lineStyle: { color: divider } },
      axisLabel: {
        color: textMuted,
        fontSize: 11,
        formatter: (value) =>
          activeMetric.value?.format === 'duration' ? `${Math.round(value / 1000)}s` : value
      }
    },
    series: [
      {
        name: activeMetric.value?.label,
        type: 'line',
        smooth: false,
        symbolSize: 8,
        data: series.value.points.map((p) => p.value),
        lineStyle: { color: moduleColor, width: 2 },
        itemStyle: { color: moduleColor },
        label: {
          show: true,
          color: token('--c-text-2', '#7A7590'),
          fontSize: 11,
          formatter: (p) => metricValue(activeKey.value, p.value)
        }
      }
    ]
  }
}

function render() {
  if (!chart.value) return
  chart.value.setOption(buildOption(), true)
}

function resize() {
  chart.value?.resize()
}

onMounted(() => {
  if (!chartEl.value) return
  chart.value = echarts.init(chartEl.value)
  render()
  window.addEventListener('resize', resize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', resize)
  chart.value?.dispose()
  chart.value = null
})

// 数据到位 / 切换指标 / 指标可用集合变化都要重画（图表容器在不足 2 遍时不渲染）。
// `flush: 'post'`：容器由 `v-if` 挂出来，默认的 pre 时机里 DOM 还没更新、`chartEl` 为 null，
// 会静默跳过首次 init（走查实测：折线要等切换指标才出现）。
watch(
  [series, availableKeys, hasCompare],
  () => {
    if (!chart.value && hasCompare.value && chartEl.value) {
      chart.value = echarts.init(chartEl.value)
    }
    render()
  },
  { flush: 'post' }
)
</script>

<template>
  <section class="progress">
    <div class="progress__head">
      <span class="progress__title">进步对比</span>
      <span class="progress__count">已练 {{ progress?.attempt_count ?? 0 }} 遍</span>
    </div>

    <p v-if="!hasCompare" class="progress__guide">
      再练一遍就会出现跨次对比——用时、填充词、停顿这些看得见的变化。
    </p>

    <template v-else>
      <div class="progress__deltas">
        <div v-for="key in DELTA_KEYS" :key="key" class="delta" :class="`delta--${deltaTone(key, pair[0][key], pair[1][key])}`">
          <span class="delta__label">{{ METRICS.find((m) => m.key === key)?.label }}</span>
          <span class="delta__value">{{ formatDelta(key, pair[0][key], pair[1][key]) }}</span>
        </div>
      </div>
      <p class="progress__note">对比口径：最近一次 vs 上一次</p>

      <div class="progress__tabs">
        <span class="progress__tabs-hint">一次只看一个指标：</span>
        <el-radio-group v-model="activeKey" size="small">
          <el-radio-button
            v-for="key in availableKeys"
            :key="key"
            :value="key"
            :disabled="activeKey !== key && !availableKeys.includes(key)"
          >
            {{ METRICS.find((m) => m.key === key)?.label }}
          </el-radio-button>
        </el-radio-group>
      </div>

      <div ref="chartEl" class="progress__chart" />
      <p v-if="series.skipped.length" class="progress__skipped">
        第 {{ series.skipped.join('、') }} 遍没有{{ activeMetric?.label }}数据（文字作答或作答过短），未画入曲线。
      </p>
    </template>
  </section>
</template>

<style scoped>
.progress {
  margin-top: var(--card-gap);
  padding: 14px var(--card-padding);
  background: var(--c-card);
  border: 1px solid var(--c-border);
  border-radius: var(--r-card);
}
.progress__head {
  display: flex;
  align-items: baseline;
  gap: 10px;
}
.progress__title {
  font-size: var(--fs-title);
  font-weight: 700;
  color: var(--c-text);
}
.progress__count {
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}
.progress__guide {
  margin: 10px 0 0;
  padding: 10px 12px;
  font-size: var(--fs-sm);
  color: var(--c-text-2);
  background: var(--c-bg);
  border-radius: var(--r-card);
}

.progress__deltas {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: 10px;
  margin-top: 12px;
}
.delta {
  padding: 10px 12px;
  border-radius: var(--r-card);
  background: var(--c-bg);
  border-left: 3px solid var(--c-border);
}
.delta__label {
  display: block;
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}
.delta__value {
  display: block;
  margin-top: 4px;
  font-size: var(--fs-title);
  font-weight: 600;
  color: var(--c-text);
  font-variant-numeric: tabular-nums;
}
.delta--good {
  border-left-color: var(--m-practice);
}
.delta--good .delta__value {
  color: var(--m-practice);
}
.delta--bad {
  border-left-color: var(--m-wrong);
}
.delta--bad .delta__value {
  color: var(--m-wrong);
}
.progress__note {
  margin: 8px 0 0;
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}

.progress__tabs {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 14px;
  flex-wrap: wrap;
}
.progress__tabs-hint {
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}
.progress__chart {
  width: 100%;
  height: 200px;
  margin-top: 8px;
}
.progress__skipped {
  margin: 0;
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}
</style>
