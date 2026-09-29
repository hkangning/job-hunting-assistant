/**
 * 陪练每轮事件流 → 视图模型（接口文档 v1.26 §3.8）。
 *
 * 与 JD 分析页「全 delta 拼接、section 只示进度」不同：本页的 section 是**板块**而非
 * 段落锚点，必须分流——`dimensions` 是一次性 JSON（不可拼接），其余 section 各自成块。
 * 本模块是纯函数、不触网络，故可脱离组件直接单测。
 */

/** 场景题四维评分的中文名（与 `dimensions` 的键一一对应）。 */
export const DIMENSION_LABELS = {
  framework: '解题框架',
  quantification: '量化估算',
  tradeoff: '取舍权衡',
  fallback: '兜底降级'
}

/** 无 section 锚点时的兜底块名（纯文本降级）。 */
const FALLBACK_SECTION = 'text'

/** 新建一轮的空壳。 */
export function createTurn() {
  return { blocks: [], dimensions: null, dimensionsRaw: '', choices: [], choicesRaw: '' }
}

/** 取某 section 的块，未出现则 undefined。 */
export function getBlock(turn, section) {
  return turn.blocks.find((b) => b.section === section)
}

/**
 * 消费一个 delta：`{text, section?}`。
 *
 * - 已知 section → 归入对应块，文本依次拼接；
 * - `dimensions` → 累积原始文本并尝试解析，成功即置 `turn.dimensions`（不进文本块），
 *   解析不出则按普通块降级展示（后端分片到达时，未解析成功前也留在原始文本里）；
 * - 无 section → 追加到最后一个块；一个块都没有时自成一块。
 */
export function applyDelta(turn, { text, section } = {}) {
  const value = text ?? ''

  if (section === 'dimensions') {
    turn.dimensionsRaw += value
    // 块始终保留：渲染是按 blocks 顺序遍历的，四维分栏要有自己的位置；
    // 解析不出时该块即以纯文本降级呈现。
    appendTo(turn, 'dimensions', value)
    const parsed = tryParseJson(turn.dimensionsRaw)
    if (parsed) turn.dimensions = parsed
    return
  }

  if (section === 'next_choices') {
    // 与 dimensions 同构：一次性 JSON，分片到达时先累积、解析成功才落到 choices。
    // 不进 blocks——选项不参与正文渲染，只供下一轮的作答区使用。
    turn.choicesRaw += value
    const parsed = tryParseJson(turn.choicesRaw)
    if (parsed && Array.isArray(parsed.options)) turn.choices = parsed.options
    return
  }

  const target = section || (turn.blocks.length ? turn.blocks[turn.blocks.length - 1].section : FALLBACK_SECTION)
  appendTo(turn, target, value)
}

function appendTo(turn, section, text) {
  const block = getBlock(turn, section)
  if (block) block.text += text
  else turn.blocks.push({ section, text })
}

function tryParseJson(text) {
  const trimmed = text.trim()
  if (!trimmed.startsWith('{')) return null
  try {
    const parsed = JSON.parse(trimmed)
    return parsed && typeof parsed === 'object' ? parsed : null
  } catch {
    return null
  }
}

/**
 * 把后端下发的 Markdown 片段转成可直接显示的纯文本。
 *
 * 两件事：①**剥掉标题行**（`## 本轮评分` / `## 点评` / `## 追问` / `## 总结`）——
 * 后端按段落组织文本、标题行随 `delta` 原样下发（与 JD 分析同一口径），而本页的
 * 版式已由前端标签承担（评分徽章、「与参考答案的差距」、「第 N 层 · 攻击面」），
 * 标题再显示一遍就是重复；②**去掉行内强调标记**（`**` 与反引号）——AI 输出常带
 * 粗体与行内代码，本页按纯文本渲染，留着标记反而干扰阅读（2026-09-28 真联调时发现）。
 */
export function toPlainText(text) {
  return String(text ?? '')
    .replace(/^#{1,6}[^\n]*\n?/gm, '')
    .replace(/\*\*/g, '')
    .replace(/`/g, '')
}

/**
 * 从 `round_score` 文本里抽出本轮评分与结论（展示口径：评分徽章 + 一句话结论）。
 *
 * 后端实际下发的是「## 本轮评分\n评分 7/10，思路清晰。」这样的 Markdown 段落
 * （真联调时确认，2026-09-28），也兼容「7 分，答得不错」这类自然语言写法。
 * 结构化分数只在结算响应里，这里取不出就不显示分数位，不阻断渲染。
 */
export function parseRoundScore(text) {
  const plain = toPlainText(text).trim()
  const matched = plain.match(/^(?:评分\s*)?(\d+(?:\.\d+)?)\s*(?:\/\s*10|分)\s*[，,：:.。]?\s*/)
  if (matched) {
    const score = Number(matched[1])
    if (score >= 0 && score <= 10) {
      return { score, note: plain.slice(matched[0].length).trim() }
    }
  }
  return { score: null, note: plain }
}
