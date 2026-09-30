/**
 * 面试会话的视图模型（纯函数）。
 *
 * 三个来源——恢复用的 `qa_list`、流式 `delta`、本地提交的作答——统一翻译成消息序列，
 * 渲染层只认 `messages`；恢复与流式两条路径因此共用一套渲染。
 *
 * 消息形态：
 *   { kind: 'question', seq, text, streaming? }
 *   { kind: 'answer',   text, skipped }
 *   { kind: 'review',   score, text, streaming? }
 *
 * 尾态 `tail` 的判定口径见设计稿 §4.3；`midway` 是**容错分支**——后端一轮一次性落库、
 * 断连整轮不落（接口文档 §3.7 实现口径 1），正常数据不会停在「已作答但无下一题」，
 * 出现即按「可继续」呈现（断线重试 = 带空 `answer` 重发，服务端幂等）。
 *
 * 消息文本**不做加工**（含「## 点评」「## 下一题」标题行——落库文本恒等于 delta 拼接），
 * 显示前由渲染层统一走 `toPlainText` 剥离（`InterviewMessages.vue`）。
 */

/** `qa_list` → `{ messages, tail }`。恢复路径的唯一入口。 */
export function buildMessages(session, qaList) {
  const messages = []
  for (const qa of qaList || []) {
    messages.push({ kind: 'question', seq: qa.seq, text: qa.question || '' })
    if (qa.answer || qa.skipped) {
      messages.push({ kind: 'answer', text: qa.answer || '', skipped: !!qa.skipped })
    }
    if (qa.review || qa.score != null) {
      messages.push({ kind: 'review', score: qa.score ?? null, text: qa.review || '' })
    }
  }
  return { messages, tail: inferTail(session, qaList || []) }
}

function inferTail(session, qaList) {
  if (!qaList.length) return 'empty'
  const last = qaList[qaList.length - 1]
  // 未作答：当前待答的题（等待输入）——刷新恢复的主路径
  if (!last.answer && !last.skipped) return 'awaiting-answer'
  // 已作答且到题量：面试结束（点评缺失也照结束论——不会再出题）
  if (last.seq >= (session?.question_count || 0)) return 'finished'
  // 已作答但下一题未生成 / 点评未完成：可继续
  return 'midway'
}

/** 流式增量归段：`review` → 点评卡片；`next_question` → 提问气泡；无 section → 末尾流式消息。 */
export function applyDelta(messages, delta) {
  const { text = '', section } = delta || {}
  const last = messages[messages.length - 1]
  if (section === 'review') {
    if (last?.kind === 'review' && last.streaming) last.text += text
    else messages.push({ kind: 'review', score: null, text, streaming: true })
  } else if (section === 'next_question') {
    if (last?.kind === 'question' && last.streaming) last.text += text
    else messages.push({ kind: 'question', seq: nextSeq(messages), text, streaming: true })
  } else if (last?.streaming) {
    // 纯文本降级：追加到当前流式消息，不新建
    last.text += text
  }
}

/** 下一个提问的本地题号（流式期间估算；done 时以后端 `seq` 校准）。 */
function nextSeq(messages) {
  let max = 0
  for (const m of messages) if (m.kind === 'question' && m.seq > max) max = m.seq
  return max + 1
}

/** 提交作答后本地立即插入（乐观），不等流。 */
export function appendAnswer(messages, text) {
  messages.push({ kind: 'answer', text, skipped: false })
}

/** 跳过：插入一条"已跳过"作答消息（渲染为灰字标记、无点评卡片）。 */
export function insertSkipped(messages) {
  messages.push({ kind: 'answer', text: '', skipped: true })
}

/** 流结束定稿：清掉流式标记（`done` / `error` 时调用）。 */
export function sealStreaming(messages) {
  for (const m of messages) if (m.streaming) m.streaming = false
}
