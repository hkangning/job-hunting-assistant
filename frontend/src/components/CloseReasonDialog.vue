<script setup>
// 「标记为已结束」时的原因选择对话框。
// 与普通流转的轻量确认不同：结束原因是终态记录的唯一分类信息，选错这条记录就废了，
// 故单独一步让用户明确选择，而不是给个「是否流转」的确认了事。
import { ref, watch } from 'vue'
import { CLOSE_REASONS } from '../constants/application'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  item: { type: Object, default: null }
})
const emit = defineEmits(['update:modelValue', 'confirmed', 'cancel'])

const reason = ref('FAILED')
// el-dialog 关闭时一律触发 @close，若不加区分会把「确认」也当成「取消」→ 卡片被误还原
let confirmed = false

watch(
  () => props.modelValue,
  (visible) => {
    if (visible) {
      reason.value = 'FAILED'
      confirmed = false
    }
  }
)

function close() {
  emit('update:modelValue', false)
}

function onDialogClose() {
  if (!confirmed) emit('cancel')
  confirmed = false
}

function onCancel() {
  close() // 关闭即可，统一由 onDialogClose 分派 cancel
}

function onConfirm() {
  confirmed = true
  emit('confirmed', reason.value)
  close()
}
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    title="标记为已结束"
    width="440px"
    @update:model-value="close"
    @close="onDialogClose"
  >
    <div class="close-reason">
      <div v-if="item" class="close-reason__target">{{ item.company }} · {{ item.position }}</div>
      <div class="close-reason__label">这次结束的原因是？</div>

      <el-radio-group v-model="reason" class="close-reason__options">
        <el-radio v-for="r in CLOSE_REASONS" :key="r.value" :value="r.value" class="close-reason__option">
          <span class="close-reason__option-label">{{ r.label }}</span>
          <span class="close-reason__option-hint">{{ r.hint }}</span>
        </el-radio>
      </el-radio-group>
    </div>

    <template #footer>
      <el-button @click="onCancel">取消</el-button>
      <el-button type="primary" @click="onConfirm">确认结束</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.close-reason__target {
  font-size: var(--fs-body);
  font-weight: 600;
  color: var(--c-text);
  margin-bottom: 14px;
}
.close-reason__label {
  font-size: var(--fs-sm);
  color: var(--c-text-2);
  margin-bottom: 8px;
}
.close-reason__options {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 8px;
}
.close-reason__option {
  height: auto;
  margin-right: 0;
  padding: 9px 12px;
  border: 1px solid var(--c-border);
  border-radius: var(--r-control);
  align-items: flex-start;
}
.close-reason__option.is-checked {
  border-color: var(--brand);
  background: var(--el-color-primary-light-9);
}
.close-reason__option-label {
  font-size: var(--fs-body);
  color: var(--c-text);
}
.close-reason__option-hint {
  display: block;
  font-size: var(--fs-xs);
  color: var(--c-text-3);
  line-height: 1.5;
}
</style>
