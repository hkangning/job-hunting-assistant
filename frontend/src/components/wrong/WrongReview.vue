<script setup>
/**
 * 错题复习：题干 + 作答区（选择题点选 / 其余题型文本框）+ 判定结果与档位变化。
 *
 * 判定走 `POST /wrong-questions/{id}/review`——选择题是**服务端规则比对**（零 AI 调用），
 * 主观题与场景题走 LLM 判定。请求由父组件发，结果经 `result` 传入，本组件只管展示。
 */
import { computed, ref, watch } from 'vue'
import { Back } from '@element-plus/icons-vue'
import ChoiceOptions from '../ChoiceOptions.vue'
import { toPlainText } from '../../utils/practiceStream'
import { directionLabelMap } from '../../utils/practiceMeta'

const props = defineProps({
  item: { type: Object, required: true },
  meta: { type: Object, default: null },
  result: { type: Object, default: null },
  busy: { type: Boolean, default: false }
})
const emit = defineEmits(['submit', 'back', 'remove'])

/** 选择题走点选；其余题型文本框。选项为空的 CHOICE（老数据）也退回文本框。 */
const isChoice = computed(() => props.item.qtype === 'CHOICE' && (props.item.options || []).length > 0)

const picked = ref('')
const answer = ref('')

/** 换一条错题时清空作答区与上一次的判定（结果由父组件置空）。 */
watch(
  () => props.item?.id,
  () => {
    picked.value = ''
    answer.value = ''
  }
)

const canSubmit = computed(() => !props.busy)

function submit() {
  if (!canSubmit.value) return
  emit('submit', isChoice.value ? picked.value : answer.value)
}

/** 领域中文名：与列表同一份映射，避免一处显示 `DESIGN`、一处显示「设计模式与架构」。 */
const directionLabel = computed(() => {
  const map = directionLabelMap(props.meta)
  return map[props.item?.direction] || props.item?.direction || ''
})

const stageText = computed(() => {
  const before = props.item?.review_stage
  const after = props.result?.review_stage
  if (after === undefined || after === null) return `第 ${before} 档`
  return `第 ${before} 档 → 第 ${after} 档`
})
</script>

<template>
  <section class="review">
    <header class="review__head">
      <span class="review__kind">错题复习</span>
      <span class="review__stage">{{ stageText }}</span>
    </header>

    <p class="review__content">{{ item.content }}</p>
    <span class="review__dir">{{ directionLabel }}</span>

    <div class="review__answer">
      <ChoiceOptions
        v-if="isChoice"
        v-model="picked"
        :options="item.options"
        :disabled="busy || !!result"
      />
      <el-input
        v-else
        v-model="answer"
        type="textarea"
        :rows="4"
        :disabled="busy || !!result"
        placeholder="写下你的答案"
      />
    </div>

    <!-- 判定结果：答完才出现 -->
    <div v-if="result" class="review__result" :class="{ 'review__result--wrong': !result.correct }">
      <span class="review__verdict">{{ result.correct ? '答对了' : '答错了' }}</span>
      <span v-if="result.mastered" class="review__mastered">四档已走完，已掌握</span>
      <p class="review__explain">{{ toPlainText(result.explain) }}</p>
    </div>

    <div class="review__actions">
      <el-button :icon="Back" :disabled="busy" @click="emit('back')">返回列表</el-button>
      <div class="review__actions-main">
        <el-button link type="danger" :disabled="busy" @click="emit('remove', item)">删除此题</el-button>
        <el-button v-if="!result" type="primary" :disabled="!canSubmit" @click="submit">
          提交
        </el-button>
      </div>
    </div>
  </section>
</template>

<style scoped>
.review {
  background: var(--c-card);
  border: 1px solid var(--c-border);
  border-radius: var(--r-card);
  box-shadow: 0 1px 2px rgba(42, 39, 64, 0.05);
  padding: var(--card-padding);
}

.review__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}
.review__kind {
  padding: 2px 9px;
  font-size: var(--fs-xs);
  color: var(--m-wrong);
  background: color-mix(in srgb, var(--m-wrong) 12%, var(--c-card));
  border-radius: var(--r-mark);
}
.review__stage {
  font-size: var(--fs-sm);
  color: var(--c-text-2);
  font-variant-numeric: tabular-nums;
}

.review__content {
  margin: 0;
  font-size: var(--fs-body);
  line-height: 1.7;
  color: var(--c-text);
  white-space: pre-wrap;
  word-break: break-word;
}
.review__dir {
  display: inline-block;
  margin-top: 6px;
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}

.review__answer {
  margin-top: var(--card-gap);
}

.review__result {
  margin-top: var(--card-gap);
  padding: 12px 14px;
  background: color-mix(in srgb, var(--m-practice) 8%, var(--c-card));
  border-left: 3px solid var(--m-practice);
  border-radius: var(--r-control);
}
.review__result--wrong {
  background: color-mix(in srgb, var(--m-wrong) 8%, var(--c-card));
  border-left-color: var(--m-wrong);
}
.review__verdict {
  font-size: var(--fs-body);
  font-weight: 700;
  color: var(--c-text);
}
.review__mastered {
  margin-left: 10px;
  font-size: var(--fs-sm);
  color: var(--m-practice);
}
.review__explain {
  margin: 8px 0 0;
  font-size: var(--fs-body);
  line-height: 1.7;
  color: var(--c-text);
  white-space: pre-wrap;
  word-break: break-word;
}

.review__actions {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: var(--card-gap);
}
.review__actions-main {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-left: auto;
}
</style>
