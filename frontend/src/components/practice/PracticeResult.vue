<script setup>
/**
 * 结算视图：综合分 / 断点回顾 / 缺口清单 / 参考答案 / 掌握度变化（接口文档 v1.26 §3.8）。
 *
 * `finish` 幂等，重复调用结果一致；`wrong_question_id` 非空表示本题已记入错题本
 * （该题此前入过本时为原 id，界面上不区分两者——文案对两种情况都成立）。
 */
import { computed } from 'vue'
import { toPlainText } from '../../utils/practiceStream'

const props = defineProps({
  result: { type: Object, required: true },
  meta: { type: Object, default: null },
  qtype: { type: String, default: '' }
})
const emit = defineEmits(['again', 'close', 'open-wrong'])

const KIND_LABELS = {
  OPENING: '初始作答',
  FOLLOW_UP: '追问',
  HINT: '提示',
  REBUTTAL: '找错',
  RETELL: '复述'
}

const answerTitle = computed(() => (props.qtype === 'SCENARIO' ? '参考框架' : '参考答案'))

const breakFaceLabel = computed(() => {
  const value = props.result.break_face
  if (!value) return '无断点'
  const hit = (props.meta?.faces || []).find((f) => f.value === value)
  return hit ? `第 ${hit.layer} 层 · ${hit.label}` : value
})

/** 掌握度影响的是哪一领域——用 meta 的领域清单映射中文名。 */
const directionLabel = computed(() => {
  const value = props.result.mastery_delta?.direction
  if (!value) return ''
  for (const stack of props.meta?.stacks || []) {
    const hit = (stack.domains || []).find((d) => d.value === value)
    if (hit) return hit.label
  }
  return value
})

const delta = computed(() => {
  const d = props.result.mastery_delta
  if (!d) return null
  return { ...d, diff: d.after - d.before }
})
</script>

<template>
  <div class="result">
    <section class="result__card result__card--score" :class="{ 'result__card--fail': !result.passed }">
      <div class="result__score">
        <span class="result__score-value">{{ result.overall_score ?? 0 }}</span>
        <span class="result__score-unit">分</span>
      </div>
      <el-tag :type="result.passed ? 'success' : 'danger'" size="large" effect="dark">
        {{ result.passed ? '本场通过' : '未通过' }}
      </el-tag>
      <div class="result__facts">
        <span>断点：{{ breakFaceLabel }}</span>
        <span>提示 {{ result.hint_count }} 次</span>
      </div>
    </section>

    <section v-if="result.rounds && result.rounds.length" class="result__card">
      <h3 class="result__title">逐轮回顾</h3>
      <ul class="result__rounds">
        <li v-for="round in result.rounds" :key="round.index" class="result__round">
          <span class="result__round-no">第 {{ round.index }} 轮</span>
          <span class="result__round-kind">{{ KIND_LABELS[round.kind] || round.kind }}</span>
          <span v-if="round.score !== null && round.score !== undefined" class="result__round-score">
            {{ round.score }} 分
          </span>
          <span v-if="round.is_break" class="result__round-break">断点</span>
        </li>
      </ul>
    </section>

    <section v-if="result.gaps && result.gaps.length" class="result__card">
      <h3 class="result__title">还缺什么</h3>
      <ul class="result__gaps">
        <li v-for="(gap, index) in result.gaps" :key="index">{{ toPlainText(gap) }}</li>
      </ul>
    </section>

    <section class="result__card">
      <h3 class="result__title">{{ answerTitle }}</h3>
      <p class="result__answer">{{ toPlainText(result.reference_answer) }}</p>
    </section>

    <section v-if="delta" class="result__card">
      <h3 class="result__title">掌握度变化</h3>
      <p class="result__mastery">
        <span>{{ directionLabel }}</span>
        <span class="result__mastery-value">{{ delta.before }} → {{ delta.after }}</span>
        <span class="result__mastery-diff" :class="{ 'result__mastery-diff--down': delta.diff < 0 }">
          {{ delta.diff >= 0 ? '+' : '' }}{{ delta.diff }}
        </span>
      </p>
    </section>

    <el-alert
      v-if="result.wrong_question_id"
      class="result__wrong"
      type="warning"
      :closable="false"
      title="本题未通过，已记入错题本"
    >
      <el-button link type="primary" @click="emit('open-wrong')">去错题本复习</el-button>
    </el-alert>

    <div class="result__actions">
      <el-button type="primary" @click="emit('again')">再练一场</el-button>
      <el-button @click="emit('close')">回到准备台</el-button>
    </div>
  </div>
</template>

<style scoped>
.result__card {
  background: var(--c-card);
  border: 1px solid var(--c-border);
  border-radius: var(--r-card);
  box-shadow: 0 1px 2px rgba(42, 39, 64, 0.05);
  padding: var(--card-padding);
}
.result__card + .result__card {
  margin-top: var(--card-gap);
}

.result__card--score {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  padding: 24px var(--card-padding);
}
.result__score {
  display: flex;
  align-items: baseline;
  gap: 2px;
}
.result__score-value {
  font-size: 44px;
  font-weight: 700;
  line-height: 1;
  color: var(--m-practice);
}
.result__score-unit {
  font-size: var(--fs-sm);
  color: var(--c-text-2);
}
.result__card--fail .result__score-value {
  color: var(--el-color-danger);
}
.result__facts {
  display: flex;
  gap: 16px;
  font-size: var(--fs-sm);
  color: var(--c-text-2);
}

.result__title {
  margin: 0 0 10px;
  font-size: var(--fs-title);
  font-weight: 700;
  color: var(--c-text);
}

.result__rounds {
  display: grid;
  gap: 6px;
  margin: 0;
  padding: 0;
  list-style: none;
}
.result__round {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: var(--fs-sm);
}
.result__round-no {
  color: var(--c-text);
}
.result__round-kind {
  color: var(--c-text-3);
}
.result__round-score {
  margin-left: auto;
  color: var(--c-text);
}
.result__round-break {
  padding: 0 4px;
  font-size: var(--fs-xs);
  color: var(--m-wrong);
  border: 1px solid var(--m-wrong);
  border-radius: var(--r-mark);
}

.result__gaps {
  margin: 0;
  padding-left: 18px;
  font-size: var(--fs-body);
  line-height: 1.8;
  color: var(--c-text);
}

.result__answer {
  margin: 0;
  font-size: var(--fs-body);
  line-height: 1.8;
  color: var(--c-text);
  white-space: pre-wrap;
  word-break: break-word;
}

.result__mastery {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 0;
  font-size: var(--fs-body);
  color: var(--c-text);
}
.result__mastery-value {
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}
.result__mastery-diff {
  font-size: var(--fs-sm);
  color: var(--m-practice);
}
.result__mastery-diff--down {
  color: var(--el-color-danger);
}

.result__wrong {
  margin-top: var(--card-gap);
}

.result__actions {
  display: flex;
  gap: 10px;
  margin-top: var(--card-gap);
}
</style>
