/**
 * 陪练元数据的小工具（`GET /practice/meta` 的消费侧）。
 *
 * 错题本与陪练页都要把领域枚举值翻成中文名——两处各写一份迟早会有一处漏改，
 * 就像复习视图曾经直接显示 `DESIGN` 那样。
 */

/** 把 meta 的「栈 → 领域」摊平成 `{枚举值: 中文名}`。 */
export function directionLabelMap(meta) {
  const map = {}
  for (const stack of meta?.stacks || []) {
    for (const domain of stack.domains || []) map[domain.value] = domain.label
  }
  return map
}

/** 题型枚举 → 中文名（错题本列表等处以标签形式展示）。 */
export const QTYPE_LABELS = {
  CHOICE: '选择题',
  SUBJECTIVE: '主观题',
  SCENARIO: '场景题'
}

/**
 * 把 meta 的「栈 → 领域」摊平成下拉选项 `[{value, label}]`。
 *
 * label 带栈前缀：领域名在跨栈语境下容易失去上下文（「并发编程」是哪一块的），
 * 下拉里一眼能看清归属。错题本的领域筛选与添加弹窗共用同一份。
 */
export function directionOptions(meta) {
  const options = []
  for (const stack of meta?.stacks || []) {
    for (const domain of stack.domains || []) {
      options.push({ value: domain.value, label: `${stack.label} · ${domain.label}` })
    }
  }
  return options
}
