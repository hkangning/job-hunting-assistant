<script setup>
/**
 * 选择题的选项列表（点选）。
 *
 * 陪练页与错题本复习共用——两处的选项形态完全一致（键 + 文本、选中态、禁用态），
 * 各写一份迟早会漂移。选中态用陪练模块色，与两个页面的主色一致。
 */
defineProps({
  options: { type: Array, default: () => [] },
  modelValue: { type: String, default: '' },
  disabled: { type: Boolean, default: false }
})
const emit = defineEmits(['update:modelValue'])
</script>

<template>
  <div class="choices">
    <button
      v-for="opt in options"
      :key="opt.key"
      type="button"
      class="choice"
      :class="{ 'choice--picked': modelValue === opt.key }"
      :disabled="disabled"
      :aria-pressed="modelValue === opt.key"
      @click="emit('update:modelValue', opt.key)"
    >
      <span class="choice__key">{{ opt.key }}</span>
      <span class="choice__text">{{ opt.text }}</span>
    </button>
  </div>
</template>

<style scoped>
/* 竖排——选项文本通常较长，横排会挤成两行以上反而难扫 */
.choices {
  display: grid;
  gap: 8px;
}
.choice {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  width: 100%;
  padding: 10px 12px;
  font: inherit;
  text-align: left;
  color: var(--c-text);
  background: var(--c-card);
  border: 1px solid var(--c-border);
  border-radius: var(--r-control);
  cursor: pointer;
}
.choice:hover:not(:disabled) {
  border-color: var(--m-practice);
}
.choice:focus-visible {
  outline: 2px solid var(--m-practice);
  outline-offset: 2px;
}
.choice:disabled {
  cursor: not-allowed;
  opacity: 0.6;
}
.choice--picked {
  border-color: var(--m-practice);
  background: color-mix(in srgb, var(--m-practice) 8%, var(--c-card));
}
.choice__key {
  flex: 0 0 auto;
  display: grid;
  place-items: center;
  width: 22px;
  height: 22px;
  font-size: var(--fs-xs);
  font-weight: 700;
  color: var(--c-text-2);
  background: var(--c-bg);
  border-radius: var(--r-mark);
}
.choice--picked .choice__key {
  color: #fff;
  background: var(--m-practice);
}
.choice__text {
  flex: 1;
  min-width: 0;
  font-size: var(--fs-body);
  line-height: 1.6;
  word-break: break-word;
}
</style>
