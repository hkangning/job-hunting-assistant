<script setup>
/**
 * 面试消息流渲染（纯展示）。
 *
 * 只认 `utils/interviewStream.js` 产出的消息序列——恢复与流式两条路径共用同一份渲染。
 * 滚动与高度由页面控制（这里只管内容）。
 *
 * **三种内容三种形态**（原版全用同款「白底细边框」，扫一眼分不清角色与层次）：
 *   提问 —— 角色徽标 + 白底气泡（模块色左条）；作答 —— 右对齐、中性浅底 + 「我」徽标；
 *   点评 —— 模块色浅底卡 + 大号分数 + **分段落色**（亮点 / 不足 / 参考要点）。
 *
 * **打字机只给流式中的消息**：`streaming` 为真才走 `StreamText`，历史消息（恢复路径）
 * 直接渲染纯文本——否则刷新后整屏历史会逐字重打一遍，像重播。点评在流式期间按整段
 * 走打字机、定稿后再切分段排版（避免逐段打字机的多实例节奏差）。
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
import ReviewBody from './ReviewBody.vue'
import MetricsCard from './MetricsCard.vue'
import { Headset, VideoPause } from '@element-plus/icons-vue'
import { parseRoundScore, toPlainText } from '../../utils/practiceStream'

defineProps({
  /** `{ kind, seq?, text, skipped?, score?, streaming? }[]` */
  messages: { type: Array, default: () => [] },
  /** 播报开关（settings.tts_enabled）：关时不显示播报按钮 */
  speakEnabled: { type: Boolean, default: false },
  /** 正在播报的消息对象引用（该条按钮显示「停止」态） */
  speakingKey: { type: Object, default: null }
})
defineEmits(['speak'])

/** 点评正文：剥标题行 / 行内标记，并去掉首行评分（格式不符时原样返回，剥不掉也无害）。 */
function reviewBody(text) {
  return parseRoundScore(text).note
}
</script>

