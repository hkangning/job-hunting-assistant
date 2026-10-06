/**
 * 播报文本准备（SRS §3.11 / 接口文档 §3.13）。
 *
 * 两个纯函数：
 * - `buildRoundSpeech`：把一轮 AI 回复（点评 + 下一题）整理成可朗读文本——
 *   标题行（`## 点评` / `## 下一题`）与评分行（`评分 8/10`）不念，复用渲染层的
 *   同一套剥离口径（practiceStream 的 toPlainText / parseRoundScore）。
 * - `splitForTts`：`/tts/synthesize` 的 `text` 上限 2000 字，长回复按
 *   段落 → 句子 → 硬切的顺序分段，逐段合成后连播。
 */
import { toPlainText, parseRoundScore } from './practiceStream.js'

/** 一轮回复的播报文本：点评（剥评分行与标记）+ 下一题题干。任一段可缺省。 */
export function buildRoundSpeech(reviewText, questionText) {
  const review = parseRoundScore(reviewText).note.trim()
  const question = toPlainText(questionText).trim()
  return [review, question].filter(Boolean).join('\n\n')
}

/** 按 `limit` 上限切分播报文本；返回非空段数组（顺序即播放顺序）。 */
export function splitForTts(text, limit = 2000) {
  const out = []
  for (const para of String(text ?? '').split(/\n{2,}/)) {
    const p = para.trim()
    if (!p) continue
    if (p.length <= limit) {
      out.push(p)
      continue
    }
    // 超限段落：按句末标点切成句子，再累积到不超过 limit 的块
    let buf = ''
    for (const seg of p.split(/(?<=[。！？；!?;])/)) {
      if (seg.length > limit) {
        // 单句仍超限（无标点长串）：先冲刷缓冲，再硬切
        if (buf) {
          out.push(buf)
          buf = ''
        }
        for (let i = 0; i < seg.length; i += limit) out.push(seg.slice(i, i + limit))
        continue
      }
      if (buf.length + seg.length > limit) {
        out.push(buf)
        buf = seg
      } else {
        buf += seg
      }
    }
    if (buf) out.push(buf)
  }
  return out
}
