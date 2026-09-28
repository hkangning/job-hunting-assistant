<script setup>
/**
 * 一轮训练的渲染：用户作答 + AI 点评的各 section 分块（接口文档 v1.26 §3.8）。
 *
 * 分块数据由 `utils/practiceStream.js` 备好，本组件只负责按 section 选版式；
 * 层号与攻击面中文名取自 `meta.faces`，不硬编码。
 */
import { computed } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import StreamText from '../StreamText.vue'
import { DIMENSION_LABELS, parseRoundScore } from '../../utils/practiceStream'

const props = defineProps({
  turn: { type: Object, required: true },
  faces: { type: Array, default: () => [] },
  qtype: { type: String, default: '' }
})
const emit = defineEmits(['retry'])

const KIND_LABELS = {
  OPENING: '初始作答',
  FOLLOW_UP: '追问',
  HINT: '提示',
  REBUTTAL: '找错',
  RETELL: '复述'
}

const kindLabel = computed(() => KIND_LABELS[props.turn.kind] || '本轮')

const scoreBlock = computed(() => props.turn.blocks.find((b) => b.section === 'round_score'))
const scoreInfo = computed(() => (scoreBlock.value ? parseRoundScore(scoreBlock.value.text) : null))

/** 四维分栏的数据源：优先用解析出的对象，解析不出则退回原始文本。 */
const dimensionRows = computed(() => {
  const dims = props.turn.dimensions
  if (!dims) return []
  return Object.entries(DIMENSION_LABELS).map(([key, label]) => ({
    key,
    label,
    value: typeof dims[key] === 'number' ? dims[key] : 0
  }))
})

const dimensionTotal = computed(() =>
  dimensionRows.value.reduce((sum, row) => sum + row.value, 0)
)

/** 场景题不谈「标准答案」，给的是参考框架。 */
const answerTitle = computed(() => (props.qtype === 'SCENARIO' ? '参考框架' : '参考答案'))

/** 追问进度的「第 N 层 · 攻击面」——层号来自上一轮 done.extra，中文名查 meta.faces。 */
const followUpLabel = computed(() => {
  const { layer, face } = props.turn.next || {}
  if (!layer || !face) return ''
  const hit = props.faces.find((f) => f.value === face)
  return `第 ${layer} 层 · ${hit ? hit.label : face}`
})
</script>

<template>
  <article class="turn">
    <header class="turn__head">
      <span class="turn__kind">{{ kindLabel }}</span>
      <span v-if="scoreInfo && scoreInfo.score !== null" class="turn__score">
        {{ scoreInfo.score }}<i>分</i>
      </span>
    </header>

    <div v-if="turn.userAnswer !== null && turn.userAnswer !== undefined" class="turn__answer">
      <span class="turn__answer-label">我的作答</span>
      <p class="turn__answer-text">{{ turn.userAnswer || '（未作答）' }}</p>
    </div>

    <div
      v-for="block in turn.blocks"
      :key="block.section"
      class="turn__block"
      :class="`turn__block--${block.section}`"
    >
      <!-- 本轮评分：徽章已在头部，这里补一句话结论 -->
      <template v-if="block.section === 'round_score'">
        <p v-if="scoreInfo && scoreInfo.note" class="turn__note">{{ scoreInfo.note }}</p>
      </template>

      <!-- 场景题四维分栏（总分取 round_score 的评分） -->
      <template v-else-if="block.section === 'dimensions'">
        <div v-if="dimensionRows.length" class="turn__dims">
          <div v-for="row in dimensionRows" :key="row.key" class="turn__dim">
            <span class="turn__dim-label">{{ row.label }}</span>
            <span class="turn__dim-bar"><i :style="{ width: `${row.value * 10}%` }" /></span>
            <span class="turn__dim-value">{{ row.value }}</span>
          </div>
          <div class="turn__dim-total">
            总分 <b>{{ scoreInfo && scoreInfo.score !== null ? scoreInfo.score : dimensionTotal }}</b>
          </div>
        </div>
        <p v-else class="turn__text"><StreamText :text="block.text" /></p>
      </template>

      <!-- 提示：只给方向不给答案 -->
      <template v-else-if="block.section === 'hint'">
        <span class="turn__tag turn__tag--hint">方向性提示</span>
        <p class="turn__text"><StreamText :text="block.text" :streaming="turn.streaming" /></p>
      </template>

      <!-- 挑错材料：待挑错的候选人答案 -->
      <template v-else-if="block.section === 'material'">
        <span class="turn__tag turn__tag--material">候选人答案（找出其中的错误）</span>
        <p class="turn__material"><StreamText :text="block.text" :streaming="turn.streaming" /></p>
      </template>

      <!-- 下一问：一次只问一个 -->
      <template v-else-if="block.section === 'next_question'">
        <span v-if="followUpLabel" class="turn__tag turn__tag--followup">{{ followUpLabel }}</span>
        <p class="turn__text turn__text--strong">
          <StreamText :text="block.text" :streaming="turn.streaming" />
        </p>
      </template>

      <!-- 整场总结 -->
      <template v-else-if="block.section === 'summary'">
        <span class="turn__tag turn__tag--summary">本场总结</span>
        <p class="turn__text"><StreamText :text="block.text" :streaming="turn.streaming" /></p>
      </template>

      <!-- 参考答案：仅 QUICK 当轮给，其余模式在结算页 -->
      <template v-else-if="block.section === 'reference_answer'">
        <span class="turn__tag turn__tag--ref">{{ answerTitle }}</span>
        <p class="turn__text"><StreamText :text="block.text" :streaming="turn.streaming" /></p>
      </template>

      <!-- 差距点与其余文本 -->
      <template v-else>
        <span v-if="block.section === 'review'" class="turn__tag">与参考答案的差距</span>
        <p class="turn__text"><StreamText :text="block.text" :streaming="turn.streaming" /></p>
      </template>
    </div>

    <div v-if="turn.error" class="turn__error">
      <span>{{ turn.error }}</span>
      <el-button size="small" :icon="Refresh" type="primary" plain @click="emit('retry')">
        重试本轮
      </el-button>
    </div>
  </article>
