<script setup>
/**
 * 表达力指标卡（步骤 25 / SRS §3.11 FR-014 / 接口文档 §3.13）。
 *
 * 「事实」卡片，与「解读」性质的点评卡分列：五项指标由后端纯函数算出（不调 LLM、
 * 毫秒级），**参考区间为经验值、不作为评分依据**——故不做红绿判定，参考值以灰色
 * 小字附在数值后，保持中性呈现。
 *
 * 数据来源：实时路径为 `done.extra.voice_metrics`、回看路径为 `qa_list[].voice_metrics`；
 * `quality=TOO_SHORT / TEXT_ONLY` 时后端不下发（父级不渲染本组件，「有则渲染、无则跳过」）。
 */
import { computed } from 'vue'

const props = defineProps({
  /** voice_metrics 快照（结构见数据库设计 §3.19） */
  metrics: { type: Object, required: true }
})

const TREND_LABELS = { IMPROVING: '提升', STABLE: '平稳', DECLINING: '下滑' }

const voice = computed(() => props.metrics || {})
const pct = (v) => (v == null ? '—' : `${Math.round(v * 100)}%`)
const secs = (ms) => (ms == null ? '—' : `${(ms / 1000).toFixed(1)} 秒`)

/** 填充词明细（仅非零项，「然后×6、就是×4」）。 */
const fillerText = computed(() => {
  const detail = voice.value.filler_detail || {}
  const items = Object.entries(detail)
    .filter(([, n]) => n > 0)
    .map(([word, n]) => `${word}×${n}`)
  return items.length ? items.join('、') : '无'
})

/** 最长停顿的位置（后端 context = 停顿前句末 10 字）。 */
const longestCtx = computed(() => {
  const pauses = voice.value.pauses || []
  const longest = pauses.find((p) => p.duration_ms === voice.value.longest_pause_ms) || pauses[0]
  return longest?.context ? `，在「${longest.context}」前` : ''
})
</script>

<template>
  <div class="metrics">
    <div class="metrics__head">
      <span class="metrics__title">表达力</span>
      <span class="metrics__note">参考区间为经验值，不作评分依据</span>
    </div>
    <div class="metrics__grid">
      <div class="metrics__item">
        <span class="metrics__value">{{ voice.speech_rate ?? '—' }}<i>字/分</i></span>
        <span class="metrics__label">语速 · 参考 180~240</span>
      </div>
      <div class="metrics__item">
        <span class="metrics__value">{{ voice.filler_count ?? 0 }}<i>处</i></span>
        <span class="metrics__label">填充词 · {{ fillerText }}</span>
      </div>
      <div class="metrics__item">
        <span class="metrics__value">{{ (voice.pauses || []).length }}<i>处</i></span>
        <span class="metrics__label">
          停顿 · 最长 {{ secs(voice.longest_pause_ms) }}{{ longestCtx }}
        </span>
      </div>
      <div class="metrics__item">
        <span class="metrics__value">{{ pct(voice.speech_ratio) }}</span>
        <span class="metrics__label">有效时长占比 · 参考 &gt;70%</span>
      </div>
      <div class="metrics__item">
        <span class="metrics__value">{{ TREND_LABELS[voice.fluency_trend?.direction] || '—' }}</span>
        <span class="metrics__label">流畅度趋势</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* 中性轻卡片：比点评卡（模块色淡底）更「素」——它陈述事实、不承担评价色彩 */
.metrics {
  border: 1px dashed var(--c-border);
  border-radius: 10px;
  background: var(--c-bg);
  padding: 10px 16px 12px;
}
.metrics__head {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin-bottom: 8px;
}
.metrics__title {
  font-size: var(--fs-sm);
  font-weight: 600;
  color: var(--c-text-2);
}
.metrics__note {
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}
.metrics__grid {
  display: flex;
  flex-wrap: wrap;
  gap: 10px 28px;
}
.metrics__item {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.metrics__value {
  font-size: var(--fs-title);
  font-weight: 700;
  color: var(--c-text);
  font-variant-numeric: tabular-nums;
}
.metrics__value i {
  font-size: var(--fs-xs);
  font-style: normal;
  font-weight: 400;
  color: var(--c-text-3);
  margin-left: 2px;
}
.metrics__label {
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}
</style>
