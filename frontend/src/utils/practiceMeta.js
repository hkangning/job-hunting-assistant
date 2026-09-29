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
