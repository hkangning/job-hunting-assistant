<script setup>
/**
 * 可手动调高度的作答文本域：固定高度 + **顶部整条拖拽区**调整（双击恢复默认）。
 *
 * 两种常见方案的取舍（本项目实测）：
 * - 原生 `resize` 手柄：命中区仅约 16px 且紧贴滚动条，实际很难拖到（用户实测"拖不动"）；
 * - `autosize` 自动长高：内容驱动、无需操作，但本组件口径是**用户自己决定看多少**——
 *   输入不改变高度（否则与手动高度互斥：自动长高每次输入会覆盖拖出的高度）。
 *
 * 拖拽区做成**整条宽度**（约 1100×14px 命中区，不只是一枚小图标），鼠标移入即变
 * `ns-resize`、拖动时拖条加长变色——不再有"拖不动/找不到"的问题。
 */
import { onUnmounted, ref } from 'vue'

defineOptions({ inheritAttrs: false })

const props = defineProps({
  modelValue: { type: String, default: '' },
  /** 初始高度（px），同时是拖动下限——面试 3 行约 76、陪练 / 错题 4 行约 110 */
  defaultHeight: { type: Number, default: 76 }
})
const emit = defineEmits(['update:modelValue', 'submit'])

const height = ref(props.defaultHeight)
const dragging = ref(false)

let startY = 0
let startH = 0

function onDown(e) {
  dragging.value = true
  startY = e.clientY
  startH = height.value
  window.addEventListener('mousemove', onMove)
  window.addEventListener('mouseup', onUp)
  document.body.style.userSelect = 'none'
  document.body.style.cursor = 'ns-resize'
}

function onMove(e) {
  // 向上拖 = 变高（拖拽区在输入框顶部）
  const max = Math.round(window.innerHeight * 0.6)
  height.value = Math.max(props.defaultHeight, Math.min(startH + (startY - e.clientY), max))
}

function onUp() {
  dragging.value = false
  window.removeEventListener('mousemove', onMove)
  window.removeEventListener('mouseup', onUp)
  document.body.style.userSelect = ''
  document.body.style.cursor = ''
}

function reset() {
  height.value = props.defaultHeight
}

function onKeydown(e) {
  if (e.ctrlKey && e.key === 'Enter') emit('submit')
}

onUnmounted(onUp)
</script>

<template>
  <div class="rta" :class="{ 'rta--dragging': dragging }">
    <div
      class="rta__grip"
      title="拖动调整输入框高度（双击恢复默认）"
      @mousedown.prevent="onDown"
      @dblclick="reset"
    >
      <i class="rta__bar" />
    </div>
    <el-input
      :model-value="modelValue"
      type="textarea"
      v-bind="$attrs"
      @update:model-value="emit('update:modelValue', $event)"
      @keydown="onKeydown"
    />
  </div>
</template>

<style scoped>
/* 高度由拖拽结果驱动（v-bind 进 CSS）；上下限兜底，防极端拖动 */
.rta :deep(.el-textarea__inner) {
  height: v-bind(height + 'px');
  max-height: 60vh;
}
/* 拖拽区：输入框上方一整条——命中面积 = 整条宽 × 14px，不再有"拖不到" */
.rta__grip {
  display: flex;
  justify-content: center;
  align-items: center;
  padding: 4px 0 6px;
  cursor: ns-resize;
}
.rta__bar {
  width: 44px;
  height: 4px;
  border-radius: var(--r-bar);
  background: var(--c-border);
  transition: background 0.15s ease, width 0.15s ease;
}
.rta__grip:hover .rta__bar,
.rta--dragging .rta__bar {
  width: 68px;
  background: var(--brand);
}
</style>
