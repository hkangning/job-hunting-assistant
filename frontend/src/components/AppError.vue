<script setup>
/**
 * 统一错误态（步骤 27 交互收口）。
 *
 * 形态从既有范本提取（Overview 错误条 + Campus 重试）：白卡 + 细边框 + 警示图标
 * + 文案 + 重试按钮。不用鲜艳红底——项目调性「求职是压力源，界面不加重紧张感」，
 * 红色只落在图标描边上（Element 危险色），块面保持中性。
 *
 * 用于页面级 / 区块级加载失败；小容器内的一行错误提示（如抽屉内）不必套组件。
 */
defineProps({
  message: { type: String, default: '' },
  /** 'md' 页面级 | 'sm' 卡内 */
  size: { type: String, default: 'md' },
  retryText: { type: String, default: '重试' },
  retryable: { type: Boolean, default: true }
})

defineEmits(['retry'])
</script>

<template>
  <div class="app-error" :class="`app-error--${size}`" role="alert">
    <svg class="app-error__icon" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
      <circle cx="12" cy="12" r="9" stroke="var(--el-color-danger)" stroke-width="1.6" />
      <path d="M12 7.5v5.5" stroke="var(--el-color-danger)" stroke-width="1.6" stroke-linecap="round" />
      <circle cx="12" cy="16.4" r="1.1" fill="var(--el-color-danger)" />
    </svg>
    <span class="app-error__text">{{ message }}</span>
    <!-- 默认插槽：场景专属动作（如 10012 的「前往配置」），排在内置重试按钮之前 -->
    <slot />
    <el-button v-if="retryable" size="small" @click="$emit('retry')">{{ retryText }}</el-button>
  </div>
</template>

<style scoped>
.app-error {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 18px;
  background: var(--c-card);
  border: 1px solid var(--c-border);
  border-radius: var(--r-card);
  font-size: var(--fs-body);
  color: var(--c-text);
}
.app-error--sm {
  padding: 10px 14px;
  font-size: var(--fs-sm);
}
.app-error__icon {
  width: 18px;
  height: 18px;
  flex: none;
}
.app-error--sm .app-error__icon {
  width: 16px;
  height: 16px;
}
.app-error__text {
  flex: 1;
  min-width: 0;
  line-height: 1.6;
}
</style>
