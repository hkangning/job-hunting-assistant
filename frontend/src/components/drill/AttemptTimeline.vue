<script setup>
/**
 * 历次练习记录时间线（FR-020）：按遍次升序，一行一遍——得分 / 时长 / 语音标签 / 时间，
 * 点开抽屉看这一遍的完整作答、表达力指标与点评。
 *
 * 「正在练的这一遍」（`liveSeq`）在列表末尾占一行虚线态，让用户知道新记录会落在哪。
 */
import { shortDateTime } from '../../utils/datetime'
import { durationText } from '../../utils/drillMeta'
import AppEmpty from '../AppEmpty.vue'

defineProps({
  /** 服务端的 attempts 摘要数组（`{id, seq, is_voice, score, duration_ms, created_at}`）。 */
  attempts: { type: Array, default: () => [] },
  /** 正在流式的那一遍的 seq（没有则为 null）。 */
  liveSeq: { type: Number, default: null }
})
const emit = defineEmits(['open'])
</script>

<template>
  <section class="timeline">
    <div class="timeline__head">
      <span class="timeline__title">历次记录</span>
      <span class="timeline__count">{{ attempts.length }} 遍</span>
    </div>

    <AppEmpty
      v-if="!attempts.length && !liveSeq"
      type="practice"
      size="sm"
      description="还没有练习记录——在上面写下第一遍，这里就会出现"
      style="--empty-color: var(--m-drill)"
    />

    <ol v-else class="timeline__list">
      <li
        v-for="attempt in attempts"
        :key="attempt.id"
        class="row"
        @click="emit('open', attempt)"
      >
        <span class="row__seq">第 {{ attempt.seq }} 遍</span>
        <span v-if="attempt.score != null" class="row__score">{{ attempt.score }}<i>分</i></span>
        <span v-else class="row__score row__score--none">未评分</span>
        <span class="row__meta">
          <span v-if="attempt.duration_ms != null">{{ durationText(attempt.duration_ms) }}</span>
          <span v-if="attempt.is_voice" class="row__voice">语音</span>
          <span class="row__time">{{ shortDateTime(attempt.created_at) }}</span>
        </span>
        <span class="row__more">查看 ›</span>
      </li>

      <li v-if="liveSeq" class="row row--live">
        <span class="row__seq">第 {{ liveSeq }} 遍</span>
        <span class="row__live-text">正在生成点评…</span>
      </li>
    </ol>
  </section>
</template>

<style scoped>
.timeline {
  margin-top: var(--card-gap);
  padding: 14px var(--card-padding);
  background: var(--c-card);
  border: 1px solid var(--c-border);
  border-radius: var(--r-card);
}
.timeline__head {
  display: flex;
  align-items: baseline;
  gap: 10px;
}
.timeline__title {
  font-size: var(--fs-title);
  font-weight: 700;
  color: var(--c-text);
}
.timeline__count {
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}
.timeline__empty {
  margin: 10px 0 0;
  font-size: var(--fs-sm);
  color: var(--c-text-3);
}

.timeline__list {
  margin: 10px 0 0;
  padding: 0;
  list-style: none;
  border-left: 2px solid var(--c-divider);
}
.row {
  position: relative;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px 10px 18px;
  cursor: pointer;
  border-radius: var(--r-card);
}
.row::before {
  content: '';
  position: absolute;
  left: -6px;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--m-drill);
}
.row:hover {
  background: var(--c-bg);
}
.row__seq {
  font-size: var(--fs-sm);
  font-weight: 600;
  color: var(--c-text);
}
.row__score {
  font-size: var(--fs-title);
  font-weight: 700;
  color: var(--m-drill);
  font-variant-numeric: tabular-nums;
}
.row__score i {
  font-size: var(--fs-xs);
  font-style: normal;
  font-weight: 400;
  margin-left: 1px;
}
.row__score--none {
  font-size: var(--fs-xs);
  font-weight: 400;
  color: var(--c-text-3);
}
.row__meta {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-left: auto;
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}
.row__voice {
  padding: 0 6px;
  color: var(--m-drill);
  background: color-mix(in srgb, var(--m-drill) 12%, var(--c-card));
  border-radius: var(--r-mark);
}
.row__more {
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}
.row--live {
  cursor: default;
  border: 1px dashed color-mix(in srgb, var(--m-drill) 45%, var(--c-card));
}
.row--live::before {
  background: var(--c-card);
  border: 2px solid var(--m-drill);
}
.row--live:hover {
  background: transparent;
}
.row__live-text {
  font-size: var(--fs-sm);
  color: var(--c-text-3);
}
</style>
