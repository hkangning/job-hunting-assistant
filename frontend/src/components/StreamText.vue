<script setup>
/**
 * 打字机文本（步骤 11）：把「突变式」的流式文本平滑成逐字出现。
 *
 * 后端 delta 的粒度是 LLM token、且多个 delta 可能被网络合并到达，直接渲染有跳字感。
 * 本组件**只做展示**——不发起请求、不感知 SSE，以便各链路按自己的版式复用它。
 */
import { onUnmounted, ref, watch } from 'vue'

const props = defineProps({
  text: { type: String, default: '' },
  streaming: { type: Boolean, default: false }
})

const displayed = ref('')
let rafId = null

/**
 * 每帧吐出量分三档：细腻（1 字 / 60 字每秒，与 LLM 常见速率相当，打字感最自然）、
 * 跟上（2 字）、追赶长文（5 字，避免几千字的长报告永远追不上）。
 *
 * 不按 `lag / N` 无上限提速：那样首个 delta 到达时（lag 已有几十字）会一帧吐十几个字，
 * 短文本 0.1 秒内直接蹦完，打字机等于没做。
 */
function tick() {
  const target = props.text || ''
  if (displayed.value.length >= target.length) {
    // 文本被整体替换（如切换记录）时直接同步，不做退格动画
    if (!target.startsWith(displayed.value)) displayed.value = target
    rafId = null
    return
  }
  const lag = target.length - displayed.value.length
  const step = lag > 240 ? 5 : lag > 60 ? 2 : 1
  displayed.value = target.slice(0, displayed.value.length + step)
  rafId = requestAnimationFrame(tick)
}

watch(
  () => props.text,
  () => {
    if (rafId === null) rafId = requestAnimationFrame(tick)
  }
)

onUnmounted(() => {
  if (rafId !== null) cancelAnimationFrame(rafId)
  displayed.value = props.text || '' // 切页时补全余下文本，不留半截
})
</script>

<template>
  <span class="stream-text">{{ displayed }}<span v-if="streaming" class="stream-text__caret" /></span>
</template>

<style scoped>
.stream-text {
  white-space: pre-wrap;
  word-break: break-word;
}
.stream-text__caret {
  display: inline-block;
  width: 2px;
  height: 1em;
  margin-left: 2px;
  vertical-align: text-bottom;
  background: var(--brand);
  animation: stream-blink 1s steps(2, start) infinite;
}
@keyframes stream-blink {
  to {
    visibility: hidden;
  }
}
</style>
