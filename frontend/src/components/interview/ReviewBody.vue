<script setup>
/**
 * 点评 / 总结正文渲染：按「亮点 / 不足 / 参考要点 / 建议」分段着色。
 *
 * 面试消息流的点评卡与回看页的总结卡共用——同一份解析（`splitReview`）与同一份样式，
 * 两处的正文观感保持一致；解析规则或配色要改时只动这一个文件。
 */
import { splitReview } from '../../utils/interviewStream'

defineProps({
  /** 已剥标题行 / 评分行的正文（`toPlainText` + `parseRoundScore().note` 之后） */
  text: { type: String, default: '' }
})
</script>

<template>
  <div class="body">
    <p
      v-for="(part, i) in splitReview(text)"
      :key="i"
      class="body__part"
      :class="`body__part--${part.kind}`"
    >
      <span v-if="part.label" class="body__part-label">{{ part.label }}</span>
      <span class="body__part-text">{{ part.text }}</span>
    </p>
  </div>
</template>

<style scoped>
.body {
  font-size: var(--fs-body);
  line-height: 1.8;
  color: var(--c-text);
}
/* 分段条目：标签定宽成一列，文本起点对齐 */
.body__part {
  display: flex;
  gap: 8px;
  margin: 0;
}
.body__part + .body__part {
  margin-top: 4px;
}
.body__part-label {
  flex: 0 0 auto;
  width: 4.2em;
  font-size: var(--fs-sm);
  font-weight: 600;
  line-height: 1.8;
}
.body__part-text {
  flex: 1;
  min-width: 0;
  white-space: pre-wrap;
  word-break: break-word;
}
/* 分段落色：亮点=练习绿（正向）、不足=经验橙（待改）、参考要点 / 建议=主色（指导） */
.body__part--good .body__part-label {
  color: var(--m-practice);
}
.body__part--bad .body__part-label {
  color: var(--m-experience);
}
.body__part--note .body__part-label {
  color: var(--brand);
}
</style>
