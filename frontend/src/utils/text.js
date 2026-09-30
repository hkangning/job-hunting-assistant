/**
 * 文本计数的统一口径。
 *
 * 面经原文的字数上限（10000 字）由后端 Python `len` 判定，Python 字符串是**码点**序列
 * （一个 emoji 计 1）；JS 原生 `.length` 数的是 UTF-16 **码元**（同一个 emoji 计 2）。
 * 直接用 `.length` 会让含 emoji 的原文在 10000 字附近被前端误判超限。
 */

/** 按 Unicode 码点计数；空值与坏输入返回 0。 */
export function textLength(value) {
  if (value == null) return 0
  return [...String(value)].length
}
