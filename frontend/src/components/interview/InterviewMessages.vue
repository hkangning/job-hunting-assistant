<script setup>
/**
 * 面试消息流渲染（纯展示）。
 *
 * 只认 `utils/interviewStream.js` 产出的消息序列——恢复与流式两条路径共用同一份渲染。
 * 滚动与高度由页面控制（这里只管内容）。
 *
 * **打字机只给流式中的消息**：`streaming` 为真才走 `StreamText`，历史消息（恢复路径）
 * 直接渲染纯文本——否则刷新后整屏历史会逐字重打一遍，像重播。
 *
 * **文本统一过 `toPlainText`**：后端按段落组织文本、标题行随 `delta` 原样下发，
 * 且落库文本恒等于拼接结果（接口文档 §3.7 实现口径 6）——恢复与流式两条路径的
 * 题干 / 点评都带「## 下一题」「## 点评」标题行，版式已由前端标签承担，渲染时剥掉；
 * 行内强调标记（`**` / 反引号）同批去掉，与陪练页同一口径。
 *
 * 点评正文再去掉首行的「评分 X/10」——分数已由点评卡片的徽章承担（与陪练页一致），
 * 正文里再留一行就是重复信息。
 */
import StreamText from '../StreamText.vue'
import { parseRoundScore, toPlainText } from '../../utils/practiceStream'

/** 点评正文：剥标题行 / 行内标记，并去掉首行评分（格式不符时原样返回，剥不掉也无害）。 */
function reviewBody(text) {
  return parseRoundScore(text).note
}

defineProps({
  /** `{ kind, seq?, text, skipped?, score?, streaming? }[]` */
  messages: { type: Array, default: () => [] }
})
</script>

<template>
  <div class="msgs">
    <template v-for="(m, i) in messages" :key="i">
      <!-- 面试官提问 -->
      <div v-if="m.kind === 'question'" class="msgs__row">
        <div class="msgs__bubble msgs__bubble--question">
          <div class="msgs__meta">
            <span class="msgs__who msgs__who--interviewer">面试官</span>
            <span v-if="m.seq != null" class="msgs__seq">第 {{ m.seq }} 题</span>
          </div>
          <StreamText v-if="m.streaming" :text="toPlainText(m.text)" :streaming="true" />
          <span v-else class="msgs__static">{{ toPlainText(m.text) }}</span>
        </div>
      </div>

      <!-- 我的作答 -->
      <div v-else-if="m.kind === 'answer'" class="msgs__row msgs__row--right">
        <div class="msgs__bubble msgs__bubble--answer">
          <div class="msgs__meta msgs__meta--right">
            <span class="msgs__who msgs__who--me">我</span>
          </div>
          <span v-if="m.skipped" class="msgs__skipped">已跳过本题</span>
          <span v-else class="msgs__answer-text">{{ m.text }}</span>
        </div>
      </div>

      <!-- 点评卡片 -->
      <div v-else-if="m.kind === 'review'" class="msgs__review">
        <div class="msgs__review-head">
          <span class="msgs__review-title">点评</span>
          <span v-if="m.score != null" class="msgs__score">{{ m.score }}<i>分</i></span>
        </div>
        <div class="msgs__review-body">
          <StreamText v-if="m.streaming" :text="reviewBody(m.text)" :streaming="true" />
          <span v-else class="msgs__static">{{ reviewBody(m.text) }}</span>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.msgs {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.msgs__row {
  display: flex;
}
.msgs__row--right {
  justify-content: flex-end;
}
.msgs__bubble {
  max-width: 78%;
  padding: 10px 14px;
  border-radius: 10px;
  border: 1px solid var(--c-border);
  background: #fff;
  font-size: 14px;
  line-height: 1.7;
  color: var(--c-text);
}
.msgs__bubble--question {
  border-top-left-radius: 2px;
  border-left: 3px solid var(--m-interview);
}
.msgs__bubble--answer {
  border-top-right-radius: 2px;
  background: var(--c-bg);
}
.msgs__meta {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-bottom: 4px;
}
.msgs__meta--right {
  justify-content: flex-end;
}
.msgs__who {
  font-size: 12px;
}
.msgs__who--interviewer {
  color: var(--m-interview);
}
.msgs__who--me {
  color: var(--c-text-3);
}
.msgs__seq {
  font-size: 12px;
  color: var(--c-text-3);
}
.msgs__skipped {
  color: var(--c-text-3);
}
/* 静态文本：与 StreamText 的排版口径一致（历史消息不走打字机） */
.msgs__static {
  white-space: pre-wrap;
  word-break: break-word;
}
.msgs__answer-text {
  white-space: pre-wrap;
  word-break: break-word;
}
.msgs__review {
  border: 1px solid var(--c-border);
  border-radius: 10px;
  background: #fff;
  padding: 12px 16px;
}
.msgs__review-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
}
.msgs__review-title {
  font-size: 12px;
  color: var(--m-interview);
}
.msgs__score {
  font-size: 18px;
  font-weight: 600;
  color: var(--m-interview);
}
.msgs__score i {
  font-size: 12px;
  font-style: normal;
  font-weight: 400;
  margin-left: 2px;
}
.msgs__review-body {
  font-size: 14px;
  line-height: 1.8;
  color: var(--c-text);
}
</style>
