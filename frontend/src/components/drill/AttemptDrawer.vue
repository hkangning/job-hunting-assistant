<script setup>
/**
 * 单次练习完整内容（接口 `GET /drills/{topic_id}/attempts/{attempt_id}`）。
 *
 * 时间线摘要不含点评全文与指标（契约如此，控制列表体量），点开这一遍才拉完整 DTO：
 * 我的作答 + 表达力指标卡（复用面试页同款组件，后端两处结构一致）+ 完整点评。
 */
import { ref, watch } from 'vue'
import { getDrillAttempt } from '../../api/drill'
import { reviewBody } from '../../utils/drillStream'
import { durationText } from '../../utils/drillMeta'
import { shortDateTime } from '../../utils/datetime'
import MetricsCard from '../interview/MetricsCard.vue'
import ReviewBody from '../interview/ReviewBody.vue'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  topicId: { type: Number, default: null },
  attemptId: { type: Number, default: null }
})
const emit = defineEmits(['update:modelValue'])

const attempt = ref(null)
const loading = ref(false)
const errorMsg = ref('')

/** 拉取单次记录（打开抽屉与失败重试共用）。 */
async function reload() {
  const id = props.attemptId
  if (id == null) return
  loading.value = true
  errorMsg.value = ''
  attempt.value = null
  try {
    attempt.value = await getDrillAttempt(props.topicId, id)
  } catch (error) {
    errorMsg.value = error?.message || '记录加载失败，请稍后重试'
  } finally {
    loading.value = false
  }
}

watch(
  [() => props.modelValue, () => props.attemptId],
  ([open, id]) => {
    if (!open || id == null) return
    reload()
  }
)
</script>

<template>
  <el-drawer
    :model-value="modelValue"
    :title="attempt ? `第 ${attempt.seq} 遍` : '练习记录'"
    size="560px"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <div v-loading="loading" class="attempt">
      <p v-if="errorMsg" class="attempt__error">
        <span>{{ errorMsg }}</span>
        <el-button size="small" @click="reload">重试</el-button>
      </p>

      <template v-if="attempt">
        <div class="attempt__meta">
          <span v-if="attempt.score != null" class="attempt__score">
            {{ attempt.score }}<i>分</i>
          </span>
          <span v-if="attempt.duration_ms != null" class="attempt__chip">
            {{ durationText(attempt.duration_ms) }}
          </span>
          <span class="attempt__chip">{{ attempt.is_voice ? '语音作答' : '文字作答' }}</span>
          <span class="attempt__time">{{ shortDateTime(attempt.created_at) }}</span>
        </div>

        <h3 class="attempt__label">我的作答</h3>
        <p class="attempt__answer">{{ attempt.answer || '（未留下作答文本）' }}</p>

        <MetricsCard v-if="attempt.voice_metrics" :metrics="attempt.voice_metrics" />
        <p v-else-if="attempt.is_voice" class="attempt__hint">
          这一遍没产出表达力指标——作答不足 10 秒或未带上分句时间轴时不计算。
        </p>

        <h3 class="attempt__label">点评</h3>
        <div class="attempt__review">
          <ReviewBody :text="reviewBody(attempt)" />
        </div>
      </template>
    </div>
  </el-drawer>
</template>

<style scoped>
.attempt {
  min-height: 120px;
}
.attempt__error {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 0 0 12px;
  font-size: var(--fs-sm);
  color: var(--el-color-danger);
}
.attempt__meta {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;
}
.attempt__score {
  font-size: 24px;
  font-weight: 700;
  line-height: 1;
  color: var(--m-drill);
}
.attempt__score i {
  font-size: var(--fs-xs);
  font-style: normal;
  font-weight: 400;
  margin-left: 2px;
}
.attempt__chip {
  padding: 1px 8px;
  font-size: var(--fs-xs);
  color: var(--c-text-2);
  background: var(--c-bg);
  border-radius: var(--r-mark);
}
.attempt__time {
  margin-left: auto;
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}
.attempt__label {
  margin: 16px 0 6px;
  font-size: var(--fs-sm);
  font-weight: 600;
  color: var(--c-text-2);
}
.attempt__answer {
  margin: 0;
  padding: 10px 12px;
  font-size: var(--fs-body);
  line-height: 1.8;
  color: var(--c-text);
  background: var(--c-bg);
  border-radius: var(--r-card);
  white-space: pre-wrap;
  word-break: break-word;
}
.attempt__hint {
  margin: 0;
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}
.attempt__review {
  font-size: var(--fs-body);
  line-height: 1.8;
  color: var(--c-text);
}
</style>
