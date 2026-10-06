/**
 * 播报文本准备（SRS §3.11 / 接口文档 §3.13）。
 *
 * 三个纯函数：
 * - `toSpeakableText`：把一条消息的原始文本整理成可朗读文本——标题行
 *   （`## 点评` / `## 下一题`）与评分行（`评分 8/10`）不念，复用渲染层的同一套
 *   剥离口径（practiceStream 的 toPlainText / parseRoundScore）。
 * - `expandSpeechChunks`：播放段数组（`[{text, key}]`，key = 该条消息）展开为
 *   chunk 序列——段内按 2000 字切分（接口上限）、key 透传（播放器据此做段级点亮）。
 * - `splitForTts`：`/tts/synthesize` 的 `text` 上限 2000 字，长回复按
 *   段落 → 句子 → 硬切的顺序分段，逐段合成后连播。
 */
import { toPlainText, parseRoundScore } from './practiceStream.js'

/** 按消息形态取可朗读文本：点评剥评分行与标记，其余（提问等）走纯文本。 */
export function toSpeakableText(kind, text) {
  if (kind === 'review') return parseRoundScore(text).note.trim()
  return toPlainText(text).trim()
}

/** 段数组 → chunk 序列（段内切 ≤2000 字；空段不产生 chunk；key 原样透传）。 */
export function expandSpeechChunks(segments) {
  const out = []
  for (const seg of segments ?? []) {
    const key = seg?.key ?? null
    for (const part of splitForTts(String(seg?.text ?? ''))) out.push({ text: part, key })
  }
  return out
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
