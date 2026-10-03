<script setup>
/**
 * 历史会话面板（覆盖消息区；输入区随面板隐藏，见 AgentFloatBall）。
 * 列表取 `GET /agent/conversations`（page_size 20 + 加载更多），点击切换会话可续聊。
 */
import { shortDateTime } from '../../utils/datetime'
import { useAgentStore } from '../../stores/agent'

const store = useAgentStore()
</script>

<template>
  <div class="history">
    <div v-if="store.history.loading && !store.history.items.length" class="history__hint">正在加载…</div>
    <div v-else-if="!store.history.items.length" class="history__hint">还没有历史对话</div>
    <template v-else>
      <button
        v-for="item in store.history.items"
        :key="item.id"
        class="history__item"
        :class="{ 'is-active': item.id === store.conversationId }"
        @click="store.loadSession(item.id)"
      >
        <span class="history__title">{{ item.title || '新对话' }}</span>
        <span class="history__time">{{ shortDateTime(item.updated_at) }}</span>
      </button>
      <el-button
        v-if="store.history.items.length < store.history.total"
        type="primary"
        plain
        :loading="store.history.loading"
        class="history__more"
        @click="store.loadHistory()"
      >加载更多</el-button>
    </template>
  </div>
</template>

<style scoped>
.history {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 10px 12px;
  background: var(--c-bg);
}
.history__hint {
  margin-top: 40px;
  text-align: center;
  color: var(--c-text-2);
  font-size: var(--fs-sm);
}
.history__item {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 12px 14px;
  margin-bottom: 8px;
  border: 1px solid var(--c-border);
  border-radius: var(--r-card);
  background: var(--c-card);
  cursor: pointer;
  text-align: left;
  font-size: var(--fs-sm);
  color: var(--c-text);
}
.history__item:hover {
  border-color: color-mix(in srgb, var(--brand) 45%, var(--c-border));
}
.history__item.is-active {
  border-color: var(--brand);
}
.history__title {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.history__time {
  flex: none;
  color: var(--c-text-3);
  font-size: var(--fs-xs);
}
.history__more {
  display: block;
  margin: 4px auto 0;
}
</style>
