/**
 * 流式播报的增量分句（步骤 24 播报口径的流式版）。
 *
 * 播放单元从「整条消息」细化到「一句话」：delta 边到边切，凑满一句就送合成——
 * 语音因此与文字输出基本同步（设计见
 * `docs/superpowers/specs/2026-10-07-面试流式同步播报-design.md`）。
 *
 * 「不念什么」与 `ttsText.toSpeakableText` 同一口径，只是改成增量判定：
 * - 标题行（`## 点评` / `## 下一题`）整行不念——行首 `#` 即定，跨 delta 切断也认；
 * - 点评**段首**的评分 token（`评分 8/10，` / `8/10，` / `7 分，`）剥掉，与
 *   `practiceStream.parseRoundScore` 同源；判定前摇按住不发（缓冲还只有「评分 8」这种一半时）；
 * - 行内标记 `**` 与反引号去掉；句尾孤立的 `*` 按住——可能是 `**` 的前半，等下一片再定。
 *
 * 纯函数（无 IO / 无 DOM），单测 `tests/ttsStream.test.js`。
 */

/** 句末标点：到这儿成句。 */
const SENTENCE_END = /[。！？；!?;]/
/** 段首评分 token（与 practiceStream.parseRoundScore 同口径，只用于剥掉）。 */
const SCORE_TOKEN = /^(?:评分\s*)?\d+(?:\.\d+)?\s*(?:\/\s*10|分)\s*[，,：:.。]?\s*/
/** 评分 token 的**可能前缀**：整个缓冲还落在它的形状里 → 按住，等下一片再定论。 */
const SCORE_PREFIX = /^\s*评?分?\s*\d*(?:\.\d*)?\s*(?:\/\s*\d*|分)?\s*[，,：:.。]?\s*$/
/** 行内标记（与 toPlainText 同口径）。 */
const MARK = /\*\*|`/g
/** 无标点长串的硬切上限：正常点评 / 题干远到不了，纯属背压保护。 */
const HARD_LIMIT = 60

/**
 * 建一个增量分句器。
 *
 * @param {'review'|'question'|string} kind 段形态——只有 `review` 剥段首评分 token
 * @returns {{ feed: (text: string) => string[], flush: () => string[] }}
 *   `feed` 喂增量、返回「这会儿可以送合成的句子」；`flush` 在流结束时吐余量
 */
export function createSpeechSegmenter(kind = 'question') {
  let rest = '' // 未定文本（含跨片的半行 / 半句）
  let lineStart = true // 缓冲起点是否在行首
  let skipLine = false // 当前行是标题行：丢到行尾
  let head = kind === 'review' // 段首评分 token 尚未定论（一旦有正文吐出就永久关闭）

  function feed(text) {
    rest += String(text ?? '')
    return drain(false)
  }

  function flush() {
    return drain(true)
  }

  function drain(atEnd) {
    const out = []
    for (;;) {
      // 行首：丢掉空行与缩进空白
      if (lineStart) {
        rest = rest.replace(/^[ \t\r\n]+/, '')
        if (!rest) {
          if (!atEnd) break
          break
        }
        if (rest.startsWith('#')) skipLine = true
      }
      // 标题行：整行丢到行尾（含换行）
      if (skipLine) {
        const nl = rest.indexOf('\n')
        if (nl === -1) {
          if (!atEnd) break
          rest = ''
          skipLine = false
          break
        }
        rest = rest.slice(nl + 1)
        skipLine = false
        lineStart = true
        continue
      }
      // 点评段首的评分 token：能剥就剥，还是「一半」就按住
      if (head && lineStart) {
        const matched = rest.match(SCORE_TOKEN)
        if (matched) {
          rest = rest.slice(matched[0].length)
          head = false
          continue
        }
        if (!atEnd && SCORE_PREFIX.test(rest)) break
        head = false
      }
      // 找这一句的终点：句末标点（含）/ 换行（不含）/ 硬切上限
      let cut = -1
      let dropNl = false
      for (let i = 0; i < rest.length; i++) {
        const ch = rest[i]
        if (ch === '\n') {
          cut = i
          dropNl = true
          break
        }
        if (SENTENCE_END.test(ch)) {
          cut = i + 1
          break
        }
        if (i + 1 >= HARD_LIMIT) {
          cut = i + 1
          break
        }
      }
      if (cut < 0) {
        if (!atEnd) break // 还凑不齐一句：等下一片
        cut = rest.length
      }
      let text = rest.slice(0, cut)
      rest = rest.slice(dropNl ? cut + 1 : cut)
      lineStart = dropNl
      text = text.replace(MARK, '')
      if (!atEnd && text.endsWith('*')) {
        // 孤立的 `*` 可能是 `**` 的前半：按住，与下一片配对后再念
        rest = '*' + rest
        text = text.slice(0, -1)
      }
      text = text.trim()
      if (text) out.push(text)
      if (!rest && atEnd) break
    }
    return out
  }

  return { feed, flush }
}