<template>
  <div class="msgs">
    <template v-for="(m, i) in messages" :key="i">
      <!-- 面试官提问 -->
      <div v-if="m.kind === 'question'" class="msgs__row">
        <span class="msgs__avatar msgs__avatar--iv">面</span>
        <div class="msgs__bubble msgs__bubble--question">
          <div class="msgs__meta">
            <span class="msgs__who msgs__who--interviewer">面试官</span>
            <span v-if="m.seq != null" class="msgs__seq">第 {{ m.seq }} 题</span>
            <el-tooltip
              v-if="speakEnabled && !m.streaming"
              :content="speakingKey === m ? '停止朗读' : '朗读本题'"
              placement="top"
            >
              <el-button
                class="msgs__speak"
                :class="{ 'msgs__speak--on': speakingKey === m }"
                link
                :icon="speakingKey === m ? VideoPause : Headset"
                @click="$emit('speak', i)"
              />
            </el-tooltip>
          </div>
          <StreamText v-if="m.streaming" :text="toPlainText(m.text)" :streaming="true" />
          <span v-else class="msgs__static">{{ toPlainText(m.text) }}</span>
        </div>
      </div>

      <!-- 我的作答 -->
      <div v-else-if="m.kind === 'answer'" class="msgs__row msgs__row--right">
        <div class="msgs__bubble msgs__bubble--answer">
          <span v-if="m.skipped" class="msgs__skipped">已跳过本题</span>
          <span v-else class="msgs__answer-text">{{ m.text }}</span>
        </div>
        <span class="msgs__avatar msgs__avatar--me">我</span>
      </div>

      <!-- 表达力指标卡（步骤 25）：作答与点评之间——先看「说得怎么样」再看「答得怎么样」 -->
      <div v-else-if="m.kind === 'metrics'" class="msgs__metrics">
        <MetricsCard :metrics="m.metrics" />
      </div>

      <!-- 点评卡片 -->
      <div v-else-if="m.kind === 'review'" class="msgs__review">
        <div class="msgs__review-head">
          <span class="msgs__review-title">点评</span>
          <span class="msgs__review-tools">
            <el-tooltip
              v-if="speakEnabled && !m.streaming"
              :content="speakingKey === m ? '停止朗读' : '朗读点评'"
              placement="top"
            >
              <el-button
                class="msgs__speak"
                :class="{ 'msgs__speak--on': speakingKey === m }"
                link
                :icon="speakingKey === m ? VideoPause : Headset"
                @click="$emit('speak', i)"
              />
            </el-tooltip>
            <span v-if="m.score != null" class="msgs__score">{{ m.score }}<i>分</i></span>
          </span>
        </div>
        <div class="msgs__review-body">
          <!-- 流式期间整段打字机；定稿后切分段着色（与回看页的总结卡共用 ReviewBody） -->
          <StreamText v-if="m.streaming" :text="reviewBody(m.text)" :streaming="true" />
          <ReviewBody v-else :text="reviewBody(m.text)" />
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.msgs {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.msgs__row {
  display: flex;
  align-items: flex-start;
  gap: 10px;
}
.msgs__row--right {
  justify-content: flex-end;
}

/* 角色徽标：圆形、模块色浅底——让「谁在说话」一眼可辨（原来只有一行小字） */
.msgs__avatar {
  flex: 0 0 auto;
  width: 30px;
  height: 30px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: var(--fs-xs);
  font-weight: 600;
  border-radius: 50%;
  user-select: none;
}
.msgs__avatar--iv {
  color: var(--m-interview);
  background: color-mix(in srgb, var(--m-interview) 14%, var(--c-card));
  border: 1px solid color-mix(in srgb, var(--m-interview) 30%, var(--c-card));
}
.msgs__avatar--me {
  color: var(--c-text-2);
  background: var(--c-bg);
  border: 1px solid var(--c-border);
}

.msgs__bubble {
  max-width: 76%;
  padding: 10px 14px;
  border-radius: 10px;
  font-size: var(--fs-body);
  line-height: 1.7;
  color: var(--c-text);
}
.msgs__bubble--question {
  background: var(--c-card);
  border: 1px solid var(--c-border);
  border-left: 3px solid var(--m-interview);
  border-top-left-radius: 3px;
  box-shadow: 0 1px 2px rgba(42, 39, 64, 0.04);
}
.msgs__bubble--answer {
  background: var(--c-bg);
  border: 1px solid var(--c-divider);
  border-top-right-radius: 3px;
}

.msgs__meta {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-bottom: 4px;
}
/* 朗读图标：常显（可发现性——不做 hover 隐藏）、播放中高亮并变停止图标 */
.msgs__speak.el-button {
  padding: 0 2px;
  font-size: 16px;
  color: var(--c-text-3);
}
.msgs__speak.el-button:hover,
.msgs__speak--on.el-button {
  color: var(--m-interview);
}
.msgs__meta .msgs__speak.el-button {
  align-self: center;
  margin-left: auto;
}
.msgs__who {
  font-size: var(--fs-xs);
}
.msgs__who--interviewer {
  color: var(--m-interview);
  font-weight: 600;
}
.msgs__seq {
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}

.msgs__skipped {
  color: var(--c-text-3);
}
/* 静态文本：与 StreamText 的排版口径一致（历史消息不走打字机） */
.msgs__static,
.msgs__answer-text {
  white-space: pre-wrap;
  word-break: break-word;
}

/* 点评：独立形态——模块色浅底 + 模块色描边，与白底气泡分开层次 */
.msgs__review {
  border: 1px solid color-mix(in srgb, var(--m-interview) 30%, var(--c-card));
  border-radius: 10px;
  background: color-mix(in srgb, var(--m-interview) 6%, var(--c-card));
  padding: 12px 16px 14px;
  box-shadow: 0 1px 2px rgba(42, 39, 64, 0.04);
}
.msgs__review-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}
.msgs__review-title {
  font-size: var(--fs-sm);
  font-weight: 600;
  color: var(--m-interview);
}
.msgs__review-tools {
  display: inline-flex;
  align-items: center;
  gap: 10px;
}
.msgs__score {
  font-size: 22px;
  font-weight: 700;
  line-height: 1;
  color: var(--m-interview);
}
.msgs__score i {
  font-size: var(--fs-xs);
  font-style: normal;
  font-weight: 400;
  margin-left: 2px;
}

.msgs__review-body {
  color: var(--c-text);
}
</style>
