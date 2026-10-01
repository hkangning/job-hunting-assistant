<script setup>
/**
 * 面经结构化提取状态区（接口文档 v1.39 §3.10 `POST /stream/experience-extract`）。
 *
 * 契约口径：`delta` 是**提取进度状态文字**（不逐字展示 JSON），故用状态行而非打字机；
 * `done` 时条目已由后端落库（`extra.items` 含落库 id、`extra.company` 为回填后最终公司名，
 * 两者供详情页兜底渲染）；失败（code 40002）原文仍在，可重试；
 * **10002** = 提取期间面经被其它页面删除（并发防御），重试无意义，引导返回列表。
 *
 * 自动提取只在详情页拿到 `?extract=1` 时发生一次：发起后立即清掉 query——
 * 刷新时若条目已落库自然不再渲染本组件；若仍无条目则回到手动入口，
 * 不会因为刷新而静默重复消耗 AI 调用。
 */
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { Loading } from '@element-plus/icons-vue'
import { experienceExtractStream } from '../../api/experiences'

const props = defineProps({
  experienceId: { type: Number, required: true },
  /** 进入详情页时自动发起（新增时「保存并提取」跳转带 ?extract=1） */
  autoStart: { type: Boolean, default: false },
  /** 失败态提供「关闭」入口（仅「重新提取」场景传——初次提取失败时本区常驻，无需关闭） */
  closable: { type: Boolean, default: false }
})
const emit = defineEmits(['extracted', 'close', 'state'])

const router = useRouter()

const status = ref('idle') // idle | running | done | error | gone
const progressText = ref('')
const errorMsg = ref('')
let stream = null

function start() {
  if (status.value === 'running') return
  status.value = 'running'
  progressText.value = ''
  errorMsg.value = ''

  stream = experienceExtractStream(
    { experience_id: props.experienceId },
    {
      onStart: (d) => (progressText.value = d?.message || '正在提取…'),
      onDelta: (d) => {
        if (d?.text) progressText.value = d.text
      },
      onDone: (d) => {
        status.value = 'done'
        emit('extracted', {
          items: d?.extra?.items || [],
          company: d?.extra?.company ?? null
        })
      },
      onError: (e) => {
        // 10002：提取期间面经被其它页面删除（后端并发防御）——原文已不在，重试无意义
        if (e?.code === 10002) {
          status.value = 'gone'
          errorMsg.value = e?.message || '面经已被删除，提取结果未保存'
          return
        }
        status.value = 'error'
        errorMsg.value =
          e?.code === 10012
            ? '未配置 AI 密钥，请前往 AI 配置页配置后重试'
            : `${e?.message || '提取失败'}——原文已保留，可重试`
      }
    }
  )
}

// 自动路径只走一次：清掉标记，刷新 / 重进不会静默重跑
onMounted(() => {
  if (!props.autoStart) return
  router.replace({ query: {} })
  start()
})

// 状态上报：详情页据此在提取中禁用删除（提取中删面经，落库端的并入会撞外键失败）
watch(status, (value) => emit('state', value), { immediate: true })

onUnmounted(() => {
  stream?.abort()
})
</script>

<template>
  <div class="extract">
    <template v-if="status === 'idle'">
      <p class="extract__hint">
        还没有结构化条目——AI 可以把这篇原文拆成「问题 + 答案要点」，方便后续复习和检索。
      </p>
      <el-button type="primary" @click="start">提取条目</el-button>
    </template>

    <div v-else-if="status === 'running' || status === 'done'" class="extract__running">
      <el-icon class="is-loading extract__icon"><Loading /></el-icon>
      <span>{{ status === 'done' ? '提取完成，正在加载条目…' : progressText || '正在提取…' }}</span>
    </div>

    <template v-else>
      <p class="extract__hint extract__hint--error">{{ errorMsg }}</p>
      <div class="extract__actions">
        <template v-if="status === 'gone'">
          <el-button type="primary" @click="router.push('/experiences')">返回面经列表</el-button>
        </template>
        <template v-else>
          <el-button type="primary" plain @click="start">重试提取</el-button>
          <el-button v-if="closable" @click="emit('close')">关闭</el-button>
        </template>
      </div>
    </template>
  </div>
</template>

<style scoped>
.extract {
  padding: 14px 18px;
  border: 1px dashed color-mix(in srgb, var(--m-experience) 40%, var(--c-border));
  border-radius: var(--r-card);
  background: color-mix(in srgb, var(--m-experience) 4%, var(--c-card));
}
.extract__hint {
  margin: 0 0 10px;
  font-size: var(--fs-sm);
  color: var(--c-text-2);
  line-height: 1.7;
}
.extract__hint--error {
  color: var(--el-color-danger);
}
.extract__actions {
  display: flex;
  gap: 8px;
}
.extract__running {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: var(--fs-sm);
  color: var(--c-text-2);
}
.extract__icon {
  color: var(--m-experience);
}
</style>
