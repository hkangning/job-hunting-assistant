<script setup>
// 投递趋势折线图（FR-005）。受控组件：数据由页面请求后经 props 传入，本组件不调接口
import { computed, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import * as echarts from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([LineChart, GridComponent, TooltipComponent, CanvasRenderer])

const props = defineProps({
  items: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  days: { type: Number, default: 30 }
})
const emit = defineEmits(['change-days'])

const chartEl = ref(null)
const chart = shallowRef(null)
const range = ref(props.days)

const isEmpty = computed(() => props.items.every((item) => !item.count))

watch(
  () => props.days,
  (value) => {
    range.value = value
  }
)

function buildOption() {
  return {
    grid: { left: 40, right: 16, top: 16, bottom: 28 },
    tooltip: { trigger: 'axis' },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: props.items.map((item) => item.date.slice(5)),
      axisLine: { lineStyle: { color: '#ECEBF5' } },
      axisLabel: { color: '#A5A0BC', fontSize: 11 }
    },
    yAxis: {
      type: 'value',
      minInterval: 1,
      splitLine: { lineStyle: { color: '#F3F2FA' } },
      // 计数轴不出现小数刻度（minInterval 在极小区间下仍会给出 0.5 一类的中间刻度）
      axisLabel: {
        color: '#A5A0BC',
        fontSize: 11,
        formatter: (value) => (Number.isInteger(value) ? value : '')
      }
    },
    series: [
      {
        name: '投递数',
        type: 'line',
        smooth: false,
        symbolSize: 5,
        data: props.items.map((item) => item.count),
        lineStyle: { color: '#5B8DD9', width: 2 },
        itemStyle: { color: '#5B8DD9' },
        // 区间较短时逐点标注，便于与看板卡片数对账
        label: {
          show: props.items.length <= 30,
          color: '#7A7590',
          fontSize: 11,
          formatter: (params) => (params.value > 0 ? params.value : '')
        }
      }
    ]
  }
}

function render() {
  if (!chart.value) return
  chart.value.setOption(buildOption())
}

function resize() {
  chart.value?.resize()
}

function onRangeChange(value) {
  emit('change-days', value)
}

onMounted(() => {
  chart.value = echarts.init(chartEl.value)
  render()
  window.addEventListener('resize', resize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', resize)
  chart.value?.dispose()
  chart.value = null
})

watch(() => props.items, render)
</script>

<template>
  <div class="trend">
    <div class="trend__head">
      <span class="trend__title">投递趋势</span>
      <el-radio-group v-model="range" size="small" @change="onRangeChange">
        <el-radio-button :value="7">7 天</el-radio-button>
        <el-radio-button :value="30">30 天</el-radio-button>
        <el-radio-button :value="90">90 天</el-radio-button>
      </el-radio-group>
    </div>
    <div ref="chartEl" v-loading="loading" class="trend__chart"></div>
    <div v-if="isEmpty" class="trend__empty">该区间暂无投递</div>
  </div>
</template>

<style scoped>
.trend {
  margin-top: var(--card-gap);
  background: var(--c-card);
  border: 1px solid var(--c-border);
  border-radius: var(--r-card);
  padding: var(--card-padding);
}
.trend__head {
  display: flex;
  align-items: center;
  margin-bottom: 8px;
}
.trend__title {
  font-size: 13px;
  font-weight: 700;
  color: var(--c-text);
}
.trend__head .el-radio-group {
  margin-left: auto;
}
.trend__chart {
  width: 100%;
  height: 180px;
}
.trend__empty {
  margin-top: 4px;
  font-size: 11.5px;
  color: var(--c-text-3);
}
</style>
