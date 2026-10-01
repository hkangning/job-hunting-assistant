<script setup>
/**
 * 写操作确认卡片（系统设计 §5.8：乐观展示、确认才写、失败可重试）。
 *
 * `tool_call` 的 args 是服务端补全后的完整参数，直接渲染；确认后走执行端点落库
 * （AI 不直接写库）。update_application_status 的 args 只有 application_id——
 * 卡片挂载时补拉一次公司名（失败静默降级为「#id」，不阻塞确认）。
 */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { CircleCheck } from '@element-plus/icons-vue'
import { confirmFields, TOOL_LABELS } from '../../utils/agentStream'
import { getApplication } from '../../api/applications'
import { useAgentStore } from '../../stores/agent'

const props = defineProps({
  message: { type: Object, required: true }
})

const store = useAgentStore()
const router = useRouter()

const tc = computed(() => props.message.toolCall)
const title = computed(() => TOOL_LABELS[tc.value.tool_name] || tc.value.tool_name)
const hasJd = computed(
  () => tc.value.tool_name === 'create_application' && !!String(tc.value.args?.jd_text || '').trim()
)

const appName = ref('')
onMounted(async () => {
  if (tc.value.tool_name !== 'update_application_status') return
  if (tc.value.args?.company) {
    appName.value = tc.value.args.company
    return
  }
  const id = tc.value.args?.application_id
  if (!id) return
  try {
    appName.value = (await getApplication(id)).company
  } catch {
    // 静默降级：显示 #id
  }
})

const fields = computed(() => confirmFields(tc.value.tool_name, tc.value.args, { appName: appName.value }))
const confirmLabel = computed(() =>
  tc.value.tool_name === 'create_application' ? '确认入库' : '确认更新'
)

function goApplications() {
  store.closePanel()
  router.push('/applications')
}
</script>

<template>
  <div class="confirm" :class="`confirm--${tc.status}`">
    <p class="confirm__title">
      <el-icon v-if="tc.status === 'done'" class="confirm__ok"><CircleCheck /></el-icon>
      <span v-if="tc.status === 'pending'">待确认 · {{ title }}</span>
      <span v-else-if="tc.status === 'executing'">正在执行 · {{ title }}</span>
      <span v-else-if="tc.status === 'done'">已入库 · {{ title }}</span>
      <span v-else-if="tc.status === 'failed'">执行失败 · {{ title }}</span>
      <span v-else>已取消 · {{ title }}</span>
    </p>

    <dl v-if="tc.status !== 'cancelled'" class="confirm__fields">
      <div v-for="row in fields" :key="row.label" class="confirm__row">
        <dt>{{ row.label }}</dt>
        <dd>{{ row.value }}</dd>
      </div>
      <div v-if="hasJd" class="confirm__row">
        <dt>岗位 JD</dt>
        <dd class="confirm__jd">已附带</dd>
      </div>
    </dl>

    <p v-if="tc.status === 'failed'" class="confirm__error">{{ tc.error }}</p>

    <div class="confirm__ops">
      <template v-if="tc.status === 'pending'">
        <el-button size="small" @click="store.cancelTool(message.id)">取消</el-button>
        <el-button size="small" type="primary" @click="store.confirmTool(message.id)">{{ confirmLabel }}</el-button>
      </template>
      <template v-else-if="tc.status === 'executing'">
        <el-button size="small" type="primary" loading>执行中…</el-button>
      </template>
      <template v-else-if="tc.status === 'done'">
        <el-button size="small" type="primary" plain @click="goApplications">去投递管理查看</el-button>
      </template>
      <template v-else-if="tc.status === 'failed'">
        <el-button size="small" @click="store.cancelTool(message.id)">取消</el-button>
        <el-button size="small" type="danger" @click="store.confirmTool(message.id)">重试</el-button>
      </template>
    </div>
  </div>
</template>

<style scoped>
.confirm {
  width: 100%;
  padding: 10px 12px;
  border: 1px solid var(--c-border);
  border-radius: var(--r-card);
  background: var(--c-card);
  font-size: var(--fs-sm);
}
.confirm--pending {
  border-color: color-mix(in srgb, var(--brand) 45%, var(--c-border));
  background: color-mix(in srgb, var(--brand) 4%, var(--c-card));
}
.confirm--done {
  border-color: color-mix(in srgb, var(--s-offer) 55%, var(--c-border));
}
.confirm--failed {
  border-color: color-mix(in srgb, var(--el-color-danger) 55%, var(--c-border));
}
.confirm--cancelled {
  opacity: 0.66;
}
.confirm__title {
  margin: 0 0 8px;
  font-weight: 600;
  color: var(--c-text);
  display: flex;
  align-items: center;
  gap: 6px;
}
.confirm--pending .confirm__title {
  color: var(--brand);
}
.confirm__ok {
  color: var(--s-offer);
}
.confirm__fields {
  margin: 0;
}
.confirm__row {
  display: flex;
  gap: 8px;
  line-height: 1.9;
}
.confirm__row dt {
  flex: none;
  width: 68px;
  color: var(--c-text-2);
}
.confirm__row dd {
  margin: 0;
  color: var(--c-text);
  word-break: break-word;
}
.confirm__jd {
  color: var(--c-text-2);
}
.confirm__error {
  margin: 6px 0 0;
  color: var(--el-color-danger);
  line-height: 1.6;
}
.confirm__ops {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 10px;
}
</style>
