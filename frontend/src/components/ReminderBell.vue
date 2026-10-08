<script setup>
/**
 * 顶栏提醒铃铛（步骤 20）：未读徽标 + 面板（未读列表 / 逐条已读 / 按类型跳转）。
 *
 * 数据口径（契约先行，见设计稿与 api/reminders.js 注释）：
 * - 徽标：挂载时 `GET /reminders?checked=false&page_size=1` 轻量取 total；
 * - 面板：打开时拉 `checked=false` 第一页（20/页）+ 加载更多；
 * - 「标为已读」PUT 成功后**本地移除**（提醒完成即消失，徽标数同步 -1）。
 * 请求失败一律静默降级：徽标不显示、列表给空态，不打断任何页面操作。
 */
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Bell } from '@element-plus/icons-vue'
import { listRemindersApi, checkReminderApi } from '../api/reminders'
import { reminderMeta, remindDayLabel } from '../constants/reminder'

const router = useRouter()
const open = ref(false)
const loading = ref(false)
const errorText = ref('')
const items = ref([])
const total = ref(0)
const unread = ref(0)

const PAGE_SIZE = 20
const metaOf = (r) => reminderMeta(r.reminder_type)

async function fetchUnreadCount() {
  try {
    const data = await listRemindersApi({ checked: false, page_size: 1 }, { silent: true })
    unread.value = data.total ?? (data.items || []).length
  } catch {
    unread.value = 0 // 静默降级：徽标不显示
  }
}

async function load(reset = false) {
  loading.value = true
  errorText.value = ''
  try {
    const page = reset ? 1 : Math.floor(items.value.length / PAGE_SIZE) + 1
    const data = await listRemindersApi({ checked: false, page, page_size: PAGE_SIZE }, { silent: true })
    const list = data.items || []
    items.value = reset ? list : [...items.value, ...list]
    total.value = data.total ?? items.value.length
    unread.value = total.value
  } catch {
    // 打开面板失败：给错误态 + 重试（步骤 27：此前与「暂无提醒」不可区分）
    if (reset) {
      items.value = []
      errorText.value = '提醒加载失败'
    }
  } finally {
    loading.value = false
  }
}

function onShow() {
  load(true)
}

async function markRead(r) {
  try {
    await checkReminderApi(r.id)
  } catch {
    return // 全局拦截器已提示，条目保留待重试
  }
  items.value = items.value.filter((x) => x.id !== r.id)
  total.value = Math.max(0, total.value - 1)
  unread.value = Math.max(0, unread.value - 1)
}

async function onItem(r) {
  await markRead(r)
  const route = metaOf(r).route
  if (route) {
    open.value = false
    router.push(route)
  }
}

onMounted(fetchUnreadCount)
</script>

<template>
  <el-popover
    v-model:visible="open"
    placement="bottom-end"
    :width="380"
    trigger="click"
    popper-class="reminder-pop"
    @show="onShow"
  >
    <template #reference>
      <span class="bell" title="提醒">
        <el-badge :value="unread" :max="99" :hidden="!unread">
          <el-icon :size="17"><Bell /></el-icon>
        </el-badge>
      </span>
    </template>

    <div class="rp">
      <div class="rp__head">
        <span class="rp__title">提醒</span>
        <span v-if="unread" class="rp__count">{{ unread }} 条未读</span>
      </div>

      <div v-if="loading && !items.length" class="rp__hint">正在加载…</div>
      <div v-else-if="errorText && !items.length" class="rp__hint">
        {{ errorText }}
        <el-button size="small" text type="primary" @click="load(true)">重试</el-button>
      </div>
      <div v-else-if="!items.length" class="rp__hint">暂无提醒</div>
      <template v-else>
        <div class="rp__items">
          <!-- 条目本体点击 = 已读 + 跳转；「标为已读」单独按钮 stopPropagation -->
          <div v-for="r in items" :key="r.id" class="rp__item" @click="onItem(r)">
            <span class="rp__dot" :style="{ background: metaOf(r).color }" />
            <span class="rp__body">
              <span class="rp__content">{{ r.content }}</span>
              <span class="rp__meta">{{ metaOf(r).label }} · {{ remindDayLabel(r.remind_date) }}</span>
            </span>
            <el-button size="small" plain class="rp__read" @click.stop="markRead(r)">标为已读</el-button>
          </div>
        </div>
        <el-button v-if="items.length < total" plain class="rp__more" :loading="loading" @click="load()">
          加载更多
        </el-button>
      </template>
    </div>
  </el-popover>
</template>

<style scoped>
.bell {
  display: inline-flex;
  align-items: center;
  padding: 6px;
  border-radius: var(--r-menu);
  color: var(--c-text-2);
  cursor: pointer;
}
.bell:hover {
  color: var(--brand);
  background: var(--c-bg);
}
/* popover 默认 12px 内边距：本面板自管留白，全局归零（popper 挂 body，scoped 需 :global） */
:global(.reminder-pop.el-popover) {
  padding: 0;
}
.rp__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 14px;
  border-bottom: 1px solid var(--c-divider);
}
.rp__title {
  font-size: var(--fs-title);
  font-weight: 600;
  color: var(--c-text);
}
.rp__count {
  font-size: var(--fs-xs);
  color: var(--c-text-2);
}
.rp__hint {
  padding: 30px 0;
  text-align: center;
  font-size: var(--fs-sm);
  color: var(--c-text-2);
}
.rp__items {
  max-height: 360px;
  overflow-y: auto;
}
.rp__item {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 10px 14px;
  border-bottom: 1px solid var(--c-divider);
  cursor: pointer;
}
.rp__item:last-child {
  border-bottom: none;
}
.rp__item:hover {
  background: var(--c-bg);
}
.rp__dot {
  flex: none;
  width: 8px;
  height: 8px;
  margin-top: 6px;
  border-radius: 50%;
}
.rp__body {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.rp__content {
  font-size: var(--fs-sm);
  line-height: 1.6;
  color: var(--c-text);
}
.rp__meta {
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}
.rp__read {
  flex: none;
}
.rp__more {
  display: block;
  margin: 10px auto;
}
</style>
