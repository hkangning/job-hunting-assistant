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
import { dueText, nextPlanText } from '../../utils/reviewPlan'

const props = defineProps({
  item: { type: Object, required: true },
  meta: { type: Object, default: null },
  result: { type: Object, default: null },
  busy: { type: Boolean, default: false },
  /** 队列里还有下一条待复习（父组件按下标后算，跳过已掌握）。 */
  hasNext: { type: Boolean, default: false }
})
const emit = defineEmits(['submit', 'back', 'remove', 'next'])

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

/** 头部右侧：未判定显示该题的复习时点；判定后显示下次复习时间（档位是内部机制，不上界面）。 */
const headPlan = computed(() => {
  if (props.result) {
    return props.result.mastered ? '已掌握' : `下次复习：${nextPlanText(props.result.next_review_at)}`
  }
  return dueText(props.item.next_review_at)
})
</script>

<template>
  <section class="review">
    <header class="review__head">
      <span class="review__kind">错题复习</span>
      <span class="review__stage">{{ headPlan }}</span>
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
        :autosize="{ minRows: 4, maxRows: 10 }"
        :disabled="busy || !!result"
        placeholder="写下你的答案"
      />
    </div>

    <!-- 判定结果：答完才出现 -->
    <div v-if="result" class="review__result" :class="{ 'review__result--wrong': !result.correct }">
      <span class="review__verdict">{{ result.correct ? '答对了' : '答错了' }}</span>
      <p class="review__explain">{{ toPlainText(result.explain) }}</p>
    </div>

    <div class="review__actions">
      <el-button :icon="Back" :disabled="busy" @click="emit('back')">返回列表</el-button>
      <div class="review__actions-main">
        <el-button link class="review__remove" :disabled="busy" @click="emit('remove', item)">
          删除
        </el-button>
        <span v-if="busy" class="review__pending">AI 判定中…</span>
        <el-button v-if="!result" type="primary" :disabled="!canSubmit" :loading="busy" @click="submit">
          提交
        </el-button>
        <el-button v-else-if="hasNext" type="primary" @click="emit('next')">
          下一条待复习 →
        </el-button>
        <span v-else class="review__finished">这批错题已复习完</span>
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
/* 删除：中性色 + hover 危险色——复习的主动作是「下一条」，删除不抢位 */
.review__remove.el-button {
  color: var(--c-text-3);
}
.review__remove.el-button:hover {
  color: var(--el-color-danger);
}
.review__finished {
  font-size: var(--fs-sm);
  color: var(--c-text-2);
}
.review__pending {
  font-size: var(--fs-sm);
  color: var(--c-text-3);
}
.review__explain {
  margin: 8px 0 0;
  font-size: var(--fs-body);
  line-height: 1.7;
  color: var(--c-text);
  white-space: pre-wrap;
  word-break: break-word;
}

/* 按钮行整体左对齐（2026-09-29）：与陪练作答区同构——选项/输入框左对齐，
   主操作跟随其正下方。原以 margin-left:auto 两端分列，点完选项要横跨屏幕才能提交。 */
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
}
</style>
