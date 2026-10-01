<script setup>
/**
 * 查询结果卡片（`section="result"` 一次性 JSON 的消费侧）。
 *
 * `data` 形态随工具（接口文档 §3.11）：列表类 `{total, items}`、题目类 `{questions}`、
 * 概览类为摘要对象。方向枚举的中文名取自 `/practice/meta`（store 缓存），
 * 拉不到时显示枚举原值。未知 type 不渲染（协议将来扩工具时旧前端不炸）。
 */
import { computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { shortDateTime, datePart } from '../../utils/datetime'
import { STATUS_LABELS, STATUS_COLORS } from '../../constants/application'
import { QTYPE_LABELS } from '../../utils/practiceMeta'
import { useAgentStore } from '../../stores/agent'

const props = defineProps({
  message: { type: Object, required: true }
})

const store = useAgentStore()
const router = useRouter()

const result = computed(() => props.message.result)
const type = computed(() => result.value?.type)
const data = computed(() => result.value?.data || {})

onMounted(() => store.ensureDirections())

const dirLabel = (value) => store.directionLabels?.[value] || value || '综合'

function go(path) {
  store.closePanel()
  router.push(path)
}
</script>

<template>
  <div v-if="result" class="result">
    <!-- 投递列表 -->
    <template v-if="type === 'list_applications'">
      <p class="result__title">投递记录 <span class="result__count">共 {{ data.total ?? data.items?.length ?? 0 }} 条</span></p>
      <div v-for="item in data.items || []" :key="item.id" class="result__row">
        <div class="result__main">
          <span class="result__name">{{ item.company }} · {{ item.position }}</span>
          <span
            class="result__tag"
            :style="{ color: STATUS_COLORS[item.status], borderColor: STATUS_COLORS[item.status] }"
          >{{ item.status_label || STATUS_LABELS[item.status] || item.status }}</span>
        </div>
        <p class="result__sub">{{ [item.city, item.applied_at ? datePart(item.applied_at) : ''].filter(Boolean).join(' · ') }}</p>
      </div>
      <el-button link type="primary" @click="go('/applications')">去投递管理查看</el-button>
    </template>

    <!-- 出题 -->
    <template v-else-if="type === 'generate_questions'">
      <p class="result__title">题目 <span class="result__count">{{ (data.questions || []).length }} 道</span></p>
      <div v-for="q in data.questions || []" :key="q.id" class="result__row">
        <div class="result__main">
          <span class="result__tag result__tag--plain">{{ dirLabel(q.direction) }}</span>
          <span class="result__tag result__tag--plain">{{ QTYPE_LABELS[q.qtype] || q.qtype }}</span>
        </div>
        <p class="result__text">{{ q.content }}</p>
      </div>
      <el-button link type="primary" @click="go('/practice')">去陪练作答</el-button>
    </template>

    <!-- 错题 -->
    <template v-else-if="type === 'quiz_wrong_questions'">
      <p class="result__title">错题 <span class="result__count">共 {{ data.total ?? (data.items || []).length }} 条</span></p>
      <div v-for="q in data.items || []" :key="q.id" class="result__row">
        <div class="result__main">
          <span class="result__tag result__tag--plain">{{ dirLabel(q.direction) }}</span>
          <span class="result__tag result__tag--plain">{{ QTYPE_LABELS[q.qtype] || q.qtype }}</span>
        </div>
        <p class="result__text">{{ q.content }}</p>
      </div>
      <el-button link type="primary" @click="go('/wrong-questions')">去错题本</el-button>
    </template>

    <!-- 面经条目 -->
    <template v-else-if="type === 'search_experience'">
      <p class="result__title">面经条目 <span class="result__count">共 {{ data.total ?? (data.items || []).length }} 条</span></p>
      <div v-for="item in data.items || []" :key="item.id" class="result__row">
        <p class="result__text">
          <span v-if="item.company" class="result__tag result__tag--plain">{{ item.company }}</span>
          {{ item.question }}
        </p>
        <p v-if="item.answer_points" class="result__sub result__sub--clamp">{{ item.answer_points }}</p>
        <el-button link type="primary" size="small" @click="go(`/experiences/${item.experience_id}?item=${item.id}`)">查看条目</el-button>
      </div>
    </template>

    <!-- 今日概览 -->
    <template v-else-if="type === 'get_today_summary'">
      <p class="result__title">今日概览</p>
      <div v-for="(ev, i) in data.upcoming_events || []" :key="`ev${i}`" class="result__row">
        <p class="result__text">{{ ev.company }} · {{ ev.position }}</p>
        <p class="result__sub">{{ shortDateTime(ev.event_at) }}</p>
      </div>
      <div v-for="(f, i) in data.follow_ups || []" :key="`f${i}`" class="result__row">
        <p class="result__text">需跟进：{{ f.company }} · {{ f.position }}</p>
        <p class="result__sub">{{ f.days }} 天无进展</p>
      </div>
      <p v-if="data.due_wrong_questions" class="result__sub">到期错题 {{ data.due_wrong_questions }} 条</p>
      <p v-if="!(data.upcoming_events || []).length && !(data.follow_ups || []).length" class="result__sub">
        今天没有待办，投递与错题都在计划上
      </p>
      <el-button link type="primary" @click="go('/')">去今日概览</el-button>
    </template>
  </div>
</template>

<style scoped>
.result {
  width: 100%;
  padding: 10px 12px;
  border: 1px solid var(--c-border);
  border-radius: var(--r-card);
  background: var(--c-card);
  font-size: var(--fs-sm);
}
.result__title {
  margin: 0 0 6px;
  font-weight: 600;
  color: var(--c-text);
}
.result__count {
  margin-left: 6px;
  font-weight: 400;
  color: var(--c-text-2);
  font-size: var(--fs-xs);
}
.result__row {
  padding: 6px 0;
  border-top: 1px solid var(--c-divider);
}
.result__row:first-of-type {
  border-top: none;
}
.result__main {
  display: flex;
  align-items: center;
  gap: 8px;
}
.result__name {
  color: var(--c-text);
}
.result__tag {
  flex: none;
  padding: 0 6px;
  font-size: var(--fs-xs);
  line-height: 18px;
  border: 1px solid;
  border-radius: var(--r-mark);
}
.result__tag--plain {
  color: var(--c-text-2);
  border-color: var(--c-border);
}
.result__text {
  margin: 0;
  color: var(--c-text);
  line-height: 1.6;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.result__sub {
  margin: 2px 0 0;
  color: var(--c-text-2);
  font-size: var(--fs-xs);
  line-height: 1.6;
}
.result__sub--clamp {
  display: -webkit-box;
  -webkit-line-clamp: 1;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
</style>
