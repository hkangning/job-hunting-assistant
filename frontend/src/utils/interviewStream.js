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

/**
 * 点评 / 总结正文分段（渲染用）：把「亮点 / 不足 / 参考要点（建议）」解析成可着色的段落。
 *
 * prompt 固定了这些节的输出格式（`- ` 开头 + 中文冒号），但模型输出会有偏差——
 * 容忍无 `- ` 前缀与全/半角冒号；认不出前缀的行**并入上一段**（长段落换行不断段）；
 * 整段都没有结构时按普通文本返回（渲染层原样显示，不丢内容）。
 * 总结报告复用同一套规则（「建议」归指导类，与「参考要点」同色）。
 */
const REVIEW_SECTIONS = [
  { pattern: /^亮点\s*[：:]/, kind: 'good', label: '亮点' },
  { pattern: /^不足\s*[：:]/, kind: 'bad', label: '不足' },
  { pattern: /^参考(?:要点|答案)\s*[：:]/, kind: 'note', label: '参考要点' },
  { pattern: /^建议\s*[：:]/, kind: 'note', label: '建议' }
]

export function splitReview(text) {
  const parts = []
  for (const raw of String(text ?? '').split('\n')) {
    const line = raw.trim()
    if (!line) {
      // 空行只在普通文本段内保留（结构段的空行由分段本身表达）
      if (parts.length && parts[parts.length - 1].kind === 'plain') parts[parts.length - 1].text += '\n'
      continue
    }
    const body = line.replace(/^[-•]\s*/, '')
    const hit = REVIEW_SECTIONS.find((s) => s.pattern.test(body))
    if (hit) {
      parts.push({ kind: hit.kind, label: hit.label, text: body.replace(hit.pattern, '').trim() })
    } else if (parts.length) {
      parts[parts.length - 1].text += '\n' + body
    } else {
      parts.push({ kind: 'plain', label: null, text: body })
    }
  }
  return parts
}

/** 面试阶段的中文名（`stages` 里给的是枚举值）。 */
export const STAGE_LABELS = { INTRO: '自我介绍', TECH: '技术问答', PROJECT: '项目深挖' }

/**
 * 阶段进度：给定题号返回所处阶段与阶段内进度；**越界 / 无计划返回 null**。
 *
 * 阶段计划 `stages = [{stage, count}]` 由后端随会话下发——分配算法（自我介绍 1 题、
 * 项目深挖按简历题量折算等）留在后端，前端不复刻；后端未落地该字段时调用方
 * 降级为「第 N/M 题」（本函数返回 null）。
 */
export function stageProgress(stages, seq) {
  if (!Array.isArray(stages) || !seq) return null
  let start = 0
  for (const item of stages) {
    const count = item?.count || 0
    if (seq > start && seq <= start + count) {
      return {
        stage: item.stage,
        label: STAGE_LABELS[item.stage] || item.stage,
        index: seq - start,
        count
      }
    }
    start += count
  }
  return null
}

/** 面试强度三档的中文名（会话 DTO 的 `intensity`；存量会话后端按 MEDIUM 兜底，不返回 null）。 */
export const INTENSITY_LABELS = { LARGE: '大厂', MEDIUM: '中厂', SMALL: '小厂' }

/**
 * 解析总结流末的「错题候选」段（接口文档 v1.36 §3.7）——`data.text` 为完整 JSON：
 * `{"candidates":[{"content","answer","direction"}]}`。
 * 容忍 ```json 围栏与前后杂文；无法解析 / 结构不符返回 `[]`（该段可缺席，不得依赖其存在）。
 */
export function parseCandidates(text) {
  if (!text) return []
  let raw = String(text).trim()
  const fence = raw.match(/```(?:json)?\s*([\s\S]*?)```/i)
  if (fence) raw = fence[1].trim()
  try {
    const data = JSON.parse(raw)
    const list = Array.isArray(data) ? data : data?.candidates
    if (!Array.isArray(list)) return []
    return list.filter((c) => c && typeof c.content === 'string' && c.content.trim())
  } catch {
    return []
  }
}