</template>

<style scoped>
.turn {
  background: var(--c-card);
  border: 1px solid var(--c-border);
  border-radius: var(--r-card);
  box-shadow: 0 1px 2px rgba(42, 39, 64, 0.05);
  padding: var(--card-padding);
}
.turn + .turn {
  margin-top: var(--card-gap);
}

.turn__head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  margin-bottom: 10px;
}
.turn__kind {
  font-size: var(--fs-sm);
  color: var(--c-text-2);
}
.turn__score {
  font-size: var(--fs-h1);
  font-weight: 700;
  line-height: 1;
  color: var(--m-practice);
}
.turn__score i {
  margin-left: 2px;
  font-size: var(--fs-xs);
  font-style: normal;
  font-weight: 400;
}

.turn__answer {
  margin-bottom: 10px;
  padding: 8px 12px;
  background: var(--c-bg);
  border-left: 3px solid var(--c-divider);
  border-radius: var(--r-control);
}
.turn__answer-label {
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}
.turn__answer-text {
  margin: 4px 0 0;
  font-size: var(--fs-body);
  line-height: 1.7;
  color: var(--c-text);
  white-space: pre-wrap;
  word-break: break-word;
}

.turn__block + .turn__block {
  margin-top: 10px;
}

.turn__tag {
  display: inline-block;
  margin-bottom: 6px;
  padding: 2px 6px;
  font-size: var(--fs-xs);
  border-radius: var(--r-mark);
  background: var(--c-bg);
  color: var(--c-text-2);
}
/* 彩色浅底用 color-mix；不支持时退回上面的中性底（第一行即 fallback） */
.turn__tag--hint {
  color: var(--m-practice);
  background: color-mix(in srgb, var(--m-practice) 14%, var(--c-card));
}
.turn__tag--material {
  color: var(--m-interview);
  background: color-mix(in srgb, var(--m-interview) 16%, var(--c-card));
}
.turn__tag--followup {
  color: var(--brand);
  background: color-mix(in srgb, var(--brand) 14%, var(--c-card));
}

.turn__note,
.turn__text {
  margin: 0;
  font-size: var(--fs-body);
  line-height: 1.7;
  color: var(--c-text);
}
.turn__text--strong {
  font-weight: 600;
}

.turn__material {
  margin: 0;
  padding: 10px 14px;
  background: var(--c-bg);
  border-left: 3px solid var(--m-interview);
  border-radius: var(--r-control);
  font-size: var(--fs-body);
  line-height: 1.7;
  color: var(--c-text);
  white-space: pre-wrap;
  word-break: break-word;
}

.turn__dims {
  display: grid;
  gap: 6px;
}
.turn__dim {
  display: grid;
  grid-template-columns: 72px 1fr 28px;
  align-items: center;
  gap: 8px;
  font-size: var(--fs-sm);
  color: var(--c-text-2);
}
.turn__dim-bar {
  display: block;
  height: 8px;
  background: var(--c-divider);
  border-radius: var(--r-bar);
  overflow: hidden;
}
.turn__dim-bar i {
  display: block;
  height: 100%;
  background: var(--m-practice);
}
.turn__dim-value {
  text-align: right;
}
.turn__dim-total {
  font-size: var(--fs-sm);
  color: var(--c-text-2);
}
.turn__dim-total b {
  font-size: var(--fs-title);
  color: var(--m-practice);
}

.turn__error {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 10px;
  font-size: var(--fs-sm);
  color: var(--el-color-danger);
}
</style>
